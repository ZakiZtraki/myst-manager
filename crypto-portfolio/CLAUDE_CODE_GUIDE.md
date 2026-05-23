# Getting Started with Claude Code

This file contains instructions for using Claude Code to develop and extend the crypto-portfolio-manager project.

## Initial Setup

1. **Install Claude Code** (if not already installed):

```bash
npm install -g @anthropic-ai/claude-code
```

1. **Navigate to project directory**:

```bash
cd /path/to/crypto-portfolio-export
```

1. **Install dependencies**:

```bash
pip install -r requirements.txt
```

1. **Create your portfolio config**:

```bash
cp examples/portfolio.example.json portfolio.json
# Edit portfolio.json with your holdings
```

## Using Claude Code for Development

### Quick Test Commands

```bash
# Test the CLI
python -m crypto_portfolio status

# Run tests
python tests/test_portfolio.py

# Check a price
python -m crypto_portfolio price BTC ETH
```

### Example Claude Code Tasks

**Add new exchange integration:**

```bash
claude-code "Add support for Kraken exchange API integration following the same pattern as BinanceClient in api_client.py. Include methods for fetching account balances and trade history."
```

**Implement new feature:**

```bash
claude-code "Add a volatility monitoring feature that alerts when any asset's 7-day volatility exceeds 50% annualized. Store thresholds in the portfolio config."
```

**Fix or improve code:**

```bash
claude-code "Refactor the analyzer.py module to improve performance when analyzing portfolios with 50+ assets. Add caching for expensive calculations."
```

**Add tests:**

```bash
claude-code "Create comprehensive pytest tests for the recommender.py module covering all recommendation types (rebalancing, profit-taking, DCA, loss management)."
```

**Generate documentation:**

```bash
claude-code "Generate API documentation for all public methods in the PortfolioManager class using Google-style docstrings."
```

**Add Home Assistant integration:**

```bash
claude-code "Create a complete Home Assistant custom integration that exposes portfolio value, individual asset values, and recommendations as sensors. Include installation instructions."
```

**Create Telegram bot:**

```bash
claude-code "Build a complete Telegram bot in examples/telegram_bot.py that supports commands: /portfolio, /recommend, /price <symbol>, /alerts. Use python-telegram-bot library."
```

**Optimize performance:**

```bash
claude-code "Profile the portfolio analysis code and optimize the bottlenecks. Add batch API requests where possible to reduce latency."
```

## Project Structure Overview

```tree
crypto-portfolio-export/
├── src/crypto_portfolio/     # Main package
│   ├── __init__.py           # Package exports
│   ├── manager.py            # Core PortfolioManager
│   ├── api_client.py         # CoinGecko/Binance clients
│   ├── analyzer.py           # Portfolio analysis
│   ├── recommender.py        # Action recommendations
│   ├── tax.py                # Tax lot tracking
│   ├── cli.py                # CLI interface
│   └── __main__.py           # Module entry point
├── examples/                  # Usage examples
├── tests/                     # Test files
├── README.md                  # Documentation
├── requirements.txt           # Dependencies
└── setup.py                   # Package config
```

## Best Practices for Claude Code

### 1. Be Specific

**Good:**

```bash
claude-code "Add a method to PortfolioAnalyzer that calculates the Sharpe ratio for each asset using the last 90 days of price data. Use the risk-free rate from the portfolio config."
```

**Too vague:**

```bash
claude-code "Make the analyzer better"
```

### 2. Provide Context

**Good:**

```bash
claude-code "The CoinGecko API is rate-limited to 10 calls/minute. Add intelligent batching to the fetch_prices method that groups multiple symbol requests while staying under the rate limit."
```

### 3. Reference Existing Patterns

**Good:**

```bash
claude-code "Add a CoinbaseClient following the same pattern as BinanceClient in api_client.py, including the same authentication and error handling approach."
```

### 4. Specify Testing Requirements

**Good:**

```bash
claude-code "Implement DeFi protocol integration for tracking Aave deposits. Include unit tests that mock the API responses."
```

## Common Development Tasks

### Add New Cryptocurrency Exchange

```bash
claude-code "Add support for <exchange_name> API:
1. Create a new client class in api_client.py following BinanceClient pattern
2. Implement get_account_balances() and get_trade_history() methods
3. Add authentication using environment variables
4. Include rate limiting appropriate for their API
5. Add example usage in examples/"
```

### Implement New Recommendation Type

```bash
claude-code "Add a 'STOP_LOSS' recommendation type to recommender.py that suggests selling when an asset drops below a configurable threshold percentage from its cost basis. Include the logic in _generate_loss_management()."
```

### Add Data Visualization

```bash
claude-code "Create a portfolio_charts.py module that generates matplotlib charts:
- Portfolio allocation pie chart
- Historical value line chart
- Per-asset P&L bar chart
Add a CLI command 'chart' that saves these to PNG files."
```

### Improve Error Handling

```bash
claude-code "Review all API calls in api_client.py and add comprehensive error handling with:
- Retry logic with exponential backoff
- Specific error messages for common failures (rate limits, auth errors, network issues)
- Graceful degradation when APIs are unavailable"
```

## Debugging with Claude Code

```bash
# Explain existing code
claude-code "Explain how the tax lot tracking FIFO algorithm works in tax.py"

# Debug an issue
claude-code "The portfolio status shows incorrect P&L percentages when holdings have zero cost basis. Find and fix the bug in analyzer.py"

# Review and suggest improvements
claude-code "Review the manager.py file and suggest performance optimizations and best practices improvements"
```

## Integration Examples to Build

### Home Assistant Sensor

```bash
claude-code "Create a Home Assistant REST sensor configuration that polls the portfolio status every 5 minutes and exposes total_value, total_pnl, and top 3 positions as sensor attributes"
```

### Grafana Dashboard

```bash
claude-code "Create a Python script that exports portfolio metrics to Prometheus format, including total value, per-asset values, allocation percentages, and P&L. Make it compatible with Prometheus node_exporter textfile collector."
```

### n8n Workflow Template

```bash
claude-code "Create an n8n workflow JSON that:
1. Triggers daily at 9 AM
2. Fetches portfolio status via CLI
3. Checks for high-priority recommendations
4. Sends formatted Telegram message with portfolio summary and top 3 recommendations"
```

## Tips for Success

1. **Start small**: Test basic functionality before adding complex features
2. **Use existing patterns**: Reference similar code in the project
3. **Test incrementally**: Run tests after each change
4. **Read the docs**: Check API documentation for exchanges/services
5. **Ask for explanations**: Use Claude Code to understand code before modifying

## Getting Help

If you encounter issues:

```bash
# Ask Claude Code to explain
claude-code "Explain why the Binance authentication is failing with 'Invalid signature' error"

# Ask for debugging steps
claude-code "What are the debugging steps for troubleshooting CoinGecko API rate limit errors?"

# Request documentation
claude-code "Generate a complete API reference for the PortfolioManager class with usage examples"
```

## Next Steps

After getting familiar with the project:

1. Customize portfolio.json with your holdings
2. Run basic commands to verify functionality
3. Use Claude Code to add features you need
4. Set up automations (Home Assistant, n8n, cron jobs)
5. Contribute improvements back to the project

Happy coding with Claude Code! 🚀
