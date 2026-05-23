"""Basic usage example for crypto portfolio manager."""

from crypto_portfolio import PortfolioManager

# Initialize with portfolio config file
pm = PortfolioManager('portfolio.json')

# Get current portfolio status
print("=" * 50)
print("PORTFOLIO STATUS")
print("=" * 50)
status = pm.get_status(format='dict')

print(f"\nTotal Value: ${status['total_value']:,.2f}")
print(f"Total P&L: ${status['total_pnl']:+,.2f} ({status['total_pnl_pct']:+.2f}%)")

print("\nPositions:")
for pos in status['positions']:
    print(f"  {pos['symbol']}: ${pos['current_value']:,.2f} ({pos['pnl_pct']:+.2f}%)")

# Get recommendations
print("\n" + "=" * 50)
print("RECOMMENDATIONS")
print("=" * 50)
recommendations = pm.get_recommendations()

if recommendations:
    for rec in recommendations[:5]:  # Top 5
        print(f"\n[{rec['priority'].upper()}] {rec['action']} {rec['asset']}")
        print(f"  Amount: ${rec.get('amount_usd', 0):,.2f}")
        print(f"  Reason: {rec['rationale']}")
else:
    print("\nNo recommendations at this time.")

# Generate full daily report
print("\n" + "=" * 50)
print("DAILY REPORT")
print("=" * 50)
print(pm.get_daily_report())
