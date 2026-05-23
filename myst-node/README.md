# myst-manager monorepo

Infrastructure and tooling for self-hosted crypto/VPN operations.

```
myst-manager/
├── myst-node/          Mysterium node + WireGuard VPN + SWAG proxy (Docker Compose)
├── crypto-portfolio/   Python portfolio tracker (CoinGecko prices, Binance sync, tax lots)
└── mcp-server/         Remote MCP server — lets Claude manage the portfolio via SSE
```

---

## myst-node

Docker Compose stack: Mysterium node, WireGuard UI, SWAG reverse proxy, Uptime Kuma, Watchtower.

```bash
cd myst-node
cp envs/.env_proxy.example envs/.env_proxy   # fill in your domain / certs
docker compose up -d
```

See `myst-node/proxy-config-samples/` for SWAG subdomain configs.

---

## crypto-portfolio

Standalone Python package to track, analyse, and report on a cryptocurrency portfolio.

```bash
cd crypto-portfolio
pip install -e .
cp examples/portfolio.example.json portfolio.json   # edit with your holdings
crypto-portfolio status
crypto-portfolio report
crypto-portfolio recommend
```

---

## mcp-server

MCP server that exposes the portfolio as tools Claude can call remotely via SSE.

### Quick start

```bash
cd mcp-server
cp .env.example .env          # fill in PORTFOLIO_FILE path, optional API key
docker compose up -d --build
```

The server listens on `http://localhost:8000`.
Expose it via SWAG using `proxy-config/mcp-server.conf`.

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

### Available tools

| Tool | Description |
|---|---|
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
