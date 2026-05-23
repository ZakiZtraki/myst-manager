"""Top-level screener orchestrator: universe → metrics → score → output."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

from ..api_client import CoinGeckoClient, COINGECKO_ID_MAP
from .config import ScreenerConfig
from .market_data import BinancePublicClient
from .metrics import (
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
from .output import write_results
from .scorer import ScreenerScorer
from .universe import UniverseBuilder

logger = logging.getLogger(__name__)


def run_screener(
    source_symbol: str,
    config: ScreenerConfig,
    top_n: Optional[int] = None,
) -> Dict:
    """
    End-to-end screener run.

    Args:
        source_symbol: Asset being rotated out of (e.g. 'MYST').
                       If not on Binance, noted in metadata and CoinGecko
                       data is fetched for context only — does not fail.
        config:        Validated ScreenerConfig.
        top_n:         Override config.top_n for the output table.

    Returns:
        {
          'results':      list of candidate dicts (ranked + filtered),
          'metadata':     run metadata dict,
          'output_paths': {'csv': ..., 'json': ...},
        }
    """
    config.validate()
    effective_top_n = top_n if top_n is not None else config.top_n
    run_ts = datetime.utcnow().isoformat() + 'Z'

    cg_client = CoinGeckoClient()
    binance = BinancePublicClient(
        cache_dir=config.cache_dir,
        cache_ttl_hours=config.cache_ttl_hours,
        max_weight_per_min=config.max_weight_per_min,
    )

    # --- Source asset context (non-fatal; CoinGecko only if not on Binance) ---
    source_ctx = _source_context(source_symbol, binance, cg_client)

    # --- Build candidate universe ---
    builder = UniverseBuilder(config, cg_client)
    candidates = builder.build(binance, source_symbol=source_symbol)
    if not candidates:
        logger.warning('No candidates found — check config thresholds')
        metadata = _make_metadata(run_ts, source_symbol, source_ctx, config, 0, 0, 0)
        return {'results': [], 'metadata': metadata, 'output_paths': {}}

    # --- Benchmarks (one fetch each, reused for all candidates) ---
    btc_klines = binance.get_klines('BTCUSDT', limit=config.lookback_days + 10)
    eth_klines = binance.get_klines('ETHUSDT', limit=config.lookback_days + 10)
    ticker_map = binance.get_ticker_map()

    # --- Per-candidate metric enrichment ---
    for coin in candidates:
        try:
            _enrich(coin, binance, ticker_map, btc_klines, eth_klines, config)
        except Exception as exc:
            logger.warning('Metrics failed for %s: %s', coin.get('binance_symbol'), exc)
            coin['metrics_error'] = str(exc)

    # --- Score: hard filter then composite rank ---
    scorer = ScreenerScorer(config)
    passed, dropped = scorer.apply_hard_filters(candidates)
    ranked = scorer.score(passed)

    # Dropped candidates appended at end (no composite_score / overall_rank)
    for coin in dropped:
        coin.setdefault('composite_score', None)
        coin.setdefault('overall_rank', None)

    all_results = ranked + dropped

    # --- Output ---
    metadata = _make_metadata(
        run_ts, source_symbol, source_ctx, config,
        len(candidates), len(passed), len(dropped),
    )
    output_paths = write_results(
        all_results[:effective_top_n + len(dropped)],
        metadata,
        config.output_dir,
    )
    logger.info('Screener complete. Written to: %s', output_paths)
    return {'results': all_results, 'metadata': metadata, 'output_paths': output_paths}


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _enrich(
    coin: Dict,
    binance: BinancePublicClient,
    ticker_map: Dict,
    btc_klines: List,
    eth_klines: List,
    config: ScreenerConfig,
) -> None:
    """Fetch Binance market data and compute all metrics for a single candidate."""
    sym = coin['binance_symbol']
    klines = binance.get_klines(sym, limit=config.lookback_days + 10)
    depth  = binance.get_order_book(sym)
    ticker = ticker_map.get(sym, {})

    # Liquidity (Binance)
    coin['volume_24h_binance'] = float(ticker.get('quoteVolume') or 0)
    coin['spread_bps']         = compute_spread_bps(depth)
    coin['depth_2pct']         = compute_depth_within_2pct(depth)

    # Returns
    coin.update(compute_returns(klines))

    # SMA / regime
    coin.update(compute_sma(klines, periods=(50, 200)))
    coin['above_200d'] = above_200d_sma(klines)

    # Risk
    coin['volatility']   = compute_volatility(klines)
    coin['max_drawdown'] = compute_max_drawdown(klines)
    coin['beta_to_btc']  = compute_beta(klines, btc_klines)
    coin['corr_to_btc']  = compute_correlation_to_btc(klines, btc_klines)

    # Risk-adjusted
    coin['sharpe']  = compute_sharpe(klines,  config.risk_free_rate)
    coin['sortino'] = compute_sortino(klines, config.risk_free_rate)

    # RS vs BTC (feeds composite) and vs ETH (context only)
    rs_btc = compute_rs_vs_benchmark(klines, btc_klines)
    rs_eth = compute_rs_vs_benchmark(klines, eth_klines)
    for w in (7, 30, 90, 180, 365):
        coin[f'rs_{w}d']     = rs_btc.get(f'rs_{w}d')
        coin[f'rs_eth_{w}d'] = rs_eth.get(f'rs_{w}d')


def _source_context(
    symbol: str,
    binance: BinancePublicClient,
    cg: CoinGeckoClient,
) -> Dict:
    """Fetch source-asset context.  Non-fatal — returns partial data on error."""
    ctx: Dict = {'symbol': symbol}
    usdt_sym = f'{symbol.upper()}USDT'
    usdt_symbols = binance.get_usdt_symbols()
    ctx['on_binance']      = usdt_sym in usdt_symbols
    ctx['binance_symbol']  = usdt_sym if ctx['on_binance'] else None

    if not ctx['on_binance']:
        logger.info(
            '%s is not on Binance — fetching CoinGecko data for context only', symbol
        )
        ctx['note'] = f'{symbol} is not on Binance; shown for context only, not ranked'
        try:
            prices = cg.fetch_prices([symbol])
            cg_id = COINGECKO_ID_MAP.get(symbol.upper(), symbol.lower())
            pd = prices.get(cg_id, {})
            ctx['price_usd']       = pd.get('usd')
            ctx['change_24h_pct']  = pd.get('usd_24h_change')
            ctx['market_cap_usd']  = pd.get('usd_market_cap')
        except Exception as exc:
            ctx['cg_error'] = str(exc)

    return ctx


def _make_metadata(
    run_ts: str,
    source_symbol: str,
    source_ctx: Dict,
    config: ScreenerConfig,
    total: int,
    passed: int,
    dropped: int,
) -> Dict:
    return {
        'run_timestamp':       run_ts,
        'source_symbol':       source_symbol,
        'source_on_binance':   source_ctx.get('on_binance', False),
        'source_context':      source_ctx,
        'benchmark':           'BTC',
        'weights':             config.weights,
        'thresholds': {
            'min_market_cap':          config.min_market_cap,
            'min_24h_volume':          config.min_24h_volume,
            'max_rank':                config.max_rank,
            'require_above_200d_sma':  config.require_above_200d_sma,
            'min_liquidity_volume_24h': config.min_liquidity_volume_24h,
            'max_spread_bps':          config.max_spread_bps,
        },
        'total_candidates':    total,
        'passed_hard_filters': passed,
        'dropped_by_filters':  dropped,
    }
