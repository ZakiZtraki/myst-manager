"""Pure metric functions that operate on raw Binance klines.

All inputs use the Binance kline format:
    [open_time, open, high, low, close, volume, close_time,
     quote_volume, num_trades, taker_buy_base, taker_buy_quote, ignore]

No I/O.  All functions are deterministic and independently unit-testable.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _closes(klines: List[List]) -> np.ndarray:
    return np.array([float(k[4]) for k in klines])


def _log_returns(closes: np.ndarray) -> np.ndarray:
    """Compute log returns from a closes array (length = len(closes) - 1)."""
    return np.diff(np.log(closes))


# ------------------------------------------------------------------
# Momentum / returns
# ------------------------------------------------------------------

def compute_returns(
    klines: List[List],
    windows: Sequence[int] = (7, 30, 90, 180, 365),
) -> Dict[str, Optional[float]]:
    """Return over each window: (close_now - close_n_days_ago) / close_n_days_ago."""
    closes = _closes(klines)
    result: Dict[str, Optional[float]] = {}
    for w in windows:
        if len(closes) >= w + 1:
            result[f'return_{w}d'] = float((closes[-1] - closes[-(w + 1)]) / closes[-(w + 1)])
        else:
            result[f'return_{w}d'] = None
    return result


def compute_sma(
    klines: List[List],
    periods: Sequence[int] = (50, 200),
) -> Dict[str, Optional[float]]:
    """Simple moving averages for the given periods."""
    closes = _closes(klines)
    result: Dict[str, Optional[float]] = {}
    for p in periods:
        result[f'sma_{p}d'] = float(np.mean(closes[-p:])) if len(closes) >= p else None
    return result


def above_200d_sma(klines: List[List]) -> Optional[bool]:
    """True if current close is above the 200-day SMA; None if insufficient data."""
    closes = _closes(klines)
    if len(closes) < 200:
        return None
    return bool(closes[-1] > float(np.mean(closes[-200:])))


# ------------------------------------------------------------------
# Risk metrics
# ------------------------------------------------------------------

def compute_volatility(klines: List[List]) -> Optional[float]:
    """Annualised realised volatility = std(daily log returns) × √365."""
    closes = _closes(klines)
    if len(closes) < 2:
        return None
    lr = _log_returns(closes)
    if np.all(lr == 0):
        return 0.0
    return float(np.std(lr, ddof=1) * math.sqrt(365))


def compute_max_drawdown(klines: List[List]) -> Optional[float]:
    """Maximum drawdown over the full kline window (negative fraction, e.g. -0.35)."""
    closes = _closes(klines)
    if len(closes) < 2:
        return None
    peaks = np.maximum.accumulate(closes)
    return float(np.min((closes - peaks) / peaks))


def _align_log_returns(
    a_klines: List[List], b_klines: List[List]
) -> Tuple[np.ndarray, np.ndarray]:
    """Return aligned log-return arrays for two kline series, trimmed to common length."""
    a_lr = _log_returns(_closes(a_klines))
    b_lr = _log_returns(_closes(b_klines))
    n = min(len(a_lr), len(b_lr))
    return a_lr[-n:], b_lr[-n:]


def compute_beta(
    asset_klines: List[List],
    btc_klines: List[List],
    min_obs: int = 30,
) -> Optional[float]:
    """Beta of the asset to BTC via OLS on aligned daily log returns."""
    a_lr, b_lr = _align_log_returns(asset_klines, btc_klines)
    if len(a_lr) < min_obs:
        return None
    if np.std(b_lr) == 0:
        return None
    A = np.vstack([b_lr, np.ones(len(b_lr))]).T
    beta = float(np.linalg.lstsq(A, a_lr, rcond=None)[0][0])
    return beta


def compute_correlation_to_btc(
    asset_klines: List[List],
    btc_klines: List[List],
    min_obs: int = 30,
) -> Optional[float]:
    """Pearson correlation of daily log returns vs BTC."""
    a_lr, b_lr = _align_log_returns(asset_klines, btc_klines)
    if len(a_lr) < min_obs:
        return None
    if np.std(a_lr) == 0 or np.std(b_lr) == 0:
        return None
    return float(np.corrcoef(a_lr, b_lr)[0, 1])


# ------------------------------------------------------------------
# Risk-adjusted return
# ------------------------------------------------------------------

def compute_sharpe(
    klines: List[List],
    risk_free_rate: float = 0.0,
) -> Optional[float]:
    """Annualised Sharpe ratio (mean excess return / std of excess return × √365)."""
    closes = _closes(klines)
    if len(closes) < 2:
        return None
    lr = _log_returns(closes)
    excess = lr - risk_free_rate / 365
    std = float(np.std(excess, ddof=1))
    if std == 0:
        return None
    return float(np.mean(excess) / std * math.sqrt(365))


def compute_sortino(
    klines: List[List],
    risk_free_rate: float = 0.0,
) -> Optional[float]:
    """Annualised Sortino ratio (mean excess return / downside std × √365)."""
    closes = _closes(klines)
    if len(closes) < 2:
        return None
    lr = _log_returns(closes)
    excess = lr - risk_free_rate / 365
    downside = excess[excess < 0]
    if len(downside) < 2:
        return None
    dd_std = float(np.std(downside, ddof=1))
    if dd_std == 0:
        return None
    return float(np.mean(excess) / dd_std * math.sqrt(365))


# ------------------------------------------------------------------
# Relative strength vs benchmark
# ------------------------------------------------------------------

def compute_rs_vs_benchmark(
    asset_klines: List[List],
    bench_klines: List[List],
    windows: Sequence[int] = (7, 30, 90, 180, 365),
) -> Dict[str, Optional[float]]:
    """RS = asset_return_Nd − benchmark_return_Nd for each window."""
    a_ret = compute_returns(asset_klines, windows)
    b_ret = compute_returns(bench_klines, windows)
    result: Dict[str, Optional[float]] = {}
    for w in windows:
        a, b = a_ret.get(f'return_{w}d'), b_ret.get(f'return_{w}d')
        result[f'rs_{w}d'] = (a - b) if (a is not None and b is not None) else None
    return result


# ------------------------------------------------------------------
# Liquidity
# ------------------------------------------------------------------

def compute_spread_bps(order_book: Dict) -> Optional[float]:
    """Best bid/ask spread in basis points."""
    bids = order_book.get('bids', [])
    asks = order_book.get('asks', [])
    if not bids or not asks:
        return None
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    if best_bid <= 0 or best_ask <= 0:
        return None
    mid = (best_bid + best_ask) / 2
    return float((best_ask - best_bid) / mid * 10_000)


def compute_depth_within_2pct(order_book: Dict) -> Optional[float]:
    """Total quote value (bids + asks) within ±2% of mid price."""
    bids = order_book.get('bids', [])
    asks = order_book.get('asks', [])
    if not bids or not asks:
        return None
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    if best_bid <= 0 or best_ask <= 0:
        return None
    mid = (best_bid + best_ask) / 2
    lower, upper = mid * 0.98, mid * 1.02
    bid_depth = sum(
        float(p) * float(q) for p, q in bids if float(p) >= lower
    )
    ask_depth = sum(
        float(p) * float(q) for p, q in asks if float(p) <= upper
    )
    return float(bid_depth + ask_depth)
