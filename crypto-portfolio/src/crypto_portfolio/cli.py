"""Command-line interface for crypto portfolio manager."""

import sys
import argparse
from pathlib import Path

from .manager import PortfolioManager


def cmd_status(args):
    """Display current portfolio status."""
    pm = PortfolioManager(args.portfolio, use_binance=args.binance)
    
    if args.json:
        print(pm.get_status(format='json'))
    else:
        print(pm.get_status(format='text'))


def cmd_recommend(args):
    """Show action recommendations."""
    pm = PortfolioManager(args.portfolio, use_binance=args.binance)
    recommendations = pm.get_recommendations()
    
    if not recommendations:
        print("No recommendations at this time.")
        return
    
    print(f"\n💡 {len(recommendations)} RECOMMENDATIONS:\n")
    for i, rec in enumerate(recommendations, 1):
        priority_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
        emoji = priority_emoji.get(rec['priority'], '⚪')
        
        print(f"{i}. [{emoji} {rec['priority'].upper()}] {rec['action']} {rec['asset']}")
        print(f"   Amount: ${rec.get('amount_usd', 0):,.2f}")
        print(f"   Reason: {rec['rationale']}\n")


def cmd_report(args):
    """Generate daily report."""
    pm = PortfolioManager(args.portfolio, use_binance=args.binance)
    print(pm.get_daily_report())


def cmd_price(args):
    """Check current price for symbols."""
    from .api_client import CoinGeckoClient
    
    client = CoinGeckoClient()
    prices = client.fetch_prices(args.symbols)
    
    print("\n💰 CURRENT PRICES:\n")
    for symbol in args.symbols:
        # Try to find price data
        cg_id = symbol.lower()
        if cg_id not in prices:
            # Try mapped ID
            from .api_client import COINGECKO_ID_MAP
            cg_id = COINGECKO_ID_MAP.get(symbol.upper(), symbol.lower())
        
        if cg_id in prices:
            data = prices[cg_id]
            price = data.get('usd', 0)
            change = data.get('usd_24h_change', 0)
            
            print(f"{symbol.upper()}: ${price:,.2f} ({change:+.2f}% 24h)")
        else:
            print(f"{symbol.upper()}: Not found")


def cmd_sync(args):
    """Sync portfolio from exchange."""
    if args.source == 'binance':
        pm = PortfolioManager(args.portfolio, use_binance=True)
        balances = pm.sync_from_binance()
        
        print(f"\n✅ Synced {len(balances)} assets from Binance:")
        for bal in balances:
            print(f"  {bal['asset']}: {bal['amount']}")
    else:
        print(f"Error: Unsupported source '{args.source}'")
        sys.exit(1)


def cmd_export(args):
    """Export portfolio to CSV."""
    pm = PortfolioManager(args.portfolio, use_binance=args.binance)
    pm.export_to_csv(args.output)
    print(f"✅ Exported to {args.output}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Crypto Portfolio Manager - Track and analyze your crypto holdings'
    )
    
    parser.add_argument(
        '--portfolio',
        default='portfolio.json',
        help='Path to portfolio config file (default: portfolio.json)'
    )
    
    parser.add_argument(
        '--binance',
        action='store_true',
        help='Enable Binance API integration'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # status command
    status_parser = subparsers.add_parser('status', help='Show portfolio status')
    status_parser.add_argument('--json', action='store_true', help='Output as JSON')
    status_parser.set_defaults(func=cmd_status)
    
    # recommend command
    recommend_parser = subparsers.add_parser('recommend', help='Get recommendations')
    recommend_parser.set_defaults(func=cmd_recommend)
    
    # report command
    report_parser = subparsers.add_parser('report', help='Generate daily report')
    report_parser.set_defaults(func=cmd_report)
    
    # price command
    price_parser = subparsers.add_parser('price', help='Check current prices')
    price_parser.add_argument('symbols', nargs='+', help='Symbols to check (e.g., BTC ETH)')
    price_parser.set_defaults(func=cmd_price)
    
    # sync command
    sync_parser = subparsers.add_parser('sync', help='Sync from exchange')
    sync_parser.add_argument('--source', default='binance', help='Exchange source')
    sync_parser.set_defaults(func=cmd_sync)
    
    # export command
    export_parser = subparsers.add_parser('export', help='Export to CSV')
    export_parser.add_argument('--output', default='portfolio.csv', help='Output file')
    export_parser.set_defaults(func=cmd_export)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    try:
        args.func(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
