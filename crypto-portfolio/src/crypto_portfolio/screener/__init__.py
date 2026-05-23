"""Swap-target screener: ranks candidate destination assets using quantitative metrics.

Usage:
    from crypto_portfolio.screener import run_screener, ScreenerConfig
    cfg = ScreenerConfig.from_json('screener_config.json')
    result = run_screener('MYST', cfg)
"""
from .screener import run_screener
from .config import ScreenerConfig

__all__ = ['run_screener', 'ScreenerConfig']
