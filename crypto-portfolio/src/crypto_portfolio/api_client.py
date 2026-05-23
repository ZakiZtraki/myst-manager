"""API clients for cryptocurrency price data and exchange integration."""

import os
import time
import hmac
import hashlib
import requests
from typing import Dict, List
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
    'POL': 'matic-network',  # POL is the rebranded MATIC on Polygon
    'MYST': 'mysterium',     # Mysterium Network node token
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
    """Client for Binance API (read-only account access)."""
    
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
    
    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make authenticated request to Binance API."""
        params = params or {}
        params['timestamp'] = int(time.time() * 1000)
        
        signature = self._sign_request(params)
        params['signature'] = signature
        
        url = f"{self.BASE_URL}{endpoint}"
        headers = {'X-MBX-APIKEY': self.api_key}
        
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        
        return response.json()
    
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
    
    def get_trade_history(self, symbol: str, limit: int = 100) -> List[Dict]:
        """
        Fetch trade history for a symbol.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT')
            limit: Number of trades to fetch

        Returns:
            List of trade records
        """
        params = {'symbol': symbol, 'limit': limit}
        return self._make_request('/api/v3/myTrades', params)

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
