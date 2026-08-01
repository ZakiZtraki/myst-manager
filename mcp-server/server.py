"""
Crypto Portfolio MCP Server — remote-accessible via SSE transport.

Configure Claude to connect to this server at:
    http(s)://<host>:<port>/sse

Environment variables:
    PORTFOLIO_FILE   Path to portfolio JSON (default: /data/portfolio.json)
    USE_BINANCE      Set to 'true' to enable Binance sync (default: false)
    MCP_HOST         Bind host (default: 0.0.0.0)
    MCP_PORT         Bind port (default: 8000)
    MCP_API_KEY      Optional API key for bearer-token auth
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# Resolve crypto-portfolio package relative to this file
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT / "crypto-portfolio" / "src"))

from crypto_portfolio.api_client import COINGECKO_ID_MAP, CoinGeckoClient
from crypto_portfolio.manager import PortfolioManager
from crypto_portfolio.screener import ScreenerConfig, run_screener
from crypto_portfolio.tax import TaxLotTracker
from scheduler import TaskScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PORTFOLIO_FILE = os.getenv("PORTFOLIO_FILE", "/data/portfolio.json")
USE_BINANCE = os.getenv("USE_BINANCE", "false").lower() == "true"
MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

# ---------------------------------------------------------------------------
# Server + scheduler initialisation
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "Crypto Portfolio",
    instructions=(
        "Manage and monitor a cryptocurrency portfolio. "
        "Supports both cash-mode (BUY/SELL) and swap-only mode for MYST node operators "
        "who earn MYST tokens and rebalance entirely via crypto-to-crypto swaps. "
        "Key tools: get_portfolio_status, get_recommendations (returns SWAP actions with "
        "routing when swap_routes is configured), update_portfolio_config (set targets and "
        "myst_balance), record_swap (log a completed swap and update holdings), "
        "screen_swap_targets (rank destination assets by Sortino/RS/liquidity composite score). "
        "Use schedule_task / list_scheduled_tasks / cancel_scheduled_task to automate "
        "recurring operations. Use trigger_task_now to run any task immediately."
    ),
)

scheduler = TaskScheduler(PORTFOLIO_FILE, USE_BINANCE)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _portfolio_manager() -> PortfolioManager:
    return PortfolioManager(PORTFOLIO_FILE, use_binance=USE_BINANCE)


# ---------------------------------------------------------------------------
# Portfolio tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_portfolio_status(format: str = "text") -> str:
    """Return current portfolio values, P&L, and allocation.

    Args:
        format: 'text' (default), 'json'
    """
    try:
        return str(_portfolio_manager().get_status(format=format))
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def get_recommendations() -> str:
    """Return prioritised action recommendations (rebalance, profit-taking, MYST deployment)."""
    try:
        recs = _portfolio_manager().get_recommendations()
        if not recs:
            return "No recommendations at this time."

        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        lines = [f"{len(recs)} RECOMMENDATIONS:\n"]
        for i, r in enumerate(recs, 1):
            action_label = r['action']
            if r['action'] == 'SWAP' and 'from_asset' in r:
                action_label = f"SWAP  {r.get('route', r['from_asset'] + ' → ' + r['asset'])}"
                if 'from_amount' in r:
                    action_label += f"  ({r['from_amount']} {r['from_asset']})"
            lines.append(
                f"{i}. [{emoji.get(r['priority'], '⚪')} {r['priority'].upper()}] {action_label}"
            )
            lines.append(f"   USD value: ~${r.get('amount_usd', 0):,.2f}")
            lines.append(f"   Reason:    {r['rationale']}\n")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def get_daily_report() -> str:
    """Generate and return a full daily portfolio report."""
    try:
        return _portfolio_manager().get_daily_report()
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def check_prices(symbols: list[str]) -> str:
    """Fetch live prices for the given cryptocurrency symbols.

    Args:
        symbols: e.g. ["BTC", "ETH", "SOL"]
    """
    try:
        client = CoinGeckoClient()
        prices = client.fetch_prices(symbols)
        lines = ["CURRENT PRICES:\n"]
        for sym in symbols:
            cg_id = COINGECKO_ID_MAP.get(sym.upper(), sym.lower())
            data = prices.get(cg_id, {})
            if data:
                lines.append(
                    f"{sym.upper()}: ${data.get('usd', 0):,.2f} "
                    f"({data.get('usd_24h_change', 0):+.2f}% 24h)"
                )
            else:
                lines.append(f"{sym.upper()}: not found")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def sync_from_binance() -> str:
    """Sync portfolio holdings from Binance (requires BINANCE_API_KEY + BINANCE_API_SECRET)."""
    try:
        pm = PortfolioManager(PORTFOLIO_FILE, use_binance=True)
        balances = pm.sync_from_binance()
        lines = [f"Synced {len(balances)} assets from Binance:"]
        for b in balances:
            lines.append(f"  {b['asset']}: {b['amount']}")
        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def transfer_myst_to_trade_account(amount: float = -1) -> str:
    """Transfer MYST from Binance Funding Wallet to Spot (trade) account.

    Requires BINANCE_API_KEY + BINANCE_API_SECRET and USE_BINANCE=true.

    Args:
        amount: MYST to transfer. -1 (default) = auto: all above myst_keep_reserve.
                Skips if value is below min_swap_usd threshold.
    """
    try:
        pm = PortfolioManager(PORTFOLIO_FILE, use_binance=True)
        transfer_amount = None if amount < 0 else amount
        result = pm.transfer_myst_to_spot(transfer_amount)
        if result['status'] == 'transferred':
            return (
                f"Transfer complete: {result['transferred']} MYST → Spot account\n"
                f"  Transaction ID:      {result['tran_id']}\n"
                f"  Funding balance was: {result['funding_balance']} MYST\n"
                f"  Reserve kept:        {result['kept_reserve']} MYST"
            )
        return f"Transfer skipped: {result['reason']}"
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def export_portfolio_csv(output_path: str = "/data/portfolio_export.csv") -> str:
    """Export current portfolio snapshot to a CSV file.

    Args:
        output_path: Destination file path (default: /data/portfolio_export.csv)
    """
    try:
        _portfolio_manager().export_to_csv(output_path)
        return f"Portfolio exported to {output_path}"
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def update_portfolio_config(
    target_allocation_json: str = "",
    myst_balance: float = -1,
    swap_routes_json: str = "",
    swap_config_json: str = "",
) -> str:
    """Update portfolio configuration and persist to disk.

    Args:
        target_allocation_json: JSON object mapping symbol → fraction (must sum to 1.0).
                                e.g. '{"MYST": 0.15, "POL": 0.40, "BNB": 0.45}'
        myst_balance:           Available MYST (node earnings) ready to deploy. -1 = no change.
        swap_routes_json:       JSON swap-route map. e.g.
                                '{"MYST": ["POL", "BNB"], "POL": ["MYST", "BNB"], "BNB": ["POL"]}'
        swap_config_json:       JSON swap settings. e.g.
                                '{"min_swap_usd": 50, "myst_keep_reserve": 200}'
    """
    try:
        pm = _portfolio_manager()
        target_allocation = json.loads(target_allocation_json) if target_allocation_json else None
        swap_routes = json.loads(swap_routes_json) if swap_routes_json else None
        swap_config = json.loads(swap_config_json) if swap_config_json else None
        myst_bal = myst_balance if myst_balance >= 0 else None
        pm.update_portfolio_config(
            target_allocation=target_allocation,
            myst_balance=myst_bal,
            swap_routes=swap_routes,
            swap_config=swap_config,
        )
        changes = []
        if target_allocation:
            changes.append(f"target_allocation: {target_allocation}")
        if myst_bal is not None:
            changes.append(f"myst_balance: {myst_bal}")
        if swap_routes:
            changes.append(f"swap_routes updated")
        if swap_config:
            changes.append(f"swap_config: {swap_config}")
        return "Portfolio config updated:\n" + "\n".join(f"  • {c}" for c in changes)
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def record_swap(
    from_symbol: str,
    from_amount: float,
    to_symbol: str,
    to_amount: float,
) -> str:
    """Record a completed crypto-to-crypto swap, updating holdings and myst_balance.

    Swaps FROM MYST deduct from myst_balance (your node-income pool).
    All other swaps deduct from holdings.

    Args:
        from_symbol: Asset you sold/swapped away (e.g. 'MYST', 'POL')
        from_amount: Amount of from_symbol used
        to_symbol:   Asset you received (e.g. 'BNB', 'POL')
        to_amount:   Amount of to_symbol received
    """
    try:
        _portfolio_manager().record_swap(from_symbol, from_amount, to_symbol, to_amount)
        return (
            f"Swap recorded: {from_amount} {from_symbol.upper()} → "
            f"{to_amount} {to_symbol.upper()}\n"
            f"Holdings updated. Run get_portfolio_status to see new allocation."
        )
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def calculate_tax_summary(
    purchases_json: str,
    sales_json: str,
    method: str = "FIFO",
) -> str:
    """Calculate realised gains/losses and generate a tax summary.

    Args:
        purchases_json: JSON list — [{"date":"2024-01-15","amount":0.1,"price":45000}, ...]
        sales_json:     JSON list — [{"date":"2024-06-20","amount":0.05,"price":50000}, ...]
        method:         Cost-basis method: FIFO, LIFO, or HIFO (default: FIFO)
    """
    try:
        purchases = json.loads(purchases_json)
        sales = json.loads(sales_json)
        tracker = TaxLotTracker(method=method)
        realized = tracker.calculate_realized_gains(purchases, sales)
        summary = tracker.generate_tax_summary(realized)
        return (
            f"TAX SUMMARY ({method})\n\n"
            f"Short-term gain/loss: ${summary['short_term_gain_loss']:+,.2f}\n"
            f"Long-term gain/loss:  ${summary['long_term_gain_loss']:+,.2f}\n"
            f"Total gain/loss:      ${summary['total_gain_loss']:+,.2f}\n"
            f"Transactions:         {summary['num_transactions']}\n"
        )
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def screen_swap_targets(
    source_symbol: str,
    top_n: int = 10,
    screener_config_json: str = "",
) -> str:
    """Rank candidate destination assets for a crypto-to-crypto swap using quantitative metrics.

    Builds a universe from CoinGecko, enriches each candidate with Binance market
    data, applies hard filters (200d SMA, min liquidity, max spread), then scores
    using a composite of Sortino ratio, RS vs BTC, liquidity, and diversification.

    Args:
        source_symbol:        Asset being swapped away from (e.g. 'MYST', 'POL').
                              If not listed on Binance, shown for context only.
        top_n:                Number of ranked candidates to return (default: 10).
        screener_config_json: Optional JSON to override ScreenerConfig fields, e.g.
                              '{"min_market_cap": 200000000, "max_spread_bps": 50,
                                "weights": {"sortino": 0.35, "rs_vs_btc": 0.25,
                                            "liquidity": 0.25, "diversification": 0.15}}'
    """
    try:
        if screener_config_json:
            overrides = json.loads(screener_config_json)
            cfg = ScreenerConfig(**{k: v for k, v in overrides.items()
                                    if k in ScreenerConfig.__dataclass_fields__})
        else:
            cfg = ScreenerConfig()

        result = run_screener(source_symbol, cfg, top_n=top_n)
        ranked = [c for c in result["results"] if c.get("composite_score") is not None]
        dropped = [c for c in result["results"] if c.get("composite_score") is None]
        meta = result["metadata"]

        lines = [f"SCREENER RESULTS — swap targets for {source_symbol.upper()}\n"]

        if not meta.get("source_on_binance"):
            lines.append(
                f"  ⚠  {source_symbol.upper()} is not on Binance — shown for context only\n"
            )

        lines.append(
            f"Universe: {meta['total_candidates']} candidates  |  "
            f"Passed filters: {meta['passed_hard_filters']}  |  "
            f"Filtered out: {meta['dropped_by_filters']}\n"
        )

        header = f"{'Rank':<5} {'Symbol':<10} {'Score':>6}  {'Sortino':>8} {'RS90d':>7} {'Vol24h(USD)':>14} {'Spread':>9}"
        lines += [header, "-" * len(header)]

        for c in ranked[:top_n]:
            warn = " ⚠" if c.get("liquidity_warning") else ""
            lines.append(
                f"{c.get('overall_rank', ''):< 5} "
                f"{c.get('symbol', ''):<10} "
                f"{c.get('composite_score', 0):>6.3f}  "
                f"{c.get('sortino') or 0:>8.2f} "
                f"{(c.get('rs_90d') or 0):>7.2%} "
                f"{c.get('volume_24h_binance') or 0:>14,.0f} "
                f"{c.get('spread_bps') or 0:>7.1f}bps"
                f"{warn}"
            )

        if dropped:
            lines.append(f"\n  ⛔ {len(dropped)} candidates filtered out (200d SMA / liquidity / spread):")
            for c in dropped[:5]:
                reason = c.get("filter_reason", "hard filter")
                lines.append(f"     • {c.get('symbol', '?')}: {reason}")
            if len(dropped) > 5:
                lines.append(f"     … and {len(dropped) - 5} more")

        if result.get("output_paths"):
            lines.append(f"\nCSV:  {result['output_paths'].get('csv', 'n/a')}")
            lines.append(f"JSON: {result['output_paths'].get('json', 'n/a')}")

        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Scheduler tools
# ---------------------------------------------------------------------------


@mcp.tool()
def schedule_task(
    task_type: str,
    trigger_type: str,
    trigger_config: str,
    label: str = "",
) -> str:
    """Schedule a recurring portfolio task.

    Args:
        task_type:      'daily_report' | 'sync_binance' | 'check_recommendations' | 'get_status' | 'transfer_myst' | 'harvest_myst'
        trigger_type:   'cron' | 'interval'
        trigger_config: JSON trigger parameters.
                        cron example:     {"hour": 9, "minute": 0}  (daily at 09:00 UTC)
                        interval example: {"hours": 6}              (every 6 hours)
        label:          Human-readable name for this task (optional)
    """
    try:
        config = json.loads(trigger_config)
        job_id = scheduler.add_task(task_type, trigger_type, config, label)
        return (
            f"Scheduled '{label or task_type}' — ID: {job_id}\n"
            f"Trigger: {trigger_type} {config}"
        )
    except Exception as exc:
        return f"Error scheduling task: {exc}"


@mcp.tool()
def list_scheduled_tasks() -> str:
    """List all currently active scheduled tasks."""
    try:
        tasks = scheduler.list_tasks()
        if not tasks:
            return "No scheduled tasks."
        lines = [f"SCHEDULED TASKS ({len(tasks)}):\n"]
        for t in tasks:
            lines += [
                f"ID:       {t['id']}",
                f"  Label:    {t['label']}",
                f"  Type:     {t['task_type']}",
                f"  Trigger:  {t['trigger']}",
                f"  Next run: {t['next_run']}",
                f"  Status:   {t['status']}\n",
            ]
        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def cancel_scheduled_task(job_id: str) -> str:
    """Cancel a scheduled task by its ID.

    Args:
        job_id: The ID returned by schedule_task or shown in list_scheduled_tasks
    """
    try:
        scheduler.cancel_task(job_id)
        return f"Task {job_id} cancelled."
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def trigger_task_now(task_type: str) -> str:
    """Execute a portfolio task immediately and return its output.

    Args:
        task_type: 'daily_report' | 'sync_binance' | 'check_recommendations' | 'get_status' | 'transfer_myst' | 'harvest_myst'
    """
    try:
        return scheduler.run_task_now(task_type)
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def get_task_results(limit: int = 10) -> str:
    """Return results from recent task executions.

    Args:
        limit: How many recent results to return (default: 10, max: 100)
    """
    try:
        results = scheduler.get_recent_results(min(limit, 100))
        if not results:
            return "No task results yet."
        lines = [f"RECENT RESULTS ({len(results)}):\n"]
        for r in results:
            snippet = r.get("output", "")
            if len(snippet) > 300:
                snippet = snippet[:300] + "…"
            lines += [
                f"[{r['timestamp']}] {r['task_type']}  status={r['status']}",
                f"  {snippet}\n",
            ]
        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Web3 on-chain harvest tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_web3_myst_balance() -> str:
    """Return MYST and POL balances in the on-chain automation wallet (Polygon network).

    Requires WEB3_PRIVATE_KEY and POLYGON_RPC_URL in the server environment.
    """
    try:
        from crypto_portfolio.web3_harvester import harvester_from_env
        h = harvester_from_env()
        myst = h.get_myst_balance()
        pol  = h.get_pol_balance()
        return (
            f"Automation wallet: {h.address}\n"
            f"  MYST : {myst:.6f}\n"
            f"  POL  : {pol:.6f}  (gas reserve)"
        )
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def send_web3_pol_to_exchange(amount: float = -1) -> str:
    """Send POL from the automation wallet to Binance Exchange Funding address.

    Use this to test the on-chain send step independently, or to forward POL
    that already sits in the automation wallet without needing a MYST swap first.

    Args:
        amount: POL to send. -1 (default) = send everything above 0.5 POL gas reserve.
    """
    try:
        from crypto_portfolio.web3_harvester import harvester_from_env
        h = harvester_from_env()

        pol_balance = h.get_pol_balance()
        keep_gas = 0.5
        to_send = (pol_balance - keep_gas) if amount < 0 else amount

        if to_send <= 0:
            return (
                f"Nothing to send: automation wallet has {pol_balance:.6f} POL, "
                f"keep_gas reserve is {keep_gas} POL."
            )

        result = h.send_pol_to_exchange(to_send, keep_gas=keep_gas)

        if result["status"] == "skipped":
            return f"Send skipped: {result['reason']}"

        return (
            f"Send {result['status'].upper()}\n"
            f"  POL sent:    {result.get('pol_sent', 0):.6f}\n"
            f"  Destination: {result.get('destination')}\n"
            f"  Tx hash:     {result.get('tx_hash')}\n"
            f"  Wallet balance before: {pol_balance:.6f} POL\n\n"
            f"  Binance credits Funding in ~1-2 min (1 bundle confirmation).\n"
            f"  Then call: transfer_asset_to_trade_account('POL')"
        )
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def run_myst_harvest(
    myst_keep_reserve: float = 5.0,
    min_value_usd: float = 5.0,
    slippage_pct: float = 1.0,
) -> str:
    """Run the full on-chain MYST harvest pipeline.

    Steps:
      1. Check MYST balance in automation wallet (Polygon)
      2. Swap MYST → POL via 1inch aggregator (falls back to QuickSwap)
      3. Send POL to Binance Exchange Funding deposit address
      4. (manual next step) call transfer_asset_to_trade_account then execute_binance_swap

    Requires WEB3_PRIVATE_KEY, POLYGON_RPC_URL, BINANCE_POL_DEPOSIT_ADDRESS in env.

    Args:
        myst_keep_reserve: MYST to leave in wallet (default: 5 — for node staking).
        min_value_usd:     Skip harvest if total swap value is below this USD amount.
        slippage_pct:      Max DEX slippage % (default 1.0).
    """
    try:
        from crypto_portfolio.web3_harvester import harvester_from_env
        from crypto_portfolio.api_client import CoinGeckoClient

        h = harvester_from_env()

        try:
            prices = CoinGeckoClient().fetch_prices(["MYST"])
            myst_price = prices.get("mysterium", {}).get("usd", 0.0)
        except Exception:
            myst_price = 0.0

        result = h.run_harvest(
            myst_keep_reserve=myst_keep_reserve,
            min_value_usd=min_value_usd,
            myst_price_usd=myst_price,
            slippage_pct=slippage_pct,
        )

        if result["status"] == "skipped":
            return f"Harvest skipped: {result['reason']}"

        lines = [f"Harvest {result['status'].upper()}"]
        lines.append(f"  MYST balance before: {result.get('myst_balance', 0):.4f}")
        if myst_price:
            lines.append(f"  MYST price: ${myst_price:.4f}")

        for step in result.get("steps", []):
            lines.append(f"\n  Step: {step['step']}")
            for k, v in step.items():
                if k != "step":
                    lines.append(f"    {k}: {v}")

        pol_sent = result.get("pol_sent_to_exchange", 0)
        if pol_sent:
            lines.append(f"\n  POL sent to Exchange Funding: {pol_sent:.6f}")
            lines.append(
                "  Next: call transfer_asset_to_trade_account('POL') once deposit is credited"
            )
        return "\n".join(lines)
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@mcp.resource("portfolio://config")
def portfolio_config() -> str:
    """The raw portfolio JSON configuration file."""
    try:
        return Path(PORTFOLIO_FILE).read_text()
    except FileNotFoundError:
        return json.dumps({"error": f"Portfolio file not found: {PORTFOLIO_FILE}"})


@mcp.resource("scheduler://results")
def scheduler_results() -> str:
    """All recent task execution results as JSON."""
    return json.dumps(scheduler.get_recent_results(50), indent=2, default=str)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting Crypto Portfolio MCP Server on %s:%d", MCP_HOST, MCP_PORT)
    mcp.run(transport="sse", host=MCP_HOST, port=MCP_PORT)
