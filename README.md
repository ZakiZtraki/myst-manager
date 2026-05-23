# myst-manager

Self-hosted infrastructure for running a Mysterium Network node alongside a cryptocurrency portfolio tracker and a remote MCP server for Claude AI integration.

```tree
myst-manager/
├── myst-node/          Mysterium node + WireGuard VPN + SWAG reverse proxy (Docker Compose)
├── crypto-portfolio/   Python portfolio tracker (CoinGecko prices, Binance sync, tax lots)
└── mcp-server/         Remote MCP server — lets Claude manage the portfolio via SSE
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

Standalone Python package (requires Python ≥ 3.8) for tracking, analysing, and reporting on a cryptocurrency portfolio.

**Features:** real-time prices via CoinGecko, P&L and allocation analysis, rebalancing recommendations, FIFO/LIFO/HIFO tax lot tracking, Binance sync, Home Assistant / n8n / Telegram integrations.

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

MCP (Model Context Protocol) server that exposes the crypto portfolio as tools Claude can call remotely via SSE transport.

### Quick start

```bash
cd mcp-server
cp .env.example .env          # set PORTFOLIO_FILE path, optional MCP_API_KEY
docker compose up -d --build
```

The server listens on `http://0.0.0.0:8000` by default. Expose it through SWAG using `proxy-config/mcp-server.conf`.

### Connect Claude

Add to your Claude MCP configuration:

```json
{
  "mcpServers": {
    "crypto-portfolio": {
      "url": "https://mcp.<your-domain>/sse",
      "transport": "sse"
    }
  }
}
```

### Environment variables

| Variable | Default | Description |
| --- | -- | -- |
| `PORTFOLIO_FILE` | `/data/portfolio.json` | Path to portfolio JSON |
| `USE_BINANCE` | `false` | Enable Binance balance sync |
| `MCP_HOST` | `0.0.0.0` | Bind address |
| `MCP_PORT` | `8000` | Bind port |
| `MCP_API_KEY` | *(none)* | Bearer-token auth (optional) |

### Available tools

| Tool | Description |
| --- | -- |
| `get_portfolio_status` | Current values, P&L, allocation |
| `get_recommendations` | Rebalance / profit-take / DCA suggestions |
| `get_daily_report` | Full formatted daily report |
| `check_prices` | Live prices for any symbols |
| `sync_from_binance` | Pull balances from Binance |
| `export_portfolio_csv` | Export snapshot to CSV |
| `calculate_tax_summary` | FIFO/LIFO/HIFO realised gain/loss |
| `schedule_task` | Schedule a recurring task (cron or interval) |
| `list_scheduled_tasks` | View all scheduled tasks |
| `cancel_scheduled_task` | Cancel a task by ID |
| `trigger_task_now` | Run any task immediately |
| `get_task_results` | View results of recent task runs |

---

## License

MIT
