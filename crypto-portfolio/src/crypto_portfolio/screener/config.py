"""Screener configuration dataclass with JSON/env loading."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ScreenerConfig:
    # ------------------------------------------------------------------ #
    # Universe filters (CoinGecko)                                        #
    # ------------------------------------------------------------------ #
    min_market_cap: float = 100_000_000.0     # USD
    min_24h_volume: float = 1_000_000.0       # USD
    max_rank: int = 300
    universe_pages: int = 3                   # CoinGecko pages (250 coins/page)

    # ------------------------------------------------------------------ #
    # Hard filters (applied before scoring)                               #
    # ------------------------------------------------------------------ #
    require_above_200d_sma: bool = True
    min_liquidity_volume_24h: float = 500_000.0   # Binance 24h quote volume (USD)
    max_spread_bps: float = 100.0                  # bid/ask spread in basis points

    # ------------------------------------------------------------------ #
    # Metrics                                                             #
    # ------------------------------------------------------------------ #
    risk_free_rate: float = 0.0       # annual, used for Sharpe / Sortino
    lookback_days: int = 365          # kline fetch window

    # ------------------------------------------------------------------ #
    # Composite weights (must sum to 1.0)                                 #
    # ------------------------------------------------------------------ #
    weights: Dict[str, float] = field(default_factory=lambda: {
        'sortino':       0.30,
        'rs_vs_btc':     0.25,
        'liquidity':     0.25,
        'diversification': 0.20,   # (1 − corr_to_btc)
    })

    # ------------------------------------------------------------------ #
    # Cache                                                               #
    # ------------------------------------------------------------------ #
    cache_dir: str = '.screener_cache'
    cache_ttl_hours: float = 4.0

    # ------------------------------------------------------------------ #
    # Rate limiting                                                       #
    # ------------------------------------------------------------------ #
    max_weight_per_min: int = 1100   # Binance hard limit = 1200; leave headroom

    # ------------------------------------------------------------------ #
    # Output                                                              #
    # ------------------------------------------------------------------ #
    output_dir: str = 'screener_output'
    top_n: int = 20

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    @classmethod
    def from_json(cls, path: str) -> 'ScreenerConfig':
        with open(path) as f:
            data = json.load(f)
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @classmethod
    def from_env(cls, base: Optional['ScreenerConfig'] = None) -> 'ScreenerConfig':
        cfg = base or cls()
        mapping = {
            'SCREENER_MIN_MARKET_CAP':        ('min_market_cap', float),
            'SCREENER_MIN_24H_VOLUME':         ('min_24h_volume', float),
            'SCREENER_MAX_RANK':               ('max_rank', int),
            'SCREENER_MIN_LIQUIDITY_VOL':      ('min_liquidity_volume_24h', float),
            'SCREENER_MAX_SPREAD_BPS':         ('max_spread_bps', float),
            'SCREENER_RISK_FREE_RATE':         ('risk_free_rate', float),
            'SCREENER_LOOKBACK_DAYS':          ('lookback_days', int),
            'SCREENER_CACHE_DIR':              ('cache_dir', str),
            'SCREENER_CACHE_TTL_HOURS':        ('cache_ttl_hours', float),
            'SCREENER_OUTPUT_DIR':             ('output_dir', str),
            'SCREENER_TOP_N':                  ('top_n', int),
        }
        for env_key, (attr, cast) in mapping.items():
            val = os.getenv(env_key)
            if val is not None:
                setattr(cfg, attr, cast(val))
        return cfg

    def validate(self) -> None:
        total = sum(self.weights.values())
        if not (0.99 <= total <= 1.01):
            raise ValueError(f'Composite weights must sum to 1.0, got {total:.3f}')
        if self.lookback_days < 200:
            raise ValueError('lookback_days must be >= 200 for 200d SMA to be computable')
