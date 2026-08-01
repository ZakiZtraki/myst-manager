"""API clients for cryptocurrency price data and exchange integration."""

import logging
import os
import time
import hmac
import hashlib
import requests
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)
from functools import wraps


# Symbol to CoinGecko ID mapping
COINGECKO_ID_MAP = {
    'BTC': 'bitcoin',
    'ETH': 'ethereum',
    'USDT': 'tether',
    'USDC': 'usd-coin',
    'BNB': 'binancecoin',
    'XRP': 'ripple',
    'ADA': 'cardano',
    'DOGE': 'dogecoin',
    'SOL': 'solana',
    'TRX': 'tron',
    'DOT': 'polkadot',
    'MATIC': 'matic-network',
    'POL': 'polygon-ecosystem-token',  # POL (Polygon Ecosystem Token) rebranded from MATIC
    'MYST': 'mysterium',     # Mysterium Network node token
    'ZEC': 'zcash',
    'FDUSD': 'first-digital-usd',
    'LTC': 'litecoin',
    'SHIB': 'shiba-inu',
    'AVAX': 'avalanche-2',
    'LINK': 'chainlink',
    'UNI': 'uniswap',
    'ATOM': 'cosmos',
    'XLM': 'stellar',
    'ALGO': 'algorand',
    'NEAR': 'near',
    'APT': 'aptos',
    'ARB': 'arbitrum',
    'OP': 'optimism',
}


def rate_limit(calls_per_minute: int = 10):
    """Decorator to rate limit API calls."""
    min_interval = 60.0 / calls_per_minute
    last_called = [0.0]
    
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            left_to_wait = min_interval - elapsed
            if left_to_wait > 0:
                time.sleep(left_to_wait)
            ret = func(*args, **kwargs)
            last_called[0] = time.time()
            return ret
        return wrapper
    return decorator


