"""Composite scoring and ranking of screener candidates.

Scoring pipeline:
  1. apply_hard_filters()  — drop candidates that fail regime/liquidity/spread gates
  2. score()               — percentile-rank each metric, compute weighted composite

Extension point: add fundamental/qualitative scores here by extending the
`score()` method.  Suggested hook:
    coin['fundamental_score'] = _fundamental_score(coin)   # NOT YET IMPLEMENTED
    # Then add a 'fundamental' key to weights and include it in composite below.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

import numpy as np

from .config import ScreenerConfig

logger = logging.getLogger(__name__)


def _percentile_rank(
    values: List[Optional[float]],
    higher_is_better: bool = True,
) -> List[Optional[float]]:
    """
    Map a list of raw metric values to [0, 1] percentile ranks.

    None values are excluded from ranking and remain None.
    When len(valid) == 1 the single element receives 0.5 (neutral).
    """
    valid_idx = [i for i, v in enumerate(values) if v is not None]
    if not valid_idx:
        return [None] * len(values)

    valid_vals = np.array([values[i] for i in valid_idx], dtype=float)

    n = len(valid_vals)
    if n == 1:
        ranks = [0.5]
    else:
        # Average-rank: tied elements receive the mean of their positional ranks,
        # then normalize to [0, 1].  This mirrors scipy.stats.rankdata(method='average').
        sorted_idx = np.argsort(valid_vals, kind='stable')
        pos = np.empty(n, dtype=float)
        i = 0
        while i < n:
            j = i + 1
            while j < n and valid_vals[sorted_idx[j]] == valid_vals[sorted_idx[i]]:
                j += 1
            avg_pos = (i + j - 1) / 2.0
            for k in range(i, j):
                pos[sorted_idx[k]] = avg_pos
            i = j
        ranks = (pos / (n - 1)).tolist()

    if not higher_is_better:
        ranks = [1.0 - r for r in ranks]

    result: List[Optional[float]] = [None] * len(values)
    for arr_i, orig_i in enumerate(valid_idx):
        result[orig_i] = float(ranks[arr_i])
    return result


class ScreenerScorer:

    def __init__(self, config: ScreenerConfig) -> None:
        self._cfg = config

    def apply_hard_filters(
        self,
        candidates: List[Dict],
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        Split candidates into (passed, filtered_out).

        Hard gates:
          - above_200d_sma  (if require_above_200d_sma=True)
          - volume_24h_binance >= min_liquidity_volume_24h
          - spread_bps <= max_spread_bps
        """
        passed: List[Dict] = []
        dropped: List[Dict] = []
        for coin in candidates:
            reasons: List[str] = []

            if self._cfg.require_above_200d_sma and coin.get('above_200d') is False:
                reasons.append('below_200d_sma')

            vol = coin.get('volume_24h_binance') or 0.0
            if vol < self._cfg.min_liquidity_volume_24h:
                reasons.append(
                    f'low_liquidity:{vol:,.0f}<{self._cfg.min_liquidity_volume_24h:,.0f}'
                )

            spread = coin.get('spread_bps')
            if spread is not None and spread > self._cfg.max_spread_bps:
                reasons.append(f'spread:{spread:.1f}bps>{self._cfg.max_spread_bps:.1f}bps')

            if reasons:
                coin['hard_filtered'] = True
                coin['filter_reasons'] = reasons
                dropped.append(coin)
            else:
                coin['hard_filtered'] = False
                passed.append(coin)

        logger.info(
            'Hard filters: %d passed, %d dropped', len(passed), len(dropped)
        )
        return passed, dropped

    def score(self, candidates: List[Dict]) -> List[Dict]:
        """
        Compute composite score for each candidate, sort descending.

        Default formula (all weights configurable):
            composite = 0.30 × sortino_rank
                      + 0.25 × rs_vs_btc_rank   (90d RS vs BTC)
                      + 0.25 × liquidity_rank
                      + 0.20 × diversification_rank  (1 − corr_to_btc)

        Missing metric values use 0.5 (neutral) so one missing field does
        not invalidate the whole candidate.

        # EXTENSION POINT: fundamental/qualitative scores
        # Uncomment and implement _fundamental_score(coin) to add tokenomics,
        # unlock schedules, audit status, etc. to the composite.
        # coin['fundamental_score'] = _fundamental_score(coin)
        # composite += weights.get('fundamental', 0) * (coin['fundamental_score'] or 0.5)
        """
        if not candidates:
            return []

        w = self._cfg.weights
        _safe = lambda v: v if v is not None else 0.5  # noqa: E731

        sortino_ranks  = _percentile_rank([c.get('sortino')           for c in candidates], True)
        rs_ranks       = _percentile_rank([c.get('rs_90d')            for c in candidates], True)
        liq_ranks      = _percentile_rank([c.get('volume_24h_binance') for c in candidates], True)
        corr_ranks     = _percentile_rank([c.get('corr_to_btc')       for c in candidates], False)

        for i, coin in enumerate(candidates):
            sr = sortino_ranks[i]
            rr = rs_ranks[i]
            lr = liq_ranks[i]
            cr = corr_ranks[i]

            coin['rank_sortino']        = sr
            coin['rank_rs_vs_btc']      = rr
            coin['rank_liquidity']      = lr
            coin['rank_diversification'] = cr

            coin['composite_score'] = round(
                w.get('sortino',         0.30) * _safe(sr) +
                w.get('rs_vs_btc',       0.25) * _safe(rr) +
                w.get('liquidity',       0.25) * _safe(lr) +
                w.get('diversification', 0.20) * _safe(cr),
                4,
            )
            coin['liquidity_warning'] = (
                (coin.get('volume_24h_binance') or 0) < self._cfg.min_liquidity_volume_24h * 5
                or (coin.get('spread_bps') or 0) > self._cfg.max_spread_bps * 0.5
            )

        candidates.sort(key=lambda c: c.get('composite_score') or 0, reverse=True)
        for rank, coin in enumerate(candidates, 1):
            coin['overall_rank'] = rank

        return candidates
