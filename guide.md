# Setup & Installation Guide

This repo contains two components:

- **`crypto-portfolio/`** — Python library + CLI for portfolio analysis
- **`mcp-server/`** — MCP server that exposes portfolio tools to Claude via SSE

---

## Prerequisites

- Python 3.11+
- Docker + Docker Compose (for the MCP server)
- A CoinGecko API account (free tier works)
- Binance API key (optional — for live balance sync)

---

## Part 1: crypto-portfolio

### Install

```bash
cd crypto-portfolio

# Install into your Python environment
pip install -r requirements.txt

# Or install as an editable package (lets you import crypto_portfolio anywhere)
pip install -e .
```

### Configure your portfolio

```bash
# For a standard cash-based portfolio:
cp examples/portfolio.example.json portfolio.json

# For a MYST node operator (swap-only, no fiat):
cp examples/portfolio.myst.example.json portfolio.json
```

Edit `portfolio.json` with your actual holdings. Key fields:

| Field | Description |
| --- | --- |
| `holdings` | List of assets with `symbol`, `amount`, `avg_purchase_price` |
| `target_allocation` | Desired % per asset (must sum to 1.0) |
| `myst_balance` | (MYST mode) Undeployed MYST earnings ready to swap |
| `swap_routes` | (MYST mode) Allowed swap pairs per asset |
| `swap_config.min_swap_usd` | Minimum swap size in USD |
| `swap_config.myst_keep_reserve` | MYST amount never to touch |

### Optional: Binance API

```bash
export BINANCE_API_KEY="your_read_only_key"
export BINANCE_API_SECRET="your_api_secret"
```

Use **read-only** keys. Never enable withdrawal permissions.

### CLI usage

```bash
# From the crypto-portfolio directory, with portfolio.json present:
python -m crypto_portfolio status
python -m crypto_portfolio recommend
python -m crypto_portfolio report
python -m crypto_portfolio price BTC ETH MYST
python -m crypto_portfolio sync --source binance
python -m crypto_portfolio export --output snapshot.csv
```

### Run tests

```bash
cd crypto-portfolio
pytest tests/
```

---

## Part 2: MCP Server

The MCP server wraps the portfolio library and exposes all tools to Claude via Server-Sent Events (SSE).

### Local (no Docker)

```bash
cd mcp-server

# Install dependencies (includes the MCP SDK and APScheduler)
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env as needed

# Set PORTFOLIO_FILE to an absolute path that exists, e.g.:
# PORTFOLIO_FILE=/path/to/portfolio.json

python server.py
```

The server listens at `http://localhost:8000/sse` by default.

### Docker (recommended for production)

The Docker build context is the **repo root** (it needs both `crypto-portfolio/` and `mcp-server/`).

```bash
# From the repo root:
cd mcp-server
cp .env.example .env
# Edit .env — set PORTFOLIO_FILE, USE_BINANCE, MCP_API_KEY, etc.

docker compose up -d
```

This creates a named volume `mcp_data` for `/data/portfolio.json`.

#### Upload your portfolio.json into the container

```bash
docker cp /path/to/your/portfolio.json mcp-server:/data/portfolio.json
```

Or place it on a host path and bind-mount instead of using the named volume.

### Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `PORTFOLIO_FILE` | `/data/portfolio.json` | Path to portfolio JSON inside the container |
| `USE_BINANCE` | `false` | Enable Binance balance sync |
| `BINANCE_API_KEY` | _(empty)_ | Required when `USE_BINANCE=true` |
| `BINANCE_API_SECRET` | _(empty)_ | Required when `USE_BINANCE=true` |
| `MCP_HOST` | `0.0.0.0` | Bind address |
| `MCP_PORT` | `8000` | Bind port |
| `MCP_API_KEY` | _(empty)_ | Optional bearer-token auth (`Authorization: Bearer <key>`) |

### HTTPS via Zoraxy reverse proxy

1. Open the Zoraxy web UI and go to **Proxy Rules → Add Proxy Rule**
2. Set the rule:
   - **Matching hostname**: `mcp.yourdomain.com`
   - **Target**: `http://127.0.0.1:8000` (or the container IP/name if Zoraxy is in the same Docker network)
3. Enable **TLS/HTTPS** and let Zoraxy issue a Let's Encrypt certificate for the subdomain
4. Under **Advanced settings** for the rule, enable **"Disable Response Buffering"** — this is required for SSE to stream correctly
5. Set the **read timeout** to at least `3600` seconds so long-lived SSE connections are not dropped

The MCP server will then be reachable at `https://mcp.yourdomain.com/sse`.

> **Note**: The `proxy-config/mcp-server.conf` file in this repo is for nginx/SWAG and is not needed with Zoraxy — all configuration is done through the Zoraxy UI.

---

## Part 3: Connect Claude to the MCP Server

In your Claude Code settings (`~/.claude/settings.json` or project `.claude/settings.json`):

```json
{
  "mcpServers": {
    "crypto-portfolio": {
      "type": "sse",
      "url": "http://localhost:8000/sse"
    }
  }
}
```

