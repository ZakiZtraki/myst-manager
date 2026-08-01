"""Core portfolio manager that coordinates all portfolio operations."""

import json
import logging
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from .api_client import CoinGeckoClient, BinanceClient
from .analyzer import PortfolioAnalyzer
from .recommender import ActionRecommender


class PortfolioManager:
    """Main portfolio management interface."""
    
    def __init__(self, portfolio_file: str, use_binance: bool = False):
        """
        Initialize portfolio manager.
        
        Args:
            portfolio_file: Path to portfolio JSON config
            use_binance: If True, sync balances from Binance API
        """
        self.portfolio_file = Path(portfolio_file)
        self.portfolio_data = self._load_portfolio()
        
        # Initialize API clients
        self.coingecko = CoinGeckoClient()
        self.binance = BinanceClient() if use_binance else None
        
        # Initialize analyzer and recommender
        self.analyzer = PortfolioAnalyzer()
        self.recommender = ActionRecommender()
        
    def _load_portfolio(self) -> Dict:
        """Load portfolio configuration from JSON file."""
        if not self.portfolio_file.exists():
            raise FileNotFoundError(
                f"Portfolio file not found: {self.portfolio_file}\n"
                f"Create one using: cp examples/portfolio.example.json portfolio.json"
            )
        
        with open(self.portfolio_file) as f:
            data = json.load(f)
        return self._normalize_portfolio(data)

    def _normalize_portfolio(self, data: Dict) -> Dict:
        """Derive legacy flat fields from wallet-oriented portfolio configs."""
        wallets = data.get('wallets')
        if not wallets:
            return data

        had_holdings = 'holdings' in data
        had_myst_balance = 'myst_balance' in data
        data['holdings'] = self._aggregate_wallet_assets(wallets)
        if 'myst_balance' not in data:
            data['myst_balance'] = self._wallet_asset_amount(wallets, 'MYST')
        data['_generated_holdings_from_wallets'] = not had_holdings
        data['_generated_myst_balance_from_wallets'] = not had_myst_balance
        return data

    def _aggregate_wallet_assets(self, wallets: Dict) -> List[Dict]:
        """Flatten all wallet assets into analyzer-compatible holdings."""
        aggregated: Dict[str, Dict] = {}
        for asset in self._iter_wallet_assets(wallets):
            symbol = asset.get('symbol', '').upper()
            if not symbol:
                continue
            amount = float(asset.get('amount', 0) or 0)
            if amount <= 0:
                continue

            holding = aggregated.setdefault(
                symbol,
                {
                    'symbol': symbol,
                    'amount': 0.0,
                    'avg_purchase_price': asset.get('avg_purchase_price', 0),
                    'purchase_dates': list(asset.get('purchase_dates', [])),
                },
            )
            holding['amount'] += amount
            if not holding.get('avg_purchase_price') and asset.get('avg_purchase_price'):
                holding['avg_purchase_price'] = asset['avg_purchase_price']
            for date in asset.get('purchase_dates', []):
                if date not in holding['purchase_dates']:
                    holding['purchase_dates'].append(date)
        return list(aggregated.values())

    def _iter_wallet_assets(self, wallets: Dict):
        """Yield asset dictionaries from every configured wallet."""
        for exchange in wallets.values():
            if not isinstance(exchange, dict):
                continue
            for wallet in exchange.values():
                if isinstance(wallet, dict):
                    yield from wallet.get('assets', [])
                elif isinstance(wallet, list):
                    yield from wallet

    def _wallet_asset_amount(self, wallets: Dict, symbol: str) -> float:
        """Return the total configured amount for one symbol across wallets."""
        symbol = symbol.upper()
        return sum(
            float(asset.get('amount', 0) or 0)
            for asset in self._iter_wallet_assets(wallets)
            if asset.get('symbol', '').upper() == symbol
        )

    def _set_binance_wallet_assets(self, wallet_name: str, balances: List[Dict]) -> None:
        """Replace one Binance wallet asset list while preserving clear config shape."""
        wallets = self.portfolio_data.setdefault('wallets', {})
        binance = wallets.setdefault('binance', {})
        wallet = binance.setdefault(wallet_name, {})
        wallet['assets'] = [
            {
                'symbol': balance['asset'].upper(),
                'amount': balance['amount'],
                'avg_purchase_price': 0,
                'purchase_dates': [],
            }
            for balance in balances
            if balance.get('amount', 0) > 0
        ]
        self.portfolio_data['holdings'] = self._aggregate_wallet_assets(wallets)

    def _deduct_wallet_asset(self, symbol: str, amount: float) -> bool:
        """Deduct an amount from configured wallets, preferring trade-ready balances."""
        wallets = self.portfolio_data.get('wallets')
        if not wallets:
            return False

        remaining = float(amount)
        binance = wallets.get('binance', {})
        wallet_order = ['spot', 'funding', 'web3']
        ordered_wallets = [binance.get(name, {}) for name in wallet_order]
        ordered_wallets.extend(
            wallet for name, wallet in binance.items() if name not in wallet_order
        )
        available_total = sum(
            float(asset.get('amount', 0) or 0)
            for wallet in ordered_wallets
            for asset in wallet.get('assets', [])
            if asset.get('symbol', '').upper() == symbol.upper()
        )
        if available_total < remaining - 1e-9:
            return False

        for wallet in ordered_wallets:
            for asset in wallet.get('assets', []):
                if asset.get('symbol', '').upper() != symbol.upper():
                    continue
                available = float(asset.get('amount', 0) or 0)
                deduction = min(available, remaining)
                asset['amount'] = max(0.0, available - deduction)
                remaining -= deduction
                if remaining <= 1e-9:
                    self.portfolio_data['holdings'] = self._aggregate_wallet_assets(wallets)
                    if symbol.upper() == 'MYST':
                        self.portfolio_data['myst_balance'] = self._wallet_asset_amount(wallets, 'MYST')
                    return True
        return False
    
    def _save_portfolio(self):
        """Save portfolio data back to file."""
        data = dict(self.portfolio_data)
        generated_holdings = data.pop('_generated_holdings_from_wallets', False)
        generated_myst_balance = data.pop('_generated_myst_balance_from_wallets', False)
        if generated_holdings:
            data.pop('holdings', None)
        if generated_myst_balance:
            data.pop('myst_balance', None)
        with open(self.portfolio_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _get_holdings(self) -> List[Dict]:
        """Return flat list of all holdings, supporting both flat and wallets schema."""
        if 'holdings' in self.portfolio_data:
            return self.portfolio_data['holdings']
        holdings = []
        for exchange_data in self.portfolio_data.get('wallets', {}).values():
            for account_data in exchange_data.values():
                holdings.extend(account_data.get('assets', []))
        return holdings

    def _find_holding(self, symbol: str) -> Optional[Dict]:
        """Find a holding by symbol (case-insensitive)."""
        return next(
            (h for h in self._get_holdings() if h['symbol'].upper() == symbol.upper()),
            None,
        )

    def _add_to_holdings(self, asset_dict: Dict) -> None:
        """Add a new holding, writing to the spot wallet under wallets schema."""
        if 'holdings' in self.portfolio_data:
            self.portfolio_data['holdings'].append(asset_dict)
            return
        spot = (
            self.portfolio_data
            .setdefault('wallets', {})
            .setdefault('binance', {})
            .setdefault('spot', {})
        )
        spot.setdefault('assets', []).append(asset_dict)

    def _remove_from_holdings(self, holding: Dict) -> None:
        """Remove a holding object from whichever list it lives in."""
        if 'holdings' in self.portfolio_data:
            try:
                self.portfolio_data['holdings'].remove(holding)
            except ValueError:
                pass
            return
        for exchange_data in self.portfolio_data.get('wallets', {}).values():
            for account_data in exchange_data.values():
                try:
                    account_data.get('assets', []).remove(holding)
                    return
                except ValueError:
                    pass

    def sync_from_binance(self):
        """Sync holdings from Binance Spot and Funding wallets."""
        if not self.binance:
            raise ValueError("Binance client not initialized. Set use_binance=True")

        spot = self.binance.get_account_balances()
        try:
            funding = self.binance.get_all_funding_wallet_balances()
        except Exception:
            funding = []

        self._set_binance_wallet_assets('spot', spot)
        self._set_binance_wallet_assets('funding', funding)
        balances = spot + funding

        # Fill missing cost basis without changing the aggregated wallet amounts.
        for holding in self.portfolio_data['holdings']:
            if not holding.get('avg_purchase_price'):
                holding['avg_purchase_price'] = (
                    self.binance.get_avg_purchase_price(holding['symbol']) or 0
                )
        
        self._save_portfolio()
        return balances

    def refresh_cost_basis(self) -> Dict[str, Dict]:
        """
        Update avg_purchase_price for all holdings using the best available source:
          1. Binance Spot + Convert trade history (exact weighted average buy price)
          2. CoinGecko historical average price as fallback (2y → 1y → 6m → 3m)

        MYST holdings are skipped (earned as node rewards, no purchase price).
        Returns a dict mapping symbol -> {price, source, detail}.
        """
        if not self.binance:
            raise ValueError("Binance client not initialized. Set use_binance=True")

        updated = {}
        for holding in self.portfolio_data['holdings']:
            symbol = holding['symbol']
            if symbol.upper() == 'MYST':
                logger.debug("Skipping MYST — earned as node rewards")
                continue

            # --- Primary: Binance trade history ---
            avg_price = self.binance.get_avg_purchase_price(symbol)
            if avg_price is not None:
                holding['avg_purchase_price'] = avg_price
                updated[symbol] = {'price': avg_price, 'source': 'binance_trades'}
                logger.info("Updated %s from Binance trade history: %.6f", symbol, avg_price)
                continue

            # --- Fallback: CoinGecko historical average ---
            try:
                result = self.coingecko.fetch_avg_historical_price(symbol)
                avg_price = result['avg_price']
                holding['avg_purchase_price'] = avg_price
                updated[symbol] = {
                    'price': avg_price,
                    'source': 'coingecko_historical',
                    'days': result['days_used'],
                    'num_points': result['num_points'],
                }
                logger.info(
                    "Updated %s from CoinGecko %dd avg: %.6f",
                    symbol, result['days_used'], avg_price,
                )
            except Exception as exc:
                logger.warning("Could not fetch historical price for %s: %s", symbol, exc)

        self._save_portfolio()
        return updated

    def transfer_myst_to_spot(self, amount: float = None) -> Dict:
        """
        Transfer MYST from Binance Funding Wallet to Spot (trading) account.

        If amount is None, transfers all MYST above myst_keep_reserve.
        Skips if the transfer value is below min_swap_usd.

        Args:
            amount: Explicit MYST amount to transfer, or None for auto.

        Returns:
            Result dict with 'status', and on success: 'transferred', 'tran_id'.
        """
        if not self.binance:
            raise ValueError("Binance client not initialized. Set use_binance=True")

        swap_config = self.portfolio_data.get('swap_config', {})
        keep_reserve = float(swap_config.get('myst_keep_reserve', 0))
        min_swap_usd = float(swap_config.get('min_swap_usd', 50))

        funding_balance = self.binance.get_funding_wallet_balance('MYST')

        if amount is None:
            transfer_amount = max(0.0, funding_balance - keep_reserve)
        else:
            transfer_amount = float(amount)

        if transfer_amount <= 0:
            return {
                'status': 'skipped',
                'reason': 'No MYST above reserve',
                'funding_balance': funding_balance,
            }

        try:
            prices = self.coingecko.fetch_prices(['MYST'])
            myst_price = prices.get('mysterium', {}).get('usd', 0)
        except Exception:
            myst_price = 0

        if myst_price > 0 and transfer_amount * myst_price < min_swap_usd:
            return {
                'status': 'skipped',
                'reason': (
                    f"Transfer value ${transfer_amount * myst_price:.2f} "
                    f"below min_swap_usd ${min_swap_usd}"
                ),
                'funding_balance': funding_balance,
            }

        result = self.binance.transfer_to_spot('MYST', transfer_amount)
        return {
            'status': 'transferred',
            'transferred': transfer_amount,
            'funding_balance': funding_balance,
            'kept_reserve': keep_reserve,
            'tran_id': result.get('tranId'),
        }

    def transfer_asset_to_spot(
        self,
        asset: str,
        amount: float,
        keep_reserve: float = 0,
    ) -> Dict:
        """
        Transfer any asset from Binance Funding Wallet to Spot account.

        Args:
            asset: Asset symbol to transfer, e.g. POL or TRX.
            amount: Amount to transfer. Use -1 to transfer all above keep_reserve.
            keep_reserve: Funding wallet amount to leave untouched when amount=-1.

        Returns:
            Result dict with status and transfer details.
        """
        if not self.binance:
            raise ValueError("Binance client not initialized. Set use_binance=True")

        asset = asset.upper()
        funding_balance = self.binance.get_funding_wallet_balance(asset)

        if amount < 0:
            transfer_amount = max(0.0, funding_balance - float(keep_reserve))
        else:
            transfer_amount = float(amount)

        if transfer_amount <= 0:
            return {
                'status': 'skipped',
                'reason': f'No {asset} above reserve',
                'asset': asset,
                'funding_balance': funding_balance,
                'kept_reserve': keep_reserve,
            }

        if transfer_amount > funding_balance + 1e-9:
            raise ValueError(
                f'Insufficient {asset} in Funding wallet: '
                f'have {funding_balance}, need {transfer_amount}'
            )

        result = self.binance.transfer_to_spot(asset, transfer_amount)
        return {
            'status': 'transferred',
            'asset': asset,
            'transferred': transfer_amount,
            'funding_balance': funding_balance,
            'kept_reserve': keep_reserve,
            'tran_id': result.get('tranId'),
        }

    def preview_binance_swap(
        self,
        from_symbol: str,
        to_symbol: str,
        from_amount: Optional[float] = None,
        amount_usd: Optional[float] = None,
        prefer_convert: bool = True,
    ) -> Dict:
        """
        Build a Binance swap preview without placing an order.

        Prefer Binance Convert when a quote is available. Falls back to Spot MARKET
        route estimation using direct pairs or USDT as an intermediary.
        """
        if not self.binance:
            raise ValueError("Binance client not initialized. Set use_binance=True")

        from_symbol = from_symbol.upper()
        to_symbol = to_symbol.upper()
        if from_symbol == to_symbol:
            raise ValueError("from_symbol and to_symbol must differ")

        resolved_amount = self._resolve_swap_from_amount(
            from_symbol, from_amount=from_amount, amount_usd=amount_usd
        )

        if prefer_convert:
            try:
                quote = self.binance.get_convert_quote(from_symbol, to_symbol, resolved_amount)
                ratio = float(quote.get('ratio', 0) or 0)
                inverse_ratio = float(quote.get('inverseRatio', 0) or 0)
                to_amount = float(quote.get('toAmount', 0) or 0)
                return {
                    'status': 'preview',
                    'mode': 'convert',
                    'from_asset': from_symbol,
                    'to_asset': to_symbol,
                    'from_amount': resolved_amount,
                    'estimated_to_amount': to_amount,
                    'route': f'{from_symbol} → {to_symbol}',
                    'quote_id': quote.get('quoteId'),
                    'ratio': ratio,
                    'inverse_ratio': inverse_ratio,
                    'raw_quote': quote,
                    'requires_confirmation': True,
                }
            except Exception as exc:
                logger.info(
                    "Binance Convert quote unavailable for %s -> %s: %s",
                    from_symbol, to_symbol, exc,
                )

        return self._preview_spot_swap(from_symbol, to_symbol, resolved_amount)

    def execute_binance_swap(
        self,
        from_symbol: str,
        to_symbol: str,
        from_amount: Optional[float] = None,
        amount_usd: Optional[float] = None,
        confirm: bool = False,
        prefer_convert: bool = True,
        quote_id: Optional[str] = None,
    ) -> Dict:
        """
        Execute a Binance swap and record actual filled amounts in the portfolio.

        Live trading is blocked unless confirm=True. Without confirmation this returns
        the same preview payload as preview_binance_swap plus a safety status.
        """
        if not self.binance:
            raise ValueError("Binance client not initialized. Set use_binance=True")

        preview = self.preview_binance_swap(
            from_symbol,
            to_symbol,
            from_amount=from_amount,
            amount_usd=amount_usd,
            prefer_convert=prefer_convert,
        )
        if quote_id:
            preview['quote_id'] = quote_id

        if not confirm:
            preview['status'] = 'confirmation_required'
            preview['message'] = 'Live Binance swap not executed. Re-run with confirm=True.'
            return preview

        if preview['mode'] == 'convert':
            result = self.binance.accept_convert_quote(preview['quote_id'])
            order_status = None
            order_id = result.get('orderId')
            try:
                order_status = self.binance.get_convert_order_status(
                    order_id=order_id,
                    quote_id=preview['quote_id'],
                )
            except Exception as exc:
                logger.warning("Could not fetch Convert order status: %s", exc)

            actual_from = float(preview['from_amount'])
            actual_to = self._extract_convert_to_amount(order_status) or float(
                preview.get('estimated_to_amount') or 0
            )
            if actual_to <= 0:
                raise RuntimeError("Convert order completed without a usable toAmount")

            self.record_swap(preview['from_asset'], actual_from, preview['to_asset'], actual_to)
            return {
                'status': 'executed',
                'mode': 'convert',
                'from_asset': preview['from_asset'],
                'to_asset': preview['to_asset'],
                'from_amount': actual_from,
                'to_amount': actual_to,
                'quote_id': preview['quote_id'],
                'order_id': order_id,
                'raw_result': result,
                'order_status': order_status,
            }

        result = self._execute_spot_swap(preview)
        self.record_swap(
            preview['from_asset'],
            result['from_amount'],
            preview['to_asset'],
            result['to_amount'],
        )
        result['status'] = 'executed'
        return result

    def _resolve_swap_from_amount(
        self,
        from_symbol: str,
        from_amount: Optional[float] = None,
        amount_usd: Optional[float] = None,
    ) -> float:
        """Resolve swap source amount from explicit amount or USD value."""
        if from_amount is not None:
            amount = float(from_amount)
        elif amount_usd is not None:
            prices = self.coingecko.fetch_prices([from_symbol])
            cg_id = self.coingecko._resolve_symbol(from_symbol)
            price = prices.get(cg_id, {}).get('usd', 0)
            if price <= 0:
                raise ValueError(f"Could not resolve USD price for {from_symbol}")
            amount = float(amount_usd) / price
        else:
            raise ValueError("from_amount or amount_usd is required")

        if amount <= 0:
            raise ValueError("Swap amount must be positive")

        min_swap_usd = float(self.portfolio_data.get('swap_config', {}).get('min_swap_usd', 0))
        if min_swap_usd:
            try:
                prices = self.coingecko.fetch_prices([from_symbol])
                cg_id = self.coingecko._resolve_symbol(from_symbol)
                price = prices.get(cg_id, {}).get('usd', 0)
                if price and amount * price < min_swap_usd:
                    raise ValueError(
                        f"Swap value ${amount * price:.2f} below min_swap_usd ${min_swap_usd}"
                    )
            except ValueError:
                raise
            except Exception as exc:
                logger.debug("Could not enforce min_swap_usd for %s: %s", from_symbol, exc)

        return amount

    def _preview_spot_swap(self, from_symbol: str, to_symbol: str, from_amount: float) -> Dict:
        """Estimate a Spot route using direct pair or USDT intermediary."""
        direct = self._spot_leg_preview(from_symbol, to_symbol, from_amount)
        if direct:
            return {
                'status': 'preview',
                'mode': 'spot',
                'from_asset': from_symbol,
                'to_asset': to_symbol,
                'from_amount': from_amount,
                'estimated_to_amount': direct['estimated_to_amount'],
                'route': direct['route'],
                'legs': [direct],
                'requires_confirmation': True,
            }

        if from_symbol != 'USDT' and to_symbol != 'USDT':
            first = self._spot_leg_preview(from_symbol, 'USDT', from_amount)
            if first:
                second = self._spot_leg_preview('USDT', to_symbol, first['estimated_to_amount'])
                if second:
                    return {
                        'status': 'preview',
                        'mode': 'spot',
                        'from_asset': from_symbol,
                        'to_asset': to_symbol,
                        'from_amount': from_amount,
                        'estimated_to_amount': second['estimated_to_amount'],
                        'route': f'{from_symbol} → USDT → {to_symbol}',
                        'legs': [first, second],
                        'requires_confirmation': True,
                    }

        raise ValueError(f"No Binance Convert or Spot route found for {from_symbol} -> {to_symbol}")

    def _spot_leg_preview(
        self,
        from_symbol: str,
        to_symbol: str,
        from_amount: float,
    ) -> Optional[Dict]:
        """Preview one Spot leg. Returns None when no usable symbol exists."""
        sell_symbol = f'{from_symbol}{to_symbol}'
        if self.binance.get_symbol_info(sell_symbol):
            ticker = self.binance.get_book_ticker(sell_symbol)
            bid = float(ticker['bidPrice'])
            ask = float(ticker['askPrice'])
            spread_bps = ((ask - bid) / ask * 10000) if ask else 0
            return {
                'symbol': sell_symbol,
                'side': 'SELL',
                'quantity': from_amount,
                'from_asset': from_symbol,
                'to_asset': to_symbol,
                'estimated_to_amount': from_amount * bid,
                'route': f'{from_symbol} → {to_symbol}',
                'bid': bid,
                'ask': ask,
                'spread_bps': spread_bps,
            }

        buy_symbol = f'{to_symbol}{from_symbol}'
        if self.binance.get_symbol_info(buy_symbol):
            ticker = self.binance.get_book_ticker(buy_symbol)
            bid = float(ticker['bidPrice'])
            ask = float(ticker['askPrice'])
            spread_bps = ((ask - bid) / ask * 10000) if ask else 0
            return {
                'symbol': buy_symbol,
                'side': 'BUY',
                'quote_order_qty': from_amount,
                'from_asset': from_symbol,
                'to_asset': to_symbol,
                'estimated_to_amount': from_amount / ask if ask else 0,
                'route': f'{from_symbol} → {to_symbol}',
                'bid': bid,
                'ask': ask,
                'spread_bps': spread_bps,
            }

        return None

    def _execute_spot_swap(self, preview: Dict) -> Dict:
        """Execute the Spot legs from a preview and return actual amounts."""
        current_amount = float(preview['from_amount'])
        orders = []
        for leg in preview['legs']:
            if leg['side'] == 'SELL':
                current_amount = self._format_spot_quantity(leg['symbol'], current_amount)
                self.binance.test_spot_market_order(
                    leg['symbol'], 'SELL', quantity=current_amount
                )
                order = self.binance.place_spot_market_order(
                    leg['symbol'], 'SELL', quantity=current_amount
                )
                current_amount = float(order.get('cummulativeQuoteQty', 0) or 0)
            else:
                current_amount = self._format_spot_quote_order_qty(leg['symbol'], current_amount)
                self.binance.test_spot_market_order(
                    leg['symbol'], 'BUY', quote_order_qty=current_amount
                )
                order = self.binance.place_spot_market_order(
                    leg['symbol'], 'BUY', quote_order_qty=current_amount
                )
                current_amount = float(order.get('executedQty', 0) or 0)
            if current_amount <= 0:
                raise RuntimeError(f"Spot order on {leg['symbol']} returned zero fill")
            orders.append(order)

        return {
            'mode': 'spot',
            'from_asset': preview['from_asset'],
            'to_asset': preview['to_asset'],
            'from_amount': float(preview['from_amount']),
            'to_amount': current_amount,
            'route': preview['route'],
            'orders': orders,
        }

    def _format_spot_quantity(self, symbol: str, quantity: float) -> float:
        """Round Spot base quantity down to the symbol LOT_SIZE step."""
        info = self.binance.get_symbol_info(symbol)
        if not info:
            return quantity
        lot_filter = self._symbol_filter(info, 'LOT_SIZE')
        if not lot_filter:
            return quantity
        step = Decimal(lot_filter.get('stepSize', '0'))
        min_qty = Decimal(lot_filter.get('minQty', '0'))
        value = Decimal(str(quantity))
        if step > 0:
            value = (value / step).to_integral_value(rounding=ROUND_DOWN) * step
        if value < min_qty:
            raise ValueError(f"{symbol} quantity {value} below minQty {min_qty}")
        return float(value)

    def _format_spot_quote_order_qty(self, symbol: str, quote_qty: float) -> float:
        """Round quoteOrderQty to the symbol quote precision."""
        info = self.binance.get_symbol_info(symbol)
        if not info:
            return quote_qty
        precision = int(info.get('quoteAssetPrecision', info.get('quotePrecision', 8)))
        quant = Decimal('1').scaleb(-precision)
        value = Decimal(str(quote_qty)).quantize(quant, rounding=ROUND_DOWN)
        notional_filter = self._symbol_filter(info, 'NOTIONAL')
        if notional_filter:
            min_notional = Decimal(notional_filter.get('minNotional', '0'))
            if value < min_notional:
                raise ValueError(f"{symbol} quoteOrderQty {value} below minNotional {min_notional}")
        return float(value)

    def _symbol_filter(self, symbol_info: Dict, filter_type: str) -> Optional[Dict]:
        """Return a Binance symbol filter by type."""
        return next(
            (f for f in symbol_info.get('filters', []) if f.get('filterType') == filter_type),
            None,
        )

    def _extract_convert_to_amount(self, order_status: Optional[Dict]) -> Optional[float]:
        """Extract received asset amount from a Convert order status payload."""
        if not order_status:
            return None
        for key in ('toAmount', 'amount'):
            value = order_status.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
        return None

    def get_status(self, format: str = 'dict') -> Dict:
        """
        Get current portfolio status.
        
        Args:
            format: Output format ('dict', 'json', 'text')
        
        Returns:
            Portfolio status with current values and P&L
        """
        holdings = self._get_holdings()
        symbols = [h['symbol'] for h in holdings]
        prices = self.coingecko.fetch_prices(symbols)
        analysis = self.analyzer.analyze(holdings, prices)
        
        if format == 'json':
            return json.dumps(analysis, indent=2)
        elif format == 'text':
            return self._format_status_text(analysis)
        
        return analysis
    
    def get_recommendations(self) -> List[Dict]:
        """
        Get actionable recommendations based on current portfolio state.

        Automatically activates swap mode when portfolio.json contains 'swap_routes'.
        Fetches MYST price moving averages for timing signals when swap mode is on.
        """
        analysis = self.get_status(format='dict')
        risks = self.analyzer.assess_risk(
            analysis,
            self.portfolio_data.get('target_allocation', {})
        )

        swap_routes = self.portfolio_data.get('swap_routes')
        swap_config = dict(self.portfolio_data.get('swap_config', {}))
        myst_balance = self.portfolio_data.get(
            'myst_balance',
            self.portfolio_data.get('cash_reserves', 0)
        )

        if swap_routes and myst_balance > 0:
            try:
                ma_data = self.coingecko.fetch_moving_averages('MYST')
                swap_config.update({
                    'myst_current_price': ma_data.get('current_price') or 0,
                    'myst_ma_7d': ma_data.get('ma_7d'),
                    'myst_ma_30d': ma_data.get('ma_30d'),
                })
            except Exception as exc:
                logger.warning('Could not fetch MYST moving averages: %s', exc)

        return self.recommender.generate(
            analysis,
            risks,
            self.portfolio_data.get('target_allocation', {}),
            cash_reserves=self.portfolio_data.get('cash_reserves', 0),
            myst_balance=myst_balance,
            swap_routes=swap_routes,
            swap_config=swap_config,
        )
    
    def update_portfolio_config(
        self,
        target_allocation: Optional[Dict] = None,
        myst_balance: Optional[float] = None,
        swap_routes: Optional[Dict] = None,
        swap_config: Optional[Dict] = None,
    ) -> None:
        """Update portfolio config fields and persist to disk."""
        if target_allocation is not None:
            total = sum(target_allocation.values())
            if not (0.95 <= total <= 1.05):
                raise ValueError(
                    f'target_allocation must sum to 1.0, got {total:.2f}'
                )
            self.portfolio_data['target_allocation'] = target_allocation
        if myst_balance is not None:
            self.portfolio_data['myst_balance'] = myst_balance
        if swap_routes is not None:
            self.portfolio_data['swap_routes'] = swap_routes
        if swap_config is not None:
            self.portfolio_data['swap_config'] = swap_config
        self._save_portfolio()

    def record_swap(
        self,
        from_symbol: str,
        from_amount: float,
        to_symbol: str,
        to_amount: float,
    ) -> None:
        """
        Record a completed swap, updating holdings and myst_balance accordingly.

        MYST swaps deduct from myst_balance; all other assets deduct from holdings.
        The received asset is added to (or created in) holdings.
        """
        if from_symbol.upper() == 'MYST':
            current = self.portfolio_data.get('myst_balance', 0)
            if from_amount > current + 1e-9:
                raise ValueError(
                    f'Insufficient MYST balance: have {current}, need {from_amount}'
                )
            if not self._deduct_wallet_asset(from_symbol, from_amount):
                self.portfolio_data['myst_balance'] = max(0.0, current - from_amount)
        else:
            if self._deduct_wallet_asset(from_symbol, from_amount):
                self._add_wallet_asset(to_symbol, to_amount)
                self._save_portfolio()
                return

            holding = self._find_holding(from_symbol)
            if not holding:
                raise ValueError(f'{from_symbol} not found in holdings')
            if from_amount > holding['amount'] + 1e-9:
                raise ValueError(
                    f'Insufficient {from_symbol}: have {holding["amount"]}, need {from_amount}'
                )
            holding['amount'] = max(0.0, holding['amount'] - from_amount)
            if holding['amount'] < 1e-9:
                self._remove_from_holdings(holding)

        to_holding = self._find_holding(to_symbol)
        if to_holding:
            to_holding['amount'] += to_amount
        else:
            self._add_to_holdings({
                'symbol': to_symbol.upper(),
                'amount': to_amount,
                'avg_purchase_price': 0,
                'purchase_dates': [datetime.now().strftime('%Y-%m-%d')],
            })
        self._add_wallet_asset(to_symbol, to_amount)
        self._save_portfolio()

    def _add_wallet_asset(self, symbol: str, amount: float, wallet_name: str = 'spot') -> None:
        """Add a received asset to the configured Binance wallet assets."""
        wallets = self.portfolio_data.get('wallets')
        if not wallets:
            return

        binance = wallets.setdefault('binance', {})
        wallet = binance.setdefault(wallet_name, {})
        assets = wallet.setdefault('assets', [])
        symbol = symbol.upper()
        asset = next((a for a in assets if a.get('symbol', '').upper() == symbol), None)
        if asset:
            asset['amount'] = float(asset.get('amount', 0) or 0) + amount
        else:
            assets.append({
                'symbol': symbol,
                'amount': amount,
                'avg_purchase_price': 0,
                'purchase_dates': [datetime.now().strftime('%Y-%m-%d')],
            })
        self.portfolio_data['holdings'] = self._aggregate_wallet_assets(wallets)
        if symbol == 'MYST':
            self.portfolio_data['myst_balance'] = self._wallet_asset_amount(wallets, 'MYST')

    def get_daily_report(self) -> str:
        """Generate formatted daily portfolio report."""
        status = self.get_status(format='dict')
        recommendations = self.get_recommendations()
        
        report = f"""
╔════════════════════════════════════════════╗
║     CRYPTO PORTFOLIO REPORT                ║
║     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC               ║
╚════════════════════════════════════════════╝

💰 PORTFOLIO VALUE
   Current:    ${status['total_value']:,.2f}
   Cost Basis: ${status['total_cost']:,.2f}
   P&L:        ${status['total_pnl']:+,.2f} ({status['total_pnl_pct']:+.2f}%)

📊 POSITIONS ({len(status['positions'])})
"""
        
        for pos in status['positions']:
            report += f"""
┌──────────────────────────────────────────┐
│ {pos['symbol']:<40} │
│ Amount:     {pos['amount']:<25} │
│ Value:      ${pos['current_value']:,.2f} ({status['allocation'][pos['symbol']]:.1f}%)
│ P&L:        ${pos['pnl']:+,.2f} ({pos['pnl_pct']:+.2f}%)
│ 24h Change: {pos['daily_change']:+.2f}%
└──────────────────────────────────────────┘
"""
        
        if recommendations:
            report += f"\n💡 RECOMMENDATIONS ({len(recommendations)})\n"
            for i, rec in enumerate(recommendations[:5], 1):
                priority_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
                emoji = priority_emoji.get(rec['priority'], '⚪')
                if rec['action'] == 'SWAP' and 'from_asset' in rec:
                    summary = (
                        f"{rec.get('route', rec['from_asset'] + ' → ' + rec['asset'])}"
                        f" (~${rec.get('amount_usd', 0):,.0f})"
                    )
                else:
                    summary = f"{rec['action']} {rec['asset']}: ${rec.get('amount_usd', 0):,.2f}"
                report += f"   {i}. [{emoji} {rec['priority'].upper()}] {summary}\n"
                report += f"      {rec['rationale']}\n"
        
        return report
    
    def _format_status_text(self, analysis: Dict) -> str:
        """Format analysis dictionary as readable text."""
        text = f"Portfolio Value: ${analysis['total_value']:,.2f}\n"
        text += f"Total P&L: ${analysis['total_pnl']:+,.2f} ({analysis['total_pnl_pct']:+.2f}%)\n\n"
        
        for pos in analysis['positions']:
            text += f"{pos['symbol']}: ${pos['current_value']:,.2f} "
            text += f"({pos['pnl_pct']:+.2f}%)\n"
        
        return text
    
    def export_to_csv(self, output_file: str):
        """Export portfolio history to CSV format."""
        import csv
        from datetime import datetime
        
        status = self.get_status(format='dict')
        
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'timestamp', 'symbol', 'amount', 'price', 'value', 
                'cost_basis', 'pnl', 'pnl_pct'
            ])
            writer.writeheader()
            
            timestamp = datetime.now().isoformat()
            for pos in status['positions']:
                writer.writerow({
                    'timestamp': timestamp,
                    'symbol': pos['symbol'],
                    'amount': pos['amount'],
                    'price': pos['current_price'],
                    'value': pos['current_value'],
                    'cost_basis': pos['cost_basis'],
                    'pnl': pos['pnl'],
                    'pnl_pct': pos['pnl_pct']
                })
