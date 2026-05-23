"""Unit tests for ScreenerScorer: percentile ranking, hard filters, composite scoring."""
from __future__ import annotations

import pytest

from crypto_portfolio.screener.config import ScreenerConfig
from crypto_portfolio.screener.scorer import ScreenerScorer, _percentile_rank


# ======================================================================
# _percentile_rank
# ======================================================================

class TestPercentileRank:
    def test_three_values_ordered(self):
        ranks = _percentile_rank([10.0, 20.0, 30.0], higher_is_better=True)
        assert ranks[0] == pytest.approx(0.0)
        assert ranks[1] == pytest.approx(0.5)
        assert ranks[2] == pytest.approx(1.0)

    def test_reversed_when_lower_is_better(self):
        ranks = _percentile_rank([10.0, 20.0, 30.0], higher_is_better=False)
        assert ranks[0] == pytest.approx(1.0)
        assert ranks[2] == pytest.approx(0.0)

    def test_none_values_preserved(self):
        ranks = _percentile_rank([None, 10.0, 20.0], higher_is_better=True)
        assert ranks[0] is None
        assert ranks[1] == pytest.approx(0.0)
        assert ranks[2] == pytest.approx(1.0)

    def test_all_none(self):
        assert _percentile_rank([None, None]) == [None, None]

    def test_single_valid_gets_neutral(self):
        ranks = _percentile_rank([None, 42.0], higher_is_better=True)
        assert ranks[0] is None
        assert ranks[1] == pytest.approx(0.5)

    def test_identical_values_equal_rank(self):
        ranks = _percentile_rank([5.0, 5.0, 5.0], higher_is_better=True)
        # All equal → all get rank 0 (argsort of argsort all-equal array)
        # Implementation returns positional rank, so check they're all equal
        assert ranks[0] == ranks[1] == ranks[2]


# ======================================================================
# Hard filters
# ======================================================================

class TestHardFilters:
    def _config(self, **kwargs) -> ScreenerConfig:
        defaults = dict(
            require_above_200d_sma=True,
            min_liquidity_volume_24h=500_000.0,
            max_spread_bps=100.0,
        )
        defaults.update(kwargs)
        return ScreenerConfig(**defaults)

    def _coin(self, above_200d=True, vol=1_000_000.0, spread=20.0) -> dict:
        return {
            'symbol': 'TEST',
            'above_200d': above_200d,
            'volume_24h_binance': vol,
            'spread_bps': spread,
        }

    def test_passes_all_filters(self):
        scorer = ScreenerScorer(self._config())
        passed, dropped = scorer.apply_hard_filters([self._coin()])
        assert len(passed) == 1
        assert len(dropped) == 0

    def test_fails_200d_filter(self):
        scorer = ScreenerScorer(self._config(require_above_200d_sma=True))
        passed, dropped = scorer.apply_hard_filters([self._coin(above_200d=False)])
        assert len(passed) == 0
        assert 'below_200d_sma' in dropped[0]['filter_reasons']

    def test_fails_liquidity_filter(self):
        scorer = ScreenerScorer(self._config(min_liquidity_volume_24h=1_000_000.0))
        passed, dropped = scorer.apply_hard_filters([self._coin(vol=100_000.0)])
        assert len(passed) == 0
        assert any('low_liquidity' in r for r in dropped[0]['filter_reasons'])

    def test_fails_spread_filter(self):
        scorer = ScreenerScorer(self._config(max_spread_bps=50.0))
        passed, dropped = scorer.apply_hard_filters([self._coin(spread=200.0)])
        assert len(passed) == 0
        assert any('spread' in r for r in dropped[0]['filter_reasons'])

    def test_200d_filter_skipped_when_disabled(self):
        scorer = ScreenerScorer(self._config(require_above_200d_sma=False))
        passed, dropped = scorer.apply_hard_filters([self._coin(above_200d=False)])
        assert len(passed) == 1

    def test_none_above_200d_not_filtered(self):
        # None means insufficient data — should not be dropped for this reason
        scorer = ScreenerScorer(self._config(require_above_200d_sma=True))
        coin = self._coin()
        coin['above_200d'] = None
        passed, dropped = scorer.apply_hard_filters([coin])
        assert len(passed) == 1


# ======================================================================
# Composite scoring
# ======================================================================

class TestCompositeScore:
    def _coin(self, sortino=1.0, rs_90d=0.10, vol=1_000_000.0, corr=0.5) -> dict:
        return {
            'symbol': 'X',
            'sortino': sortino,
            'rs_90d': rs_90d,
            'volume_24h_binance': vol,
            'corr_to_btc': corr,
            'spread_bps': 20.0,
        }

    def test_higher_sortino_gets_higher_score(self):
        cfg = ScreenerConfig()
        scorer = ScreenerScorer(cfg)
        c1 = self._coin(sortino=0.1)
        c2 = self._coin(sortino=2.0)
        scorer.score([c1, c2])
        assert c2['composite_score'] > c1['composite_score']

    def test_higher_liquidity_gets_higher_score(self):
        cfg = ScreenerConfig()
        scorer = ScreenerScorer(cfg)
        c1 = self._coin(vol=100_000.0)
        c2 = self._coin(vol=50_000_000.0)
        scorer.score([c1, c2])
        assert c2['composite_score'] > c1['composite_score']

    def test_lower_correlation_gets_higher_diversification(self):
        cfg = ScreenerConfig()
        scorer = ScreenerScorer(cfg)
        c1 = self._coin(corr=0.95)   # highly correlated → lower diversification rank
        c2 = self._coin(corr=0.10)   # low correlation → higher diversification rank
        scorer.score([c1, c2])
        assert c2['rank_diversification'] > c1['rank_diversification']

    def test_scores_between_0_and_1(self):
        cfg = ScreenerConfig()
        scorer = ScreenerScorer(cfg)
        coins = [self._coin(sortino=i, rs_90d=i * 0.01, vol=i * 1e5, corr=i * 0.1)
                 for i in range(1, 6)]
        scorer.score(coins)
        for c in coins:
            assert 0.0 <= c['composite_score'] <= 1.0

    def test_overall_rank_assigned(self):
        cfg = ScreenerConfig()
        scorer = ScreenerScorer(cfg)
        coins = [self._coin(sortino=float(i)) for i in range(5, 0, -1)]
        scorer.score(coins)
        ranks = [c['overall_rank'] for c in coins]
        assert sorted(ranks) == list(range(1, 6))

    def test_liquidity_warning_low_volume(self):
        cfg = ScreenerConfig(min_liquidity_volume_24h=500_000.0)
        scorer = ScreenerScorer(cfg)
        low = self._coin(vol=100_000.0)   # below 5× floor
        scorer.score([low])
        assert low['liquidity_warning'] is True

    def test_empty_candidates(self):
        scorer = ScreenerScorer(ScreenerConfig())
        assert scorer.score([]) == []
