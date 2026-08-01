"""Shared pytest fixtures for screener tests."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import List

SRC_DIR = Path(__file__).resolve().parents[1] / 'src'
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def make_klines(prices: List[float]) -> List[List]:
    """Build minimal Binance-format klines from a close-price list.

    Format per entry:
        [open_time, open, high, low, close, volume, close_time,
         quote_volume, num_trades, taker_buy_base, taker_buy_quote, '0']
    """
    ts = 1_700_000_000_000  # arbitrary epoch ms start
    return [
        [
            ts + i * 86_400_000,
            str(p * 0.999),           # open  (≈ close)
            str(p * 1.001),           # high
            str(p * 0.998),           # low
            str(p),                   # close  <-- used by metrics
            '1000.0',                 # volume
            ts + i * 86_400_000 + 86_399_999,
            str(p * 1_000.0),         # quote_volume
            100,
            '500.0',
            str(p * 500.0),
            '0',
        ]
        for i, p in enumerate(prices)
    ]


def make_order_book(
    best_bid: float,
    best_ask: float,
    depth_levels: int = 5,
) -> dict:
    """Build a minimal order-book dict for spread / depth tests."""
    bids = [[str(best_bid - i * 0.01), '10.0'] for i in range(depth_levels)]
    asks = [[str(best_ask + i * 0.01), '10.0'] for i in range(depth_levels)]
    return {'bids': bids, 'asks': asks}