class CoinGeckoClient:
    """Client for CoinGecko API (free tier)."""
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    def __init__(self):
        """Initialize CoinGecko client with caching."""
        self.cache = {}
        self.cache_ttl = 300  # 5 minutes
    
    def _resolve_symbol(self, symbol: str) -> str:
        """Convert symbol to CoinGecko ID."""
        return COINGECKO_ID_MAP.get(symbol.upper(), symbol.lower())
    
    @rate_limit(calls_per_minute=10)
    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make rate-limited request to CoinGecko API."""
        url = f"{self.BASE_URL}/{endpoint}"
        response = requests.get(url, params=params or {})
        response.raise_for_status()
        return response.json()
    
    def fetch_prices(self, symbols: List[str]) -> Dict:
        """
        Fetch current prices for multiple cryptocurrencies.
        
        Args:
            symbols: List of crypto symbols (e.g., ['BTC', 'ETH'])
        
        Returns:
            Dict mapping CoinGecko IDs to price data
        """
        # Check cache first
        cache_key = ','.join(sorted(symbols))
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return cached_data
        
        # Convert symbols to CoinGecko IDs
        ids = [self._resolve_symbol(s) for s in symbols]
        
        params = {
            'ids': ','.join(ids),
            'vs_currencies': 'usd',
            'include_24hr_change': 'true',
            'include_market_cap': 'true',
            'include_24hr_vol': 'true'
        }
        
        data = self._make_request('simple/price', params)
        
        # Cache result
        self.cache[cache_key] = (data, time.time())
        
        return data
    
    def fetch_historical(self, symbol: str, days: int = 30) -> List[Dict]:
        """
        Fetch historical price data.
        
        Args:
            symbol: Crypto symbol
            days: Number of days of history
        
        Returns:
            List of price points with timestamps
        """
        cg_id = self._resolve_symbol(symbol)
        
        params = {
            'vs_currency': 'usd',
            'days': days,
            'interval': 'daily'
        }
        
        data = self._make_request(f'coins/{cg_id}/market_chart', params)
        
        return [
            {'timestamp': p[0], 'price': p[1]}
            for p in data.get('prices', [])
        ]

    def fetch_avg_historical_price(self, symbol: str) -> Dict:
        """
        Fetch the mean daily closing price over the longest available period,
        trying 730 → 365 → 180 → 90 days in order.

        Returns:
            Dict with keys: avg_price (float), days_used (int), num_points (int)
            Raises RuntimeError if all periods fail.
        """
        for days in (730, 365, 180, 90):
            try:
                history = self.fetch_historical(symbol, days=days)
                if history:
                    prices = [p['price'] for p in history]
                    return {
                        'avg_price': sum(prices) / len(prices),
                        'days_used': days,
                        'num_points': len(prices),
                    }
            except Exception as exc:
                logger.debug("fetch_historical(%s, %d) failed: %s", symbol, days, exc)
        raise RuntimeError(f"Could not fetch historical prices for {symbol} at any lookback period")

    def fetch_moving_averages(self, symbol: str) -> Dict:
        """
        Fetch 7-day and 30-day simple moving averages for a symbol.

        Returns dict with keys: current_price, ma_7d, ma_30d
        """
        history = self.fetch_historical(symbol, days=30)
        if not history:
            return {}
        prices = [p['price'] for p in history]
        result = {'ma_30d': sum(prices) / len(prices) if prices else None}
        if len(prices) >= 7:
            result['ma_7d'] = sum(prices[-7:]) / 7
        else:
            result['ma_7d'] = None
        result['current_price'] = prices[-1] if prices else None
        return result


class BinanceClient:
    """Client for Binance API account access and optional trade execution."""
    
    BASE_URL = "https://api.binance.com"
    
    def __init__(self):
        """Initialize Binance client with API credentials from environment."""
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')
        
        if not self.api_key or not self.api_secret:
            raise ValueError(
                "Binance API credentials not found. Set environment variables:\n"
                "  export BINANCE_API_KEY='your_key'\n"
                "  export BINANCE_API_SECRET='your_secret'"
            )
    
    def _sign_request(self, params: Dict) -> str:
        """Generate HMAC SHA256 signature for Binance request."""
        query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
        signature = hmac.new(
            self.api_secret.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        return signature
    
    def _make_public_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make unauthenticated request to Binance API."""
        url = f"{self.BASE_URL}{endpoint}"
        response = requests.get(url, params=params or {})
        response.raise_for_status()
        return response.json()

    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make authenticated GET request to Binance API."""
        params = params or {}
        params['timestamp'] = int(time.time() * 1000)
        
        signature = self._sign_request(params)
        params['signature'] = signature
        
        url = f"{self.BASE_URL}{endpoint}"
        headers = {'X-MBX-APIKEY': self.api_key}
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        return response.json()

    def get_exchange_info(self, symbol: str = None) -> Dict:
        """Fetch Binance Spot exchange metadata and trading filters."""
        params = {'symbol': symbol.upper()} if symbol else None
        return self._make_public_request('/api/v3/exchangeInfo', params)

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        """Fetch metadata for a single Spot symbol, or None if unavailable."""
        try:
            data = self.get_exchange_info(symbol)
        except Exception as exc:
            logger.debug("Spot symbol info unavailable for %s: %s", symbol, exc)
            return None
        symbols = data.get('symbols', [])
        return symbols[0] if symbols else None

    def get_book_ticker(self, symbol: str) -> Dict:
        """Fetch best bid/ask for a Spot symbol."""
        return self._make_public_request('/api/v3/ticker/bookTicker', {'symbol': symbol.upper()})
    
    def get_account_balances(self) -> List[Dict]:
        """
        Fetch account balances from Binance.
        
        Returns:
            List of balances with non-zero amounts
        """
        data = self._make_request('/api/v3/account')
        
        return [
            {
                'asset': b['asset'],
                'amount': float(b['free']) + float(b['locked'])
            }
            for b in data.get('balances', [])
            if float(b['free']) + float(b['locked']) > 0
        ]
    
    def get_trade_history(self, symbol: str, limit: int = 1000) -> List[Dict]:
        """
        Fetch trade history for a trading pair.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            limit: Number of trades to fetch (max 1000)

        Returns:
            List of trade records
        """
        params = {'symbol': symbol, 'limit': limit}
        return self._make_request('/api/v3/myTrades', params)

    def get_convert_history(self, start_ms: int, end_ms: int, limit: int = 1000) -> List[Dict]:
        """
        Fetch Binance Convert trade history for a single 30-day window.

        Args:
            start_ms: Start timestamp in milliseconds
            end_ms:   End timestamp in milliseconds (max 30 days after start_ms)
            limit:    Max records to return (default 1000)

        Returns:
            List of convert trade records
        """
        params = {'startTime': start_ms, 'endTime': end_ms, 'limit': limit}
        data = self._make_request('/sapi/v1/convert/tradeFlow', params)
        return data.get('list', [])

    def get_avg_purchase_price(self, asset: str, lookback_days: int = 730) -> Optional[float]:
        """
        Compute weighted average buy price for an asset using Spot trade history
        and Binance Convert history, both quoted in stablecoins.

        Tries USDT, FDUSD, BUSD, and USDC quote pairs for Spot trades.
        Walks lookback_days of Convert history in 30-day chunks.
        Non-stablecoin pairs (BNB, BTC, ETH) are skipped.

        Args:
            asset:         Asset symbol (e.g., 'POL', 'BNB')
            lookback_days: How far back to search Convert history (default: 730 days)

        Returns:
            Weighted average purchase price in USD, or None if no buy trades found.
        """
        STABLE_QUOTES = ['USDT', 'FDUSD', 'BUSD', 'USDC']
        STABLE_SET = set(STABLE_QUOTES)
        # Legacy symbols for rebranded assets (try both current and old ticker)
        LEGACY_ALIASES: Dict[str, List[str]] = {
            'POL': ['MATIC'],
        }
        total_qty = 0.0
        total_cost = 0.0

        symbols_to_try = [asset.upper()] + LEGACY_ALIASES.get(asset.upper(), [])

        # --- Spot market trades ---
        for sym in symbols_to_try:
            for quote in STABLE_QUOTES:
                pair = f"{sym}{quote}"
                try:
                    trades = self.get_trade_history(pair)
                except Exception as exc:
                    logger.debug("Skipping Spot pair %s: %s", pair, exc)
                    continue

                for trade in trades:
                    if trade.get('isBuyer'):
                        qty = float(trade['qty'])
                        price = float(trade['price'])
                        total_qty += qty
                        total_cost += qty * price

        # --- Binance Convert history (paginated in 30-day windows) ---
        window_ms = 30 * 24 * 60 * 60 * 1000
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - lookback_days * 24 * 60 * 60 * 1000

        cursor = start_ms
        while cursor < end_ms:
            window_end = min(cursor + window_ms, end_ms)
            try:
                records = self.get_convert_history(cursor, window_end)
            except Exception as exc:
                logger.debug("Convert history fetch failed (%d-%d): %s", cursor, window_end, exc)
                cursor = window_end
                continue

            for record in records:
                if (record.get('orderStatus') == 'SUCCESS'
                        and record.get('toAsset', '').upper() in symbols_to_try
                        and record.get('fromAsset', '').upper() in STABLE_SET):
                    to_amount = float(record['toAmount'])
                    from_amount = float(record['fromAmount'])
                    if to_amount > 0:
                        price = from_amount / to_amount
                        total_qty += to_amount
                        total_cost += from_amount

            cursor = window_end

        if total_qty == 0:
            return None
        return total_cost / total_qty

    def diagnose_trade_history(self, asset: str, lookback_days: int = 730) -> Dict:
        """
        Diagnostic: report what trade data was found for an asset across all sources.

        Returns a dict with per-pair Spot counts, Convert window counts, errors,
        and a sample of raw records for inspection.
        """
        STABLE_QUOTES = ['USDT', 'FDUSD', 'BUSD', 'USDC']
        STABLE_SET = set(STABLE_QUOTES)
        LEGACY_ALIASES: Dict[str, List[str]] = {'POL': ['MATIC']}
        symbols_to_try = [asset.upper()] + LEGACY_ALIASES.get(asset.upper(), [])

        report: Dict = {
            'asset': asset.upper(),
            'symbols_tried': symbols_to_try,
            'spot': {},
            'convert': {'windows_fetched': 0, 'windows_failed': 0, 'total_records': 0,
                        'matching_records': 0, 'errors': [], 'sample': []},
        }

        # Spot
        for sym in symbols_to_try:
            for quote in STABLE_QUOTES:
                pair = f"{sym}{quote}"
                try:
                    trades = self.get_trade_history(pair)
                    buys = [t for t in trades if t.get('isBuyer')]
                    report['spot'][pair] = {'total': len(trades), 'buys': len(buys)}
                    if buys:
                        report['spot'][pair]['sample'] = buys[:2]
                except Exception as exc:
                    report['spot'][pair] = {'error': str(exc)}

        # Convert
        window_ms = 30 * 24 * 60 * 60 * 1000
        end_ms = int(time.time() * 1000)
        cursor = end_ms - lookback_days * 24 * 60 * 60 * 1000

        while cursor < end_ms:
            window_end = min(cursor + window_ms, end_ms)
            try:
                records = self.get_convert_history(cursor, window_end)
                report['convert']['windows_fetched'] += 1
                report['convert']['total_records'] += len(records)
                for rec in records:
                    if (rec.get('orderStatus') == 'SUCCESS'
                            and rec.get('toAsset', '').upper() in symbols_to_try
                            and rec.get('fromAsset', '').upper() in STABLE_SET):
                        report['convert']['matching_records'] += 1
                        if len(report['convert']['sample']) < 3:
                            report['convert']['sample'].append(rec)
            except Exception as exc:
                report['convert']['windows_failed'] += 1
                err = str(exc)
                if err not in report['convert']['errors']:
                    report['convert']['errors'].append(err)
            cursor = window_end

        return report

    def _make_post_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make authenticated POST request to Binance API."""
        params = params or {}
        params['timestamp'] = int(time.time() * 1000)

        signature = self._sign_request(params)
        params['signature'] = signature

        url = f"{self.BASE_URL}{endpoint}"
        headers = {'X-MBX-APIKEY': self.api_key}

        response = requests.post(url, headers=headers, params=params)
        response.raise_for_status()

        return response.json()

    def get_convert_quote(
        self,
        from_asset: str,
        to_asset: str,
        from_amount: float,
        valid_time: str = '10s',
    ) -> Dict:
        """
        Request a Binance Convert quote.

        The quote is temporary; execute with accept_convert_quote before it expires.
        """
        params = {
            'fromAsset': from_asset.upper(),
            'toAsset': to_asset.upper(),
            'fromAmount': str(from_amount),
            'validTime': valid_time,
        }
        return self._make_post_request('/sapi/v1/convert/getQuote', params)

    def accept_convert_quote(self, quote_id: str) -> Dict:
        """Accept a Binance Convert quote."""
        return self._make_post_request('/sapi/v1/convert/acceptQuote', {'quoteId': quote_id})

    def get_convert_order_status(
        self,
        order_id: str = None,
        quote_id: str = None,
    ) -> Dict:
        """Fetch Binance Convert order status by order_id or quote_id."""
        if not order_id and not quote_id:
            raise ValueError("order_id or quote_id is required")
        params = {}
        if order_id:
            params['orderId'] = order_id
        if quote_id:
            params['quoteId'] = quote_id
        return self._make_request('/sapi/v1/convert/orderStatus', params)

    def test_spot_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float = None,
        quote_order_qty: float = None,
    ) -> Dict:
        """Validate a Spot MARKET order without placing it."""
        params = {'symbol': symbol.upper(), 'side': side.upper(), 'type': 'MARKET'}
        if quantity is not None:
            params['quantity'] = str(quantity)
        if quote_order_qty is not None:
            params['quoteOrderQty'] = str(quote_order_qty)
        return self._make_post_request('/api/v3/order/test', params)

    def place_spot_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float = None,
        quote_order_qty: float = None,
    ) -> Dict:
        """Place a Spot MARKET order."""
        params = {'symbol': symbol.upper(), 'side': side.upper(), 'type': 'MARKET'}
        if quantity is not None:
            params['quantity'] = str(quantity)
        if quote_order_qty is not None:
            params['quoteOrderQty'] = str(quote_order_qty)
        return self._make_post_request('/api/v3/order', params)

    def get_funding_wallet_balance(self, asset: str) -> float:
        """
        Fetch free balance of an asset in the Binance Funding Wallet.

        Args:
            asset: Asset symbol (e.g., 'MYST')

        Returns:
            Free balance as float (0.0 if asset not found)
        """
        data = self._make_post_request('/sapi/v1/asset/get-funding-asset', {'asset': asset})
        for entry in data:
            if entry.get('asset') == asset:
                return float(entry.get('free', 0))
        return 0.0

    def get_all_funding_wallet_balances(self) -> List[Dict]:
        """
        Fetch all non-zero balances from the Binance Funding Wallet.

        Returns:
            List of {'asset': str, 'amount': float}
        """
        data = self._make_post_request('/sapi/v1/asset/get-funding-asset')
        return [
            {'asset': entry['asset'], 'amount': float(entry.get('free', 0)) + float(entry.get('locked', 0))}
            for entry in data
            if float(entry.get('free', 0)) + float(entry.get('locked', 0)) > 0
        ]

    def transfer_to_spot(self, asset: str, amount: float) -> Dict:
        """
        Transfer an asset from Funding Wallet to Spot (trading) account.

        Args:
            asset:  Asset symbol (e.g., 'MYST')
            amount: Amount to transfer

        Returns:
            Response dict containing 'tranId'
        """
        params = {'type': 'FUNDING_MAIN', 'asset': asset, 'amount': str(amount)}
        return self._make_post_request('/sapi/v1/asset/transfer', params)

    def get_convert_quote(self, from_asset: str, to_asset: str, from_amount: float) -> Dict:
        """
        Get a Binance Convert quote (Spot wallet).

        Args:
            from_asset:  Asset to sell (e.g. 'TRX')
            to_asset:    Asset to buy (e.g. 'BNB')
            from_amount: Amount of from_asset to convert

        Returns:
            Dict with quoteId, toAmount, ratio, etc.
        """
        params = {
            'fromAsset': from_asset.upper(),
            'toAsset': to_asset.upper(),
            'fromAmount': str(from_amount),
        }
        return self._make_post_request('/sapi/v1/convert/getQuote', params)

    def accept_convert_quote(self, quote_id: str) -> Dict:
        """
        Accept and execute a previously fetched Binance Convert quote.

        Args:
            quote_id: The quoteId from get_convert_quote

        Returns:
            Dict with orderId, status
        """
        return self._make_post_request('/sapi/v1/convert/acceptQuote', {'quoteId': quote_id})
