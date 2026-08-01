# Setup & Installation Guide

This repo contains two components:

- **`crypto-portfolio/`** — Python library + CLI for portfolio analysis
- **`mcp-server/`** — MCP server that exposes portfolio tools to Claude via Streamable HTTP

---

## Prerequisites

- Python 3.11+
- Docker + Docker Compose (for the MCP server)
- A CoinGecko API account (free tier works)
- Binance API key (optional — for live balance sync)
- Web3 automation wallet private key (optional — for on-chain MYST harvesting)

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

Edit `portfolio.json` with your actual wallet balances. Key fields:

| Field | Description |
| --- | --- |
| `wallets.binance.web3.assets` | Assets and amounts in the Binance Web3 wallet |
| `wallets.binance.funding.assets` | Assets and amounts in the Binance Funding wallet |
| `wallets.binance.spot.assets` | Assets and amounts in the Binance Spot wallet |
| `target_allocation` | Desired % per asset (must sum to 1.0) |
| `swap_routes` | (MYST mode) Allowed swap pairs per asset |
| `swap_config.min_swap_usd` | Minimum swap size in USD |
| `swap_config.myst_keep_reserve` | MYST amount never to touch (node staking reserve) |

The portfolio manager aggregates wallet assets into flat holdings internally for
analysis, recommendations, and reports.

### Optional: Binance API

```bash
export BINANCE_API_KEY="your_read_only_key"
export BINANCE_API_SECRET="your_api_secret"
```

Use **read-only** keys unless you also need transfers (requires "Enable Transfers between Spot and Funding Wallet" permission).

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

The MCP server wraps the portfolio library and exposes all tools to Claude via **Streamable HTTP** (the current MCP transport standard).

### Local (no Docker)

```bash
cd mcp-server

# Install dependencies (includes the MCP SDK, APScheduler, web3)
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env as needed

# Set PORTFOLIO_FILE to an absolute path that exists, e.g.:
# PORTFOLIO_FILE=/path/to/portfolio.json

python server.py
```

The server listens at `http://localhost:8000/mcp` by default.

### Docker (recommended for production)

The Docker build context is the **repo root** (it needs both `crypto-portfolio/` and `mcp-server/`).

```bash
# From the repo root:
cd mcp-server
cp .env.example .env
# Edit .env — set PORTFOLIO_FILE, USE_BINANCE, API keys, etc.

docker compose up -d
```

The compose file bind-mounts your `portfolio.json` directly from the host path.

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
| `WEB3_PRIVATE_KEY` | _(empty)_ | Private key of the on-chain automation wallet (hex, no 0x prefix) |
| `POLYGON_RPC_URL` | `https://polygon-rpc.com` | Polygon JSON-RPC endpoint |
| `BINANCE_POL_DEPOSIT_ADDRESS` | _(empty)_ | Your Binance **Funding** wallet deposit address for POL (Polygon network) |
| `ONEINCH_API_KEY` | _(empty)_ | Optional 1inch Developer Portal key for better DEX routing |

### HTTPS via Zoraxy reverse proxy

1. Open the Zoraxy web UI and go to **Proxy Rules → Add Proxy Rule**
2. Set the rule:
   - **Matching hostname**: `mcp.yourdomain.com`
   - **Target**: `http://127.0.0.1:8000` (or the container IP/name if Zoraxy is in the same Docker network)
3. Enable **TLS/HTTPS** and let Zoraxy issue a Let's Encrypt certificate for the subdomain
4. Under **Advanced settings** for the rule, enable **"Disable Response Buffering"**
5. Set the **read timeout** to at least `3600` seconds

The MCP server will then be reachable at `https://mcp.yourdomain.com/mcp`.

---

## Part 3: Connect Claude to the MCP Server

### Claude Code (`~/.claude/settings.json`)

