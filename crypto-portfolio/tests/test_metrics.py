"""Unit tests for screener metric functions with deterministic fixture data."""
from __future__ import annotations

import math

import numpy as np
import pytest

from crypto_portfolio.screener.metrics import (
    above_200d_sma,
    compute_beta,
    compute_correlation_to_btc,
    compute_depth_within_2pct,
    compute_max_drawdown,
    compute_returns,
    compute_rs_vs_benchmark,
    compute_sharpe,
    compute_sma,
    compute_sortino,
    compute_spread_bps,
    compute_volatility,
)
from conftest import make_klines, make_order_book


# ======================================================================
# Returns
# ======================================================================

class TestReturns:
    def test_7d_return_exact(self):
        # 11 data points: positions -(8) through -1
        # close[-8] = 100, close[-1] = 110 → 10% gain
        prices = [100.0] * 10 + [110.0]
        ret = compute_returns(make_klines(prices), windows=(7,))
        assert ret['return_7d'] is not None
        assert abs(ret['return_7d'] - 0.10) < 1e-9

    def test_negative_return(self):
        prices = [100.0] * 8 + [90.0]   # 9 points, close[-8]=100 close[-1]=90
        ret = compute_returns(make_klines(prices), windows=(7,))
        assert abs(ret['return_7d'] - (-0.10)) < 1e-9

    def test_none_when_insufficient(self):
        prices = [100.0, 102.0, 105.0]
        ret = compute_returns(make_klines(prices), windows=(7, 30))
        assert ret['return_7d'] is None
        assert ret['return_30d'] is None

    def test_exact_window_boundary(self):
        # Exactly w+1 = 8 points for w=7; should NOT be None
        prices = [100.0] * 7 + [110.0]   # 8 points total
        ret = compute_returns(make_klines(prices), windows=(7,))
        assert ret['return_7d'] is not None


# ======================================================================
# SMA / regime
# ======================================================================

class TestSMA:
    def test_sma_flat(self):
        prices = [50.0] * 250
        smas = compute_sma(make_klines(prices), periods=(50, 200))
        assert abs(smas['sma_50d'] - 50.0) < 1e-9
        assert abs(smas['sma_200d'] - 50.0) < 1e-9

    def test_sma_insufficient_data(self):
        prices = [100.0] * 100
        smas = compute_sma(make_klines(prices), periods=(200,))
        assert smas['sma_200d'] is None

    def test_above_200d_true(self):
        prices = [100.0] * 200 + [101.0]
        assert above_200d_sma(make_klines(prices)) is True

    def test_above_200d_false(self):
        prices = [100.0] * 200 + [99.0]
        assert above_200d_sma(make_klines(prices)) is False

    def test_above_200d_none_on_short_series(self):
        assert above_200d_sma(make_klines([100.0] * 150)) is None


# ======================================================================
# Volatility
# ======================================================================

class TestVolatility:
    def test_flat_price_zero_vol(self):
        klines = make_klines([100.0] * 100)
        assert compute_volatility(klines) == 0.0

    def test_constant_log_return_near_zero_std(self):
        # Exact geometric series: all log returns identical → std ≈ 0
        prices = [100.0 * math.exp(0.001 * i) for i in range(100)]
        vol = compute_volatility(make_klines(prices))
        assert vol < 1e-9

    def test_volatile_series_in_plausible_range(self):
        rng = np.random.default_rng(42)
        prices = list(100.0 * np.cumprod(1 + rng.normal(0.001, 0.02, 300)))
        vol = compute_volatility(make_klines(prices))
        # Daily σ ≈ 0.02 → annual ≈ 0.02 × √365 ≈ 38.2%
        assert 0.25 < vol < 0.55

    def test_insufficient_data(self):
        assert compute_volatility(make_klines([100.0])) is None


# ======================================================================
# Max drawdown
# ======================================================================

class TestMaxDrawdown:
    def test_no_drawdown_monotone_up(self):
        prices = list(range(100, 200))
        dd = compute_max_drawdown(make_klines(prices))
        assert abs(dd) < 1e-9

    def test_50pct_drawdown(self):
        prices = [100.0] * 50 + [50.0] * 50
        dd = compute_max_drawdown(make_klines(prices))
        assert abs(dd - (-0.5)) < 1e-9

    def test_20pct_drawdown_partial_recovery(self):
        prices = [100.0, 80.0, 90.0]
        dd = compute_max_drawdown(make_klines(prices))
        assert abs(dd - (-0.20)) < 1e-9

    def test_single_point_none(self):
        assert compute_max_drawdown(make_klines([100.0])) is None


# ======================================================================
# Beta & Correlation
# ======================================================================

