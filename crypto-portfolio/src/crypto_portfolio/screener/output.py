"""CSV and JSON output for screener results."""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Ordered column list for the CSV.  Extra keys land in JSON only.
COLUMNS = [
    # Ranking
    'overall_rank', 'symbol', 'name', 'composite_score',
    # Component ranks
    'rank_sortino', 'rank_rs_vs_btc', 'rank_liquidity', 'rank_diversification',
    # Risk-adjusted
    'sortino', 'sharpe',
    # Risk
    'volatility', 'max_drawdown', 'beta_to_btc', 'corr_to_btc',
    # Momentum (absolute returns)
    'return_7d', 'return_30d', 'return_90d', 'return_180d', 'return_365d',
    # Relative strength vs BTC
    'rs_7d', 'rs_30d', 'rs_90d', 'rs_180d', 'rs_365d',
    # Relative strength vs ETH
    'rs_eth_7d', 'rs_eth_30d', 'rs_eth_90d', 'rs_eth_180d', 'rs_eth_365d',
    # Regime
    'sma_50d', 'sma_200d', 'above_200d',
    # Liquidity
    'volume_24h_binance', 'spread_bps', 'depth_2pct',
    'liquidity_warning',
    # Fundamentals (from CoinGecko)
    'market_cap', 'fdv', 'circulating_supply', 'total_supply', 'rank',
    # Filter metadata
    'hard_filtered', 'filter_reasons',
]


def write_results(
    candidates: List[Dict],
    metadata: Dict[str, Any],
    output_dir: str,
) -> Dict[str, str]:
    """Write ranked results to CSV + JSON.  Returns {'csv': path, 'json': path}."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    csv_path  = str(out / f'screener_{ts}.csv')
    json_path = str(out / f'screener_{ts}.json')
    _write_csv(candidates, csv_path)
    _write_json(candidates, metadata, json_path)
    return {'csv': csv_path, 'json': json_path}


def _fmt(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, list):
        return '; '.join(str(x) for x in v)
    return v


def _write_csv(candidates: List[Dict], path: str) -> None:
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction='ignore')
        writer.writeheader()
        for coin in candidates:
            writer.writerow({col: _fmt(coin.get(col)) for col in COLUMNS})


def _write_json(candidates: List[Dict], metadata: Dict, path: str) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'metadata': metadata, 'results': candidates}, f, indent=2, default=str)