```json
{
  "mcpServers": {
    "crypto-portfolio": {
      "type": "streamable-http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

For a remote server with auth:

```json
{
  "mcpServers": {
    "crypto-portfolio": {
      "type": "streamable-http",
      "url": "https://mcp.yourdomain.com/mcp",
      "headers": {
        "Authorization": "Bearer your_mcp_api_key"
      }
    }
  }
}
```

Restart Claude Code. You should see the `crypto-portfolio` server listed in `/mcp`.

### Claude Desktop App (`claude_desktop_config.json`)

On **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`  
On **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "crypto-portfolio": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://localhost:8000/mcp"
      ]
    }
  }
}
```

Restart the Claude desktop app after saving. The MCP container must be running for the connection to succeed.

---

## Available MCP Tools

### Portfolio & Analysis

| Tool | Description |
| --- | --- |
| `get_portfolio_status` | Current values, P&L, allocation |
| `get_recommendations` | Prioritised actions (SWAP / DCA / profit-taking) |
| `get_daily_report` | Full daily summary |
| `check_prices` | Live prices for given symbols |
| `update_portfolio_config` | Update targets, MYST balance, swap_routes |
| `record_swap` | Log a completed crypto-to-crypto swap and update holdings |
| `sync_from_binance` | Pull live balances from Binance Spot + Funding wallets |
| `export_portfolio_csv` | Snapshot to CSV file |
| `calculate_tax_summary` | Realised gains via FIFO / LIFO / HIFO |
| `screen_swap_targets` | Rank destination assets by Sortino / RS / liquidity |

### Binance Transfers & Swaps

| Tool | Description |
| --- | --- |
| `transfer_asset_to_trade_account` | Move any asset from Binance Funding → Spot (POL, TRX, BNB, etc.) |
| `preview_binance_convert` | Get a live Binance Convert quote without executing |
| `execute_binance_convert` | Execute a Binance Convert swap (Spot → Spot) |

### On-chain Web3 (Polygon)

| Tool | Description |
| --- | --- |
| `get_web3_myst_balance` | MYST + POL balances in the automation wallet |
| `run_myst_harvest` | Full pipeline: MYST → POL (1inch/QuickSwap) → send to Binance Exchange |
| `send_web3_pol_to_exchange` | Send POL from automation wallet to Binance Funding deposit address |

### Scheduled Tasks

| Tool | Description |
| --- | --- |
| `schedule_task` | Schedule a recurring task (`cron` or `interval`) |
| `list_scheduled_tasks` | List active scheduled tasks |
| `cancel_scheduled_task` | Remove a scheduled task |
| `trigger_task_now` | Run a task immediately |
| `get_task_results` | Recent task execution history |

**Valid task types**: `daily_report`, `sync_binance`, `check_recommendations`, `get_status`, `transfer_myst`, `harvest_myst`

---

## MYST Node Operator Workflow

MYST is **not listed on Binance Exchange** — it cannot be deposited to a Binance Spot wallet directly. Node operators are paid in Polygon MYST and must convert on-chain first.

### Correct cash-out pipeline

```
Mysterium node (Polygon)
  └─ earn MYST → automation wallet
       └─ run_myst_harvest (MCP tool)
            ├─ swap MYST → POL via 1inch / QuickSwap (on-chain)
            └─ send POL → Binance Funding deposit address (on-chain)
                  └─ transfer_asset_to_trade_account('POL')
                        └─ execute_binance_convert('POL', 'BNB', ...)
                              └─ record_swap(...)
```

### Step-by-step

1. Copy `examples/portfolio.myst.example.json` → `portfolio.json`
2. Set Web3 env vars in your `.env`:

   ```dotenv
   WEB3_PRIVATE_KEY=your_hex_private_key
   POLYGON_RPC_URL=https://polygon-rpc.com
   BINANCE_POL_DEPOSIT_ADDRESS=0xYourBinanceFundingDepositAddress
   ONEINCH_API_KEY=optional_but_recommended
   ```

3. Check your automation wallet: call `get_web3_myst_balance`
4. Harvest when ready: call `run_myst_harvest` (skips automatically if below `min_value_usd`)
5. Wait ~1–2 minutes for Binance to credit the POL deposit
6. Move POL to Spot: `transfer_asset_to_trade_account('POL')`
7. Preview a swap: `preview_binance_convert('POL', 'BNB', amount)`
8. Execute: `execute_binance_convert('POL', 'BNB', amount)`
9. Record it: `record_swap('POL', amount, 'BNB', received)`

### Automate the harvest

Schedule it to run daily so MYST is automatically converted and forwarded:

```python
schedule_task(
  task_type="harvest_myst",
  trigger_type="cron",
  trigger_config='{"hour": 8, "minute": 0}',
  label="Daily MYST harvest"
)
```

### Example screener config override

To screen with stricter liquidity requirements:

```python
screen_swap_targets(
  source_symbol="POL",
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

```python
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

**MCP server not appearing in Claude** — Confirm the server is reachable (`curl http://localhost:8000/mcp`), then restart Claude Code / the desktop app.

**Docker build fails** — Run `docker compose build` from the `mcp-server/` directory (the build context is set to `..` in the Dockerfile, so it resolves the repo root correctly).

**Portfolio file not found inside container** — Check the `volumes` bind-mount in `docker-compose.yml`; the host path must exist and point to a valid `portfolio.json`.

**Web3 harvest fails with "insufficient funds"** — The automation wallet needs a small POL balance (~0.5 POL) to pay Polygon gas. Fund it directly from Binance or another source.

**1inch API returns 400** — Add your `ONEINCH_API_KEY` (free at portal.1inch.dev); the fallback to QuickSwap still works without it but may give slightly worse rates.
