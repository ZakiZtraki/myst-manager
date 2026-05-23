# Crypto Portfolio Manager

Python-based cryptocurrency portfolio monitoring, analysis, and recommendation system with real-time price tracking via CoinGecko API.

## Features

- **Real-time Price Monitoring**: Fetch current prices and market data
- **Portfolio Analysis**: Calculate P&L, allocation, and performance metrics
- **Risk Assessment**: Detect concentration risk and allocation drift
- **Action Recommendations**: Automated rebalancing, profit-taking, and DCA suggestions
- **Tax Lot Tracking**: FIFO/LIFO/HIFO cost basis calculations
- **Multiple Integrations**: Home Assistant, n8n, Telegram Bot support
- **Binance API Support**: Direct exchange balance fetching

## Quick Start

### Installation

```bash
# Clone or download this project
cd crypto-portfolio-export

# Install dependencies
pip install -r requirements.txt

# Copy example config
cp examples/portfolio.example.json portfolio.json

# Edit portfolio.json with your holdings
nano portfolio.json
```

### Basic Usage

```python
from crypto_portfolio import PortfolioManager

# Initialize manager
pm = PortfolioManager('portfolio.json')

# Get current portfolio status
status = pm.get_status()
print(status)

# Get recommendations
recommendations = pm.get_recommendations()
for rec in recommendations:
    print(f"{rec['action']} {rec['asset']}: ${rec['amount_usd']:.2f}")
```

### Command Line Interface

```bash
# View portfolio status
python -m crypto_portfolio status

# Get recommendations
python -m crypto_portfolio recommend

# Daily report
python -m crypto_portfolio report

# Check specific coin price
python -m crypto_portfolio price BTC ETH

# Export to CSV
python -m crypto_portfolio export --output portfolio_history.csv
```

## Configuration

### Portfolio Configuration (`portfolio.json`)

```json
{
  "holdings": [
    {
      "symbol": "BTC",
      "amount": 0.5,
      "avg_purchase_price": 45000,
      "purchase_dates": ["2024-01-15", "2024-03-20"]
    }
  ],
  "cash_reserves": 5000,
  "target_allocation": {
    "BTC": 0.50,
    "ETH": 0.30,
    "stablecoins": 0.20
  }
}
```

### Binance API Integration (Optional)

```bash
# Set environment variables
export BINANCE_API_KEY="your_read_only_api_key"
export BINANCE_API_SECRET="your_api_secret"

# Sync portfolio from Binance
python -m crypto_portfolio sync --source binance
```

## Project Structure

```
crypto-portfolio-export/
├── src/crypto_portfolio/
│   ├── __init__.py
│   ├── manager.py          # Core portfolio manager
│   ├── api_client.py       # CoinGecko/Binance API clients
│   ├── analyzer.py         # Portfolio analysis
│   ├── recommender.py      # Action recommendations
│   ├── tax.py              # Tax lot tracking
│   └── cli.py              # Command-line interface
├── examples/
│   ├── portfolio.example.json
│   ├── basic_usage.py
│   ├── telegram_bot.py
│   └── n8n_integration.py
├── tests/
│   └── test_portfolio.py
├── requirements.txt
├── setup.py
└── README.md
```

## Integration Examples

### Home Assistant

```yaml
# configuration.yaml
sensor:
  - platform: command_line
    name: crypto_portfolio_value
    command: "python3 /path/to/crypto-portfolio-export/src/crypto_portfolio/cli.py status --json"
    value_template: '{{ value_json.total_value }}'
    unit_of_measurement: 'USD'
    scan_interval: 300
```

### n8n Workflow

1. **Schedule Trigger**: Daily at 9:00 AM
2. **Execute Command**: `python -m crypto_portfolio report --json`
3. **Parse JSON**: Extract recommendations
4. **Send Notification**: Telegram/Email with action items

### Telegram Bot

```python
from telegram.ext import Application, CommandHandler
from crypto_portfolio import PortfolioManager

pm = PortfolioManager('portfolio.json')

async def portfolio_cmd(update, context):
    status = pm.get_status()
    await update.message.reply_text(status['formatted_report'])

app = Application.builder().token("YOUR_BOT_TOKEN").build()
app.add_handler(CommandHandler("portfolio", portfolio_cmd))
app.run_polling()
```

## API Rate Limits

- **CoinGecko Free**: 10-30 calls/minute
- **Binance**: 1200 requests/minute
- Built-in rate limiting and caching included

## Development

### Running Tests

```bash
pytest tests/
```

### Adding New Features

```bash
# Use Claude Code for development
claude-code "Add support for tracking staking rewards in the portfolio"
```

## Security Notes

- **Never commit API keys** to version control
- Use read-only API keys when possible
- Store sensitive data in environment variables
- Portfolio files contain financial data - keep private

## License

MIT License - See LICENSE file for details

## Contributing

Contributions welcome! Use Claude Code to help implement features:

```bash
claude-code "Implement Kraken exchange integration following the Binance pattern"
```

## Troubleshooting

**Issue**: CoinGecko rate limit errors  
**Solution**: Increase cache TTL in config or use paid CoinGecko API

**Issue**: Binance API authentication fails  
**Solution**: Verify API key permissions (need "Enable Reading" only)

**Issue**: Missing price data for altcoins  
**Solution**: Check symbol mapping in `api_client.py`, add custom mappings

## Roadmap

- [ ] Support for additional exchanges (Kraken, Coinbase)
- [ ] Historical performance charts
- [ ] DeFi protocol integration (Aave, Uniswap)
- [ ] Multi-currency support (EUR, GBP)
- [ ] Mobile app companion
- [ ] Advanced tax reporting (Form 8949 generation)