class TestBetaCorrelation:
    def _trending(self, seed: int, mu: float = 0.001, sigma: float = 0.02, n: int = 200):
        rng = np.random.default_rng(seed)
        return list(100.0 * np.cumprod(1 + rng.normal(mu, sigma, n)))

    def test_beta_to_self_is_one(self):
        prices = self._trending(0)
        kl = make_klines(prices)
        beta = compute_beta(kl, kl)
        assert beta is not None
        assert abs(beta - 1.0) < 1e-6

    def test_corr_to_self_is_one(self):
        prices = self._trending(1)
        kl = make_klines(prices)
        corr = compute_correlation_to_btc(kl, kl)
        assert corr is not None
        assert abs(corr - 1.0) < 1e-6

    def test_beta_insufficient_returns_none(self):
        kl = make_klines([100.0] * 20)
        assert compute_beta(kl, kl, min_obs=30) is None

    def test_independent_series_low_corr(self):
        rng = np.random.default_rng(99)
        p1 = list(100.0 * np.cumprod(1 + rng.normal(0, 0.02, 300)))
        p2 = list(100.0 * np.cumprod(1 + rng.normal(0, 0.02, 300)))
        corr = compute_correlation_to_btc(make_klines(p1), make_klines(p2))
        assert corr is not None
        assert -0.4 < corr < 0.4


# ======================================================================
# Sharpe / Sortino
# ======================================================================

class TestSharpeAndSortino:
    def test_sharpe_positive_uptrend(self):
        rng = np.random.default_rng(10)
        prices = list(100.0 * np.cumprod(1 + rng.normal(0.003, 0.01, 200)))
        s = compute_sharpe(make_klines(prices))
        assert s is not None and s > 0

    def test_sharpe_higher_rf_lowers_ratio(self):
        rng = np.random.default_rng(11)
        prices = list(100.0 * np.cumprod(1 + rng.normal(0.001, 0.02, 200)))
        kl = make_klines(prices)
        s0 = compute_sharpe(kl, risk_free_rate=0.0)
        s5 = compute_sharpe(kl, risk_free_rate=0.05)
        if s0 is not None and s5 is not None:
            assert s0 >= s5

    def test_sortino_flat_returns_none(self):
        # Flat price → no downside returns → None
        kl = make_klines([100.0] * 100)
        assert compute_sortino(kl) is None

    def test_sortino_positive_uptrend(self):
        rng = np.random.default_rng(12)
        prices = list(100.0 * np.cumprod(1 + rng.normal(0.003, 0.01, 200)))
        s = compute_sortino(make_klines(prices))
        # Uptrend will have some negative days, so sortino should be defined and positive
        if s is not None:
            assert s > 0

    def test_sharpe_none_on_single_point(self):
        assert compute_sharpe(make_klines([100.0])) is None


# ======================================================================
# RS vs benchmark
# ======================================================================

class TestRS:
    def test_positive_outperformance(self):
        asset = make_klines([100.0] * 8 + [120.0])   # +20% over 7d
        bench = make_klines([100.0] * 8 + [110.0])   # +10% over 7d
        rs = compute_rs_vs_benchmark(asset, bench, windows=(7,))
        assert abs(rs['rs_7d'] - 0.10) < 1e-9

    def test_underperformance(self):
        asset = make_klines([100.0] * 8 + [90.0])    # −10%
        bench = make_klines([100.0] * 8 + [100.0])   # flat
        rs = compute_rs_vs_benchmark(asset, bench, windows=(7,))
        assert abs(rs['rs_7d'] - (-0.10)) < 1e-9

    def test_none_when_insufficient(self):
        kl = make_klines([100.0] * 5)
        rs = compute_rs_vs_benchmark(kl, kl, windows=(7,))
        assert rs['rs_7d'] is None


# ======================================================================
# Spread & Depth
# ======================================================================

class TestLiquidity:
    def test_spread_200bps(self):
        book = make_order_book(99.0, 101.0)
        # spread = (101−99)/100 × 10000 = 200 bps
        spread = compute_spread_bps(book)
        assert spread is not None
        assert abs(spread - 200.0) < 0.01

    def test_spread_zero_bid_returns_none(self):
        book = {'bids': [['0', '1']], 'asks': [['100', '1']]}
        assert compute_spread_bps(book) is None

    def test_spread_empty_book_none(self):
        assert compute_spread_bps({'bids': [], 'asks': []}) is None

    def test_depth_within_2pct(self):
        # mid = 100, ±2% = [98, 102]
        # bids: 99@10 (in range), 97@10 (out of range)
        # asks: 101@10 (in range), 103@10 (out of range)
        book = {
            'bids': [['99', '10'], ['97', '10']],
            'asks': [['101', '10'], ['103', '10']],
        }
        depth = compute_depth_within_2pct(book)
        # bid: 99×10 = 990; ask: 101×10 = 1010; total = 2000
        assert depth is not None
        assert abs(depth - 2000.0) < 0.01

    def test_depth_empty_book_none(self):
        assert compute_depth_within_2pct({'bids': [], 'asks': []}) is None
