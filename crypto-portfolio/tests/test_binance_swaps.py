"""Tests for Binance swap preview/execution orchestration."""

import json

from crypto_portfolio.manager import PortfolioManager


class FakeCoinGecko:
    def _resolve_symbol(self, symbol):
        return {'MYST': 'mysterium', 'BNB': 'binancecoin'}.get(symbol.upper(), symbol.lower())

    def fetch_prices(self, symbols):
        return {
            'mysterium': {'usd': 0.20},
            'binancecoin': {'usd': 700.0},
        }


class FakeBinanceConvert:
    def __init__(self):
        self.accepted = False

    def get_convert_quote(self, from_asset, to_asset, from_amount):
        return {
            'quoteId': 'quote-1',
            'fromAsset': from_asset,
            'toAsset': to_asset,
            'fromAmount': str(from_amount),
            'toAmount': '0.025',
            'ratio': '0.00025',
            'inverseRatio': '4000',
        }

    def accept_convert_quote(self, quote_id):
        self.accepted = True
        return {'orderId': 'order-1', 'orderStatus': 'SUCCESS'}

    def get_convert_order_status(self, order_id=None, quote_id=None):
        return {'orderId': order_id, 'orderStatus': 'SUCCESS', 'toAmount': '0.0245'}


def write_portfolio(path):
    data = {
        'holdings': [
            {'symbol': 'MYST', 'amount': 500, 'avg_purchase_price': 0, 'purchase_dates': []},
            {'symbol': 'BNB', 'amount': 1, 'avg_purchase_price': 500, 'purchase_dates': []},
        ],
        'myst_balance': 100,
        'target_allocation': {'MYST': 0.5, 'BNB': 0.5},
        'swap_config': {'min_swap_usd': 0},
    }
    path.write_text(json.dumps(data))
    return data


def make_manager(path):
    pm = PortfolioManager(str(path), use_binance=False)
    pm.binance = FakeBinanceConvert()
    pm.coingecko = FakeCoinGecko()
    return pm


def test_execute_swap_without_confirmation_does_not_trade_or_mutate(tmp_path):
    portfolio_path = tmp_path / 'portfolio.json'
    original = write_portfolio(portfolio_path)
    pm = make_manager(portfolio_path)

    result = pm.execute_binance_swap('MYST', 'BNB', from_amount=10, confirm=False)

    assert result['status'] == 'confirmation_required'
    assert result['mode'] == 'convert'
    assert result['quote_id'] == 'quote-1'
    assert pm.binance.accepted is False
    assert json.loads(portfolio_path.read_text()) == original


def test_confirmed_convert_swap_records_actual_fill(tmp_path):
    portfolio_path = tmp_path / 'portfolio.json'
    write_portfolio(portfolio_path)
    pm = make_manager(portfolio_path)

    result = pm.execute_binance_swap('MYST', 'BNB', from_amount=10, confirm=True)
    updated = json.loads(portfolio_path.read_text())
    bnb = next(h for h in updated['holdings'] if h['symbol'] == 'BNB')

    assert result['status'] == 'executed'
    assert result['to_amount'] == 0.0245
    assert pm.binance.accepted is True
    assert updated['myst_balance'] == 90
    assert bnb['amount'] == 1.0245


def test_wallet_layout_aggregates_holdings_and_myst_balance(tmp_path):
    portfolio_path = tmp_path / 'portfolio.json'
    portfolio_path.write_text(json.dumps({
        'wallets': {
            'binance': {
                'web3': {
                    'assets': [
                        {'symbol': 'MYST', 'amount': 25, 'avg_purchase_price': 0}
                    ]
                },
                'funding': {
                    'assets': [
                        {'symbol': 'BNB', 'amount': 0.25, 'avg_purchase_price': 500}
                    ]
                },
                'spot': {
                    'assets': [
                        {'symbol': 'BNB', 'amount': 1.0, 'avg_purchase_price': 500}
                    ]
                },
            }
        },
        'target_allocation': {'MYST': 0.5, 'BNB': 0.5},
        'swap_config': {'min_swap_usd': 0},
    }))

    pm = make_manager(portfolio_path)
    holdings = {h['symbol']: h for h in pm.portfolio_data['holdings']}

    assert holdings['MYST']['amount'] == 25
    assert holdings['BNB']['amount'] == 1.25
    assert pm.portfolio_data['myst_balance'] == 25


def test_wallet_layout_swap_saves_wallet_first_shape(tmp_path):
    portfolio_path = tmp_path / 'portfolio.json'
    portfolio_path.write_text(json.dumps({
        'wallets': {
            'binance': {
                'web3': {'assets': []},
                'funding': {'assets': []},
                'spot': {
                    'assets': [
                        {'symbol': 'MYST', 'amount': 100, 'avg_purchase_price': 0},
                        {'symbol': 'BNB', 'amount': 1, 'avg_purchase_price': 500},
                    ]
                },
            }
        },
        'target_allocation': {'MYST': 0.5, 'BNB': 0.5},
        'swap_config': {'min_swap_usd': 0},
    }))
    pm = make_manager(portfolio_path)

    result = pm.execute_binance_swap('MYST', 'BNB', from_amount=10, confirm=True)
    updated = json.loads(portfolio_path.read_text())
    spot_assets = {
        asset['symbol']: asset
        for asset in updated['wallets']['binance']['spot']['assets']
    }

    assert result['status'] == 'executed'
    assert 'holdings' not in updated
    assert 'myst_balance' not in updated
    assert spot_assets['MYST']['amount'] == 90
    assert spot_assets['BNB']['amount'] == 1.0245
