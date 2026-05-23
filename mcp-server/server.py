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
        "Use get_portfolio_status, get_recommendations, and get_daily_report "
        "for portfolio insights. Use schedule_task / list_scheduled_tasks / "
        "cancel_scheduled_task to automate recurring operations. "
        "Use trigger_task_now to run any task immediately."
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
    """Return prioritised action recommendations (rebalance, profit-taking, DCA)."""
    try:
        recs = _portfolio_manager().get_recommendations()
        if not recs:
            return "No recommendations at this time."

        emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
        lines = [f"{len(recs)} RECOMMENDATIONS:\n"]
        for i, r in enumerate(recs, 1):
            lines.append(
                f"{i}. [{emoji.get(r['priority'], '⚪')} {r['priority'].upper()}] "
                f"{r['action']} {r['asset']}"
            )
            lines.append(f"   Amount: ${r.get('amount_usd', 0):,.2f}")
            lines.append(f"   Reason: {r['rationale']}\n")
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
        task_type:      'daily_report' | 'sync_binance' | 'check_recommendations' | 'get_status'
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
        task_type: 'daily_report' | 'sync_binance' | 'check_recommendations' | 'get_status'
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