For a remote server with auth:

```json
{
  "mcpServers": {
    "crypto-portfolio": {
      "type": "sse",
      "url": "https://mcp.yourdomain.com/sse",
      "headers": {
        "Authorization": "Bearer your_mcp_api_key"
      }
    }
  }
}
```

Restart Claude Code. You should see the `crypto-portfolio` server listed in `/mcp`.

---

## Available MCP Tools

| Tool | Descripti on |
| --- | --- |
| `get_portfolio_status` | Current values, P&L, allocation |
| `get_recommendations` | Prioritised actions (BUY / SELL / SWAP / DCA) |
| `get_daily_report` | Full daily summary |
| `check_prices` | Live prices for given symbols |
| `update_portfolio_config` | Update targets, myst_balance, swap_routes |
| `record_swap` | Log a completed crypto-to-crypto swap |
| `transfer_myst_to_trade_account` | Move MYST from Binance Funding Wallet → Spot account (auto or explicit amount) |
| `sync_from_binance` | Pull live balances from Binance |
| `export_portfolio_csv` | Snapshot to CSV file |
| `calculate_tax_summary` | Realised gains via FIFO / LIFO / HIFO |
| `screen_swap_targets` | Rank destination assets by Sortino / RS / liquidity |
| `schedule_task` | Schedule recurring task (cron or interval) |
| `list_scheduled_tasks` | List active scheduled tasks |
| `cancel_scheduled_task` | Remove a scheduled task |
| `trigger_task_now` | Run a task immediately |
| `get_task_results` | Recent task execution history |

---

## MYST Node Operator Workflow

MYST node operators earn MYST tokens and rebalance entirely via crypto-to-crypto swaps (no fiat in or out). The recommended setup:

1. Copy `examples/portfolio.myst.example.json` → `portfolio.json`
2. Set `myst_balance` to your current undeployed MYST earnings
3. Configure `swap_routes` for your exchange (e.g. MYST→POL, MYST→BNB)
4. **Transfer MYST to your Spot account** — Mysterium node payouts land in the Binance Funding Wallet, not the trading account. Call `transfer_myst_to_trade_account` to move them over automatically:
   - `amount=-1` (default): transfers everything above `myst_keep_reserve`, skips if below `min_swap_usd`
   - `amount=500`: transfers exactly 500 MYST
   - Requires `USE_BINANCE=true` and a Binance API key with **"Enable Transfers between Spot and Funding Wallet"** permission
5. Ask Claude: _"What should I swap my MYST earnings into?"_
   - Claude calls `get_recommendations` → returns SWAP actions with routing
6. Execute the swap on your exchange, then call `record_swap` to update holdings
7. Use `screen_swap_targets` to discover new candidate assets ranked by risk-adjusted performance

### Automate the Funding→Spot transfer

Schedule it to run daily so MYST is always ready to trade:

```
schedule_task(
  task_type="transfer_myst",
  trigger_type="cron",
  trigger_config='{"hour": 8, "minute": 0}',
  label="Move MYST to Spot"
)
```

### Example screener config override

To screen with stricter liquidity requirements:

```python
screen_swap_targets(
  source_symbol="MYST",
  top_n=5,
  screener_config_json='{"min_market_cap": 200000000, "max_spread_bps": 50}'
)
```

---

## Integrations

### Home Assistant sensor

```yaml
sensor:
  - platform: command_line
    name: crypto_portfolio_value
    command: "python3 /path/to/crypto-portfolio/src/crypto_portfolio/cli.py status --json"
    value_template: '{{ value_json.total_value }}'
    unit_of_measurement: 'USD'
    scan_interval: 300
```

### n8n workflow

1. Schedule Trigger — daily 09:00
2. Execute Command — `python -m crypto_portfolio report --json`
3. Parse JSON — extract recommendations
4. Send Notification — Telegram / Email

### Scheduled tasks via MCP

```code
schedule_task(
  task_type="daily_report",
  trigger_type="cron",
  trigger_config='{"hour": 9, "minute": 0}',
  label="Morning report"
)
```

---

## Troubleshooting

**CoinGecko rate limit errors** — Increase the cache TTL or use a paid CoinGecko plan.

**Binance "Invalid signature"** — Confirm the API key has "Enable Reading" enabled and that your system clock is within 5 seconds of UTC.

**Missing price for an altcoin** — Check the symbol mapping in `crypto-portfolio/src/crypto_portfolio/api_client.py` and add a custom entry to `COINGECKO_ID_MAP`.

**MCP server not appearing in Claude** — Confirm the SSE URL is reachable (`curl http://localhost:8000/sse`), then restart Claude Code.

**Docker build fails** — Run `docker compose build` from the repo root (not from `mcp-server/`), since the build context is `..`.

**Portfolio file not found inside container** — Either `docker cp` your JSON to `/data/portfolio.json`, or add a bind-mount in `docker-compose.yml`:

```yaml
volumes:
  - /host/path/portfolio.json:/data/portfolio.json
```
