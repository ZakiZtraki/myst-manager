"""Candidate universe: CoinGecko market list filtered to Binance-listed USDT spot pairs."""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from ..api_client import CoinGeckoClient, COINGECKO_ID_MAP
from .config import ScreenerConfig
from .market_data import BinancePublicClient

logger = logging.getLogger(__name__)


class UniverseBuilder:
    """Fetch and filter the candidate asset universe."""

    def __init__(
        self,
        config: ScreenerConfig,
        cg_client: Optional[CoinGeckoClient] = None,
    ) -> None:
        self._cfg = config
        self._cg = cg_client or CoinGeckoClient()

    def fetch_coingecko_universe(self) -> List[Dict]:
        """
        Pull coins from CoinGecko /coins/markets, applying min_market_cap,
        min_24h_volume, and max_rank thresholds.

        Returns a list of candidate dicts with fundamentals (market cap, FDV,
        circulating/total supply, rank) — data Binance cannot provide.
        """
        candidates: List[Dict] = []
        for page in range(1, self._cfg.universe_pages + 1):
            data = self._cg._make_request('coins/markets', {
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': 250,
                'page': page,
                'sparkline': 'false',
            })
            for coin in data:
                rank = coin.get('market_cap_rank') or 9999
                if rank > self._cfg.max_rank:
                    # Results are sorted by market cap; no point scanning further
                    break
                mcap = coin.get('market_cap') or 0
                vol = coin.get('total_volume') or 0
                if mcap < self._cfg.min_market_cap:
                    continue
                if vol < self._cfg.min_24h_volume:
                    continue
                candidates.append({
                    'cg_id':              coin['id'],
                    'symbol':             coin['symbol'].upper(),
                    'name':               coin.get('name', ''),
                    'market_cap':         mcap,
                    'fdv':                coin.get('fully_diluted_valuation') or 0,
                    'circulating_supply': coin.get('circulating_supply') or 0,
                    'total_supply':       coin.get('total_supply') or 0,
                    'rank':               rank,
                    'volume_24h_cg':      vol,
                    'price_usd':          coin.get('current_price') or 0,
                })
            # CoinGecko free-tier courtesy pause between pages
            time.sleep(0.5)

        logger.info('CoinGecko universe: %d candidates (pages=%d)', len(candidates), self._cfg.universe_pages)
        return candidates

    def filter_binance_listed(
        self,
        candidates: List[Dict],
        binance_client: BinancePublicClient,
    ) -> List[Dict]:
        """Keep only candidates that have an active USDT spot pair on Binance."""
        usdt_symbols = binance_client.get_usdt_symbols()
        result = []
        for coin in candidates:
            binance_sym = f"{coin['symbol']}USDT"
            if binance_sym in usdt_symbols:
                coin['binance_symbol'] = binance_sym
                result.append(coin)
            else:
                logger.debug('%s: no %s on Binance — excluded', coin['symbol'], binance_sym)
        logger.info('After Binance filter: %d candidates', len(result))
        return result

    def build(
        self,
        binance_client: BinancePublicClient,
        source_symbol: Optional[str] = None,
    ) -> List[Dict]:
        """Full pipeline: CoinGecko → Binance filter → exclude source asset."""
        candidates = self.fetch_coingecko_universe()
        candidates = self.filter_binance_listed(candidates, binance_client)
        if source_symbol:
            before = len(candidates)
            candidates = [c for c in candidates if c['symbol'] != source_symbol.upper()]
            if len(candidates) < before:
                logger.info('Excluded source asset %s from candidate set', source_symbol.upper())
        return candidates
