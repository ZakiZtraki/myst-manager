# myst-manager

Self-hosted infrastructure for running a Mysterium Network node alongside a cryptocurrency portfolio tracker and a remote MCP server for Claude AI integration.

```text
myst-manager/
├── myst-node/          Mysterium node + WireGuard VPN + SWAG reverse proxy (Docker Compose)
├── crypto-portfolio/   Python portfolio tracker (CoinGecko prices, Binance sync, on-chain harvesting)
└── mcp-server/         Remote MCP server — lets Claude manage the portfolio via Streamable HTTP
```

---

## myst-node

Docker Compose stack running:

- **Mysterium node** — earn MYST by providing VPN bandwidth
- **WireGuard UI** (`wg-gen-web`) — manage VPN peers via browser
- **SWAG** — reverse proxy with automatic Let's Encrypt TLS
- **Uptime Kuma** — service monitoring dashboard
- **Heimdall** — bookmark/app dashboard
- **Watchtower** — automatic container image updates

### Quick start

```bash
cd myst-node
cp envs/.env_proxy.example envs/.env_proxy   # fill in domain, email, certs
docker compose up -d
```

The node listens on UDP `59850–60000`. The management API is bound to `$WG_IFACE_IP:4449` (not publicly exposed — access via VPN or SSH tunnel). SWAG proxies HTTPS on port 443.

See `myst-node/proxy-config-samples/` for SWAG subdomain configuration examples.

---

## crypto-portfolio

Standalone Python package (requires Python ≥ 3.11) for tracking, analysing, and reporting on a cryptocurrency portfolio.

**Features:** real-time prices via CoinGecko, P&L and allocation analysis, rebalancing recommendations, FIFO/LIFO/HIFO tax lot tracking, Binance Spot + Funding sync, Binance Convert swaps, on-chain MYST→POL harvesting via 1inch/QuickSwap, Home Assistant / n8n / Telegram integrations.

### Quick start

```bash
cd crypto-portfolio
pip install -e .
cp examples/portfolio.example.json portfolio.json   # edit with your holdings
crypto-portfolio status
crypto-portfolio report
crypto-portfolio recommend
```

### Optional Binance sync

```bash
export BINANCE_API_KEY="your_read_only_key"
export BINANCE_API_SECRET="your_secret"
crypto-portfolio sync --source binance
```

See [`crypto-portfolio/README.md`](crypto-portfolio/README.md) for full CLI reference, configuration schema, and integration examples.

---

## mcp-server

MCP (Model Context Protocol) server that exposes the crypto portfolio as tools Claude can call remotely via **Streamable HTTP** transport.

### Quick start

```bash
cd mcp-server
cp .env.example .env          # set PORTFOLIO_FILE path, optional API keys
docker compose up -d --build
```

The server listens on `http://0.0.0.0:8000/mcp` by default.

### Connect Claude

**Claude Code** (`~/.claude/settings.json`):

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

**Claude Desktop App** (`%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "crypto-portfolio": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

### Environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `PORTFOLIO_FILE` | `/data/portfolio.json` | Path to portfolio JSON |
| `USE_BINANCE` | `false` | Enable Binance balance sync |
| `MCP_HOST` | `0.0.0.0` | Bind address |
| `MCP_PORT` | `8000` | Bind port |
| `MCP_API_KEY` | *(none)* | Bearer-token auth (optional) |
| `WEB3_PRIVATE_KEY` | *(none)* | Automation wallet private key (hex) |
| `POLYGON_RPC_URL` | `https://polygon-rpc.com` | Polygon JSON-RPC endpoint |
| `BINANCE_POL_DEPOSIT_ADDRESS` | *(none)* | Binance Funding deposit address for POL |
| `ONEINCH_API_KEY` | *(none)* | 1inch API key for better DEX routing (optional) |

### Available tools

#### Portfolio & Analysis

| Tool | Description |
| --- | --- |
| `get_portfolio_status` | Current values, P&L, allocation |
| `get_recommendations` | Rebalance / profit-take / DCA suggestions |
| `get_daily_report` | Full formatted daily report |
| `check_prices` | Live prices for any symbols |
| `update_portfolio_config` | Update targets, MYST balance, swap routes |
| `record_swap` | Log a completed swap and update holdings |
| `sync_from_binance` | Pull balances from Binance Spot + Funding |
| `export_portfolio_csv` | Export snapshot to CSV |
| `calculate_tax_summary` | FIFO/LIFO/HIFO realised gain/loss |
| `screen_swap_targets` | Rank swap destinations by Sortino/RS/liquidity |

#### Binance Transfers & Swaps

| Tool | Description |
| --- | --- |
| `transfer_asset_to_trade_account` | Move any asset from Binance Funding → Spot |
| `preview_binance_convert` | Get a live Binance Convert quote (no execution) |
| `execute_binance_convert` | Execute a Binance Convert swap (Spot → Spot) |

#### On-chain Web3 (Polygon)

| Tool | Description |
| --- | --- |
| `get_web3_myst_balance` | MYST + POL balances in the automation wallet |
| `run_myst_harvest` | Full pipeline: MYST → POL → send to Binance |
| `send_web3_pol_to_exchange` | Send POL from automation wallet to Binance |

#### Scheduled Tasks

| Tool | Description |
| --- | --- |
| `schedule_task` | Schedule a recurring task (cron or interval) |
| `list_scheduled_tasks` | View all scheduled tasks |
| `cancel_scheduled_task` | Cancel a task by ID |
| `trigger_task_now` | Run any task immediately |
| `get_task_results` | View results of recent task runs |

See [`guide.md`](guide.md) for the full setup guide including the MYST node operator cash-out pipeline.

---

## License

MIT
