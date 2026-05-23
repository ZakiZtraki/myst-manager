"""
Integration test: universe → metrics → score → output, end-to-end with mocked HTTP.

Covers:
  1. Non-Binance source (MYST) is noted in metadata and does not fail.
  2. Low-liquidity candidate is filtered out.
  3. CSV + JSON are written and contain expected columns.
  4. Composite scores are produced and results are ranked.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from typing import List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from crypto_portfolio.screener.config import ScreenerConfig
from crypto_portfolio.screener.screener import run_screener
from conftest import make_klines


# ------------------------------------------------------------------
# Fixture data builders
# ------------------------------------------------------------------

def _make_prices(n: int = 250, mu: float = 0.001, sigma: float = 0.02, seed: int = 0) -> List[float]:
    rng = np.random.default_rng(seed)
    return list(100.0 * np.cumprod(1 + rng.normal(mu, sigma, n)))


def _binance_klines(prices: List[float]) -> List[List]:
    return make_klines(prices)


def _ticker(symbol: str, quote_vol: float) -> dict:
    return {'symbol': symbol, 'quoteVolume': str(quote_vol), 'lastPrice': '100.0'}


def _depth(best_bid: float = 99.5, best_ask: float = 100.5) -> dict:
    bids = [[str(best_bid - i * 0.1), '10.0'] for i in range(10)]
    asks = [[str(best_ask + i * 0.1), '10.0'] for i in range(10)]
    return {'bids': bids, 'asks': asks}


# ------------------------------------------------------------------
# Synthetic universe (5 candidates)
# ------------------------------------------------------------------

CANDIDATE_SYMBOLS = ['SOLUSDT', 'AVAXUSDT', 'LINKUSDT', 'DOTUSDT', 'LOWLIQUSDT']

EXCHANGE_INFO = {
    'symbols': [
        {'symbol': sym, 'quoteAsset': 'USDT', 'status': 'TRADING'}
        for sym in CANDIDATE_SYMBOLS
    ] + [
        # Source asset NOT listed
        {'symbol': 'MYSTUSDT', 'quoteAsset': 'USDT', 'status': 'BREAK'},
    ]
}

COINGECKO_MARKETS = [
    {'id': 'solana',    'symbol': 'sol',    'name': 'Solana',    'market_cap_rank': 5,
     'market_cap': 50_000_000_000, 'fully_diluted_valuation': 55_000_000_000,
     'total_volume': 2_000_000_000, 'circulating_supply': 400_000_000,
     'total_supply': 500_000_000, 'current_price': 100.0},
    {'id': 'avalanche-2', 'symbol': 'avax', 'name': 'Avalanche', 'market_cap_rank': 10,
     'market_cap': 15_000_000_000, 'fully_diluted_valuation': 18_000_000_000,
     'total_volume': 500_000_000, 'circulating_supply': 300_000_000,
     'total_supply': 400_000_000, 'current_price': 30.0},
    {'id': 'chainlink',  'symbol': 'link',  'name': 'Chainlink',  'market_cap_rank': 15,
     'market_cap': 8_000_000_000, 'fully_diluted_valuation': 9_000_000_000,
     'total_volume': 300_000_000, 'circulating_supply': 500_000_000,
     'total_supply': 1_000_000_000, 'current_price': 14.0},
    {'id': 'polkadot',   'symbol': 'dot',   'name': 'Polkadot',   'market_cap_rank': 20,
     'market_cap': 10_000_000_000, 'fully_diluted_valuation': 12_000_000_000,
     'total_volume': 400_000_000, 'circulating_supply': 1_200_000_000,
     'total_supply': 1_300_000_000, 'current_price': 7.0},
    {'id': 'lowliq',     'symbol': 'lowliq','name': 'LowLiq',     'market_cap_rank': 250,
     'market_cap': 200_000_000, 'fully_diluted_valuation': 250_000_000,
     'total_volume': 5_000_000, 'circulating_supply': 100_000_000,
     'total_supply': 200_000_000, 'current_price': 0.5},
]


# ------------------------------------------------------------------
# Test
# ------------------------------------------------------------------

@pytest.fixture
def tmp_output(tmp_path):
    return str(tmp_path)


@pytest.fixture
def screener_config(tmp_path) -> ScreenerConfig:
    return ScreenerConfig(
        min_market_cap=100_000_000,
        min_24h_volume=1_000_000,
        max_rank=300,
        universe_pages=1,
        require_above_200d_sma=False,    # disable to reduce fixture complexity
        min_liquidity_volume_24h=1_000_000.0,
        max_spread_bps=200.0,
        lookback_days=250,
        cache_dir=str(tmp_path / 'cache'),
        output_dir=str(tmp_path / 'output'),
        top_n=10,
    )


def _make_binance_get_side_effect():
    """Return the correct fixture data based on the URL path."""
    btc_prices  = _make_prices(260, seed=0)
    eth_prices  = _make_prices(260, seed=1)
    sol_prices  = _make_prices(260, seed=2)
    avax_prices = _make_prices(260, seed=3)
    link_prices = _make_prices(260, seed=4)
    dot_prices  = _make_prices(260, seed=5)
    # Low-liquidity candidate has valid klines but tiny volume
    lowliq_prices = _make_prices(260, mu=0.0, sigma=0.005, seed=6)

    klines_map = {
        'BTCUSDT':    _binance_klines(btc_prices),
        'ETHUSDT':    _binance_klines(eth_prices),
        'SOLUSDT':    _binance_klines(sol_prices),
        'AVAXUSDT':   _binance_klines(avax_prices),
        'LINKUSDT':   _binance_klines(link_prices),
        'DOTUSDT':    _binance_klines(dot_prices),
        'LOWLIQUSDT': _binance_klines(lowliq_prices),
    }

    tickers = [
        _ticker('SOLUSDT',    2_000_000_000),
        _ticker('AVAXUSDT',   500_000_000),
        _ticker('LINKUSDT',   300_000_000),
        _ticker('DOTUSDT',    400_000_000),
        _ticker('LOWLIQUSDT', 50_000),       # below min_liquidity_volume_24h
    ]

    def side_effect(path, params, weight):
        if path == '/api/v3/exchangeInfo':
            return EXCHANGE_INFO
        if path == '/api/v3/klines':
            sym = params['symbol']
            return klines_map.get(sym, klines_map['BTCUSDT'])
        if path == '/api/v3/ticker/24hr':
            return tickers
        if path == '/api/v3/depth':
            return _depth()
        raise ValueError(f'Unexpected path: {path}')

    return side_effect


def test_end_to_end(screener_config, monkeypatch):
    """Full pipeline with mocked HTTP: 5 candidates, 1 low-liquidity filtered out."""
    # Mock CoinGecko
    cg_mock = MagicMock()
    cg_mock._make_request.side_effect = lambda endpoint, params: (
        COINGECKO_MARKETS if 'markets' in endpoint
        else {  # fetch_prices for MYST context
            'mysterium': {'usd': 0.07, 'usd_24h_change': -1.5, 'usd_market_cap': 20_000_000}
        }
    )

    # Mock Binance HTTP
    with patch(
        'crypto_portfolio.screener.market_data.BinancePublicClient._get',
        side_effect=_make_binance_get_side_effect(),
    ), patch(
        'crypto_portfolio.screener.universe.CoinGeckoClient',
        return_value=cg_mock,
    ), patch(
        'crypto_portfolio.screener.screener.CoinGeckoClient',
        return_value=cg_mock,
    ):
        result = run_screener('MYST', screener_config)

    # --- Source asset ---
    assert result['metadata']['source_symbol'] == 'MYST'
    assert result['metadata']['source_on_binance'] is False
    assert 'note' in result['metadata']['source_context']

    # --- Results exist ---
    all_results = result['results']
    assert len(all_results) > 0

    passed = [c for c in all_results if not c.get('hard_filtered')]
    filtered = [c for c in all_results if c.get('hard_filtered')]

    # LOWLIQ should be hard-filtered
    assert any('LOWLIQ' in c.get('symbol', '') for c in filtered), \
        'Low-liquidity candidate should have been filtered'

    # Passed candidates have composite scores
    for c in passed:
        assert c.get('composite_score') is not None
        assert 0.0 <= c['composite_score'] <= 1.0
        assert c.get('overall_rank') is not None

    # --- Ranking is descending ---
    ranked_scores = [c['composite_score'] for c in passed]
    assert ranked_scores == sorted(ranked_scores, reverse=True)

    # --- Output files exist and are valid ---
    paths = result['output_paths']
    assert os.path.exists(paths['csv'])
    assert os.path.exists(paths['json'])

    with open(paths['json']) as f:
        payload = json.load(f)
    assert 'metadata' in payload
    assert 'results'  in payload
    assert payload['metadata']['benchmark'] == 'BTC'
    assert 'weights' in payload['metadata']

    # --- CSV has header row and data ---
    with open(paths['csv']) as f:
        lines = f.readlines()
    assert len(lines) >= 2   # header + at least one row
    assert 'composite_score' in lines[0]
    assert 'symbol' in lines[0]


def test_source_on_binance_no_extra_cg_call(screener_config, monkeypatch):
    """When source IS on Binance, no CoinGecko price fetch for source context."""
    cg_mock = MagicMock()
    cg_mock._make_request.return_value = COINGECKO_MARKETS

    calls_to_fetch_prices = []

    def mock_fetch_prices(syms):
        calls_to_fetch_prices.extend(syms)
        return {}

    cg_mock.fetch_prices.side_effect = mock_fetch_prices

    with patch(
        'crypto_portfolio.screener.market_data.BinancePublicClient._get',
        side_effect=_make_binance_get_side_effect(),
    ), patch(
        'crypto_portfolio.screener.universe.CoinGeckoClient',
        return_value=cg_mock,
    ), patch(
        'crypto_portfolio.screener.screener.CoinGeckoClient',
        return_value=cg_mock,
    ):
        result = run_screener('SOL', screener_config)

    assert result['metadata']['source_on_binance'] is True
    assert 'SOL' not in calls_to_fetch_prices


def test_empty_universe_returns_gracefully(screener_config):
    """When no candidates pass universe filters, return gracefully with empty results."""
    cg_mock = MagicMock()
    cg_mock._make_request.return_value = []  # empty CoinGecko response

    with patch(
        'crypto_portfolio.screener.market_data.BinancePublicClient._get',
        return_value=EXCHANGE_INFO,
    ), patch(
        'crypto_portfolio.screener.universe.CoinGeckoClient',
        return_value=cg_mock,
    ), patch(
        'crypto_portfolio.screener.screener.CoinGeckoClient',
        return_value=cg_mock,
    ):
        result = run_screener('MYST', screener_config)

    assert result['results'] == []
    assert result['output_paths'] == {}
