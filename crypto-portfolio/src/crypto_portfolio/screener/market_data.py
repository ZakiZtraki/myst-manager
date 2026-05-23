"""Binance public market-data client with weight-aware rate limiting and local kline cache.

Uses only unauthenticated Binance REST endpoints — no API keys required.
Documented endpoints:
  GET /api/v3/klines          weight=2
  GET /api/v3/ticker/24hr     weight=40 (all) / 2 (single)
  GET /api/v3/depth           weight=5  (limit<=100)
  GET /api/v3/exchangeInfo    weight=20
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

BINANCE_BASE = 'https://api.binance.com'

# Documented endpoint request weights
_W_KLINES = 2
_W_TICKER_ALL = 40
_W_DEPTH_100 = 5
_W_EXCHANGE_INFO = 20


class WeightBudget:
    """Track Binance 1-minute rolling request weight and throttle before the hard limit."""

    def __init__(self, max_weight: int = 1100) -> None:
        self._max = max_weight
        self._used = 0
        self._window_start = time.monotonic()

    def _reset_if_new_window(self) -> None:
        if time.monotonic() - self._window_start >= 60.0:
            self._used = 0
            self._window_start = time.monotonic()

    def consume(self, weight: int) -> None:
        self._reset_if_new_window()
        if self._used + weight > self._max:
            sleep_for = 61.0 - (time.monotonic() - self._window_start)
            logger.info('Weight budget reached (%d/%d); sleeping %.1fs', self._used, self._max, sleep_for)
            time.sleep(max(0.0, sleep_for))
            self._used = 0
            self._window_start = time.monotonic()
        self._used += weight

    def sync_from_header(self, value: Optional[str]) -> None:
        """Keep internal counter in sync with the actual header returned by Binance."""
        if value is not None:
            try:
                self._used = int(value)
            except ValueError:
                pass


class BinancePublicClient:
    """Read-only Binance public API client — no authentication required."""

    def __init__(
        self,
        cache_dir: str = '.screener_cache',
        cache_ttl_hours: float = 4.0,
        max_weight_per_min: int = 1100,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_ttl = cache_ttl_hours * 3600
        self._budget = WeightBudget(max_weight_per_min)
        self._session = requests.Session()

    # ------------------------------------------------------------------
    # Internal HTTP + cache helpers
    # ------------------------------------------------------------------

    def _get(self, path: str, params: Dict, weight: int) -> object:
        self._budget.consume(weight)
        url = f'{BINANCE_BASE}{path}'
        for attempt in range(4):
            resp = self._session.get(url, params=params, timeout=20)
            self._budget.sync_from_header(resp.headers.get('X-MBX-USED-WEIGHT-1M'))
            if resp.status_code == 429:
                retry_after = int(resp.headers.get('Retry-After', 30))
                logger.warning('Binance 429 rate-limit — sleeping %ds (attempt %d)', retry_after, attempt + 1)
                time.sleep(retry_after)
                continue
            if resp.status_code == 418:
                raise RuntimeError('Binance IP banned (418). Stop requests and wait.')
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f'Binance {path} still failing after 4 retries')

    def _cache_key_path(self, key: str) -> Path:
        digest = hashlib.md5(key.encode()).hexdigest()
        return self._cache_dir / f'{digest}.json'

    def _load_cache(self, key: str) -> Optional[object]:
        path = self._cache_key_path(key)
        if not path.exists():
            return None
        try:
            entry = json.loads(path.read_text())
            if time.time() - entry['ts'] < self._cache_ttl:
                return entry['data']
        except (json.JSONDecodeError, KeyError):
            pass
        return None

    def _save_cache(self, key: str, data: object) -> None:
        self._cache_key_path(key).write_text(
            json.dumps({'ts': time.time(), 'data': data})
        )

    # ------------------------------------------------------------------
    # Public API wrappers
    # ------------------------------------------------------------------

    def get_exchange_info(self) -> Dict:
        """Fetch all trading pair metadata. Cached for cache_ttl."""
        key = 'exchange_info'
        cached = self._load_cache(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        data = self._get('/api/v3/exchangeInfo', {}, weight=_W_EXCHANGE_INFO)
        self._save_cache(key, data)
        return data  # type: ignore[return-value]

    def get_usdt_symbols(self) -> 'set[str]':
        """Return the set of active USDT-quoted spot symbols (e.g. {'BTCUSDT', …})."""
        info = self.get_exchange_info()
        return {
            s['symbol']
            for s in info.get('symbols', [])
            if s.get('quoteAsset') == 'USDT' and s.get('status') == 'TRADING'
        }

    def get_klines(
        self,
        symbol: str,
        interval: str = '1d',
        limit: int = 400,
    ) -> List[List]:
        """
        Fetch daily OHLCV klines from /api/v3/klines. Cached per symbol+limit.

        Each entry: [open_time, open, high, low, close, volume, close_time,
                     quote_volume, num_trades, taker_buy_base, taker_buy_quote, '0']
        """
        key = f'klines:{symbol}:{interval}:{limit}'
        cached = self._load_cache(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        data = self._get(
            '/api/v3/klines',
            {'symbol': symbol, 'interval': interval, 'limit': limit},
            weight=_W_KLINES,
        )
        self._save_cache(key, data)
        return data  # type: ignore[return-value]

    def get_all_24hr_tickers(self) -> List[Dict]:
        """
        Fetch 24hr statistics for all symbols in a single call (weight=40).
        Cached for cache_ttl.
        """
        key = 'ticker_24hr_all'
        cached = self._load_cache(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        data = self._get('/api/v3/ticker/24hr', {}, weight=_W_TICKER_ALL)
        self._save_cache(key, data)
        return data  # type: ignore[return-value]

    def get_ticker_map(self) -> Dict[str, Dict]:
        """Return {symbol: ticker_dict} for convenient O(1) lookup."""
        return {t['symbol']: t for t in self.get_all_24hr_tickers()}

    def get_order_book(self, symbol: str, limit: int = 100) -> Dict:
        """
        Fetch top-of-book depth from /api/v3/depth (weight=5 for limit<=100).
        Not cached — caller needs fresh spread/depth data.
        """
        return self._get(  # type: ignore[return-value]
            '/api/v3/depth',
            {'symbol': symbol, 'limit': limit},
            weight=_W_DEPTH_100,
        )
