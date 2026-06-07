"""Command-line interface for crypto portfolio manager."""

import sys
import argparse
import logging
import json
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


def cmd_screen(args):
    """Run the swap-target screener and rank destination candidates."""
    from .screener import run_screener, ScreenerConfig

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    )

    if args.config:
        cfg = ScreenerConfig.from_json(args.config)
    else:
        cfg = ScreenerConfig()

    # CLI overrides
    if args.output_dir:
        cfg.output_dir = args.output_dir
    if args.top_n:
        cfg.top_n = args.top_n
    if args.cache_dir:
        cfg.cache_dir = args.cache_dir

    cfg = ScreenerConfig.from_env(base=cfg)

    print(f"\n🔍 Screening swap targets for source: {args.source.upper()}")
    print(f"   Config: {args.config or 'defaults'}")
    print(f"   Output: {cfg.output_dir}\n")

    result = run_screener(args.source, cfg, top_n=args.top_n)

    ranked = [c for c in result['results'] if not c.get('hard_filtered')]
    dropped = [c for c in result['results'] if c.get('hard_filtered')]
    meta = result['metadata']

    if not meta.get('source_on_binance'):
        print(f"  ⚠️  {args.source.upper()} is not on Binance — used for context only\n")

    print(f"{'Rank':<5} {'Symbol':<10} {'Score':>6}  {'Sortino':>8} {'RS90d':>7} {'Vol24h':>14} {'Spread':>8} {'Liq⚠':>5}")
    print('-' * 68)
    for c in ranked[:cfg.top_n]:
        warn = '⚠' if c.get('liquidity_warning') else ''
        print(
            f"{c.get('overall_rank', ''):<5} "
            f"{c.get('symbol', ''):<10} "
            f"{c.get('composite_score', 0):>6.3f}  "
            f"{c.get('sortino') or 0:>8.2f} "
            f"{c.get('rs_90d') or 0:>7.2%} "
            f"{c.get('volume_24h_binance') or 0:>14,.0f} "
            f"{c.get('spread_bps') or 0:>7.1f}bps "
            f"{warn:>5}"
        )

    if dropped:
        print(f"\n  ⛔ {len(dropped)} candidates filtered out (200d SMA / liquidity / spread)")

    if result.get('output_paths'):
        print(f"\n  📄 CSV:  {result['output_paths']['csv']}")
        print(f"  📄 JSON: {result['output_paths']['json']}")


def cmd_swap_preview(args):
    """Preview a Binance token swap without executing it."""
    pm = PortfolioManager(args.portfolio, use_binance=True)
    preview = pm.preview_binance_swap(
        args.from_symbol,
        args.to_symbol,
        from_amount=args.amount,
        amount_usd=args.amount_usd,
        prefer_convert=not args.no_convert,
    )
    print(json.dumps(preview, indent=2, default=str))


def cmd_swap_execute(args):
    """Execute a Binance token swap when explicit confirmation is provided."""
    pm = PortfolioManager(args.portfolio, use_binance=True)
    result = pm.execute_binance_swap(
        args.from_symbol,
        args.to_symbol,
        from_amount=args.amount,
        amount_usd=args.amount_usd,
        confirm=args.confirm,
        prefer_convert=not args.no_convert,
        quote_id=args.quote_id,
    )
    print(json.dumps(result, indent=2, default=str))


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

    # screen command
    screen_parser = subparsers.add_parser(
        'screen',
        help='Rank swap-target destination assets (CoinGecko universe + Binance metrics)',
    )
    screen_parser.add_argument(
        '--source', required=True,
        help='Symbol being rotated out of (e.g. MYST). Non-Binance assets are handled gracefully.',
    )
    screen_parser.add_argument(
        '--config', default=None,
        help='Path to screener_config.json (optional; uses built-in defaults if omitted)',
    )
    screen_parser.add_argument(
        '--output-dir', dest='output_dir', default=None,
        help='Override output directory for CSV/JSON',
    )
    screen_parser.add_argument(
        '--top-n', dest='top_n', type=int, default=None,
        help='Number of ranked results to show/write (default: 20)',
    )
    screen_parser.add_argument(
        '--cache-dir', dest='cache_dir', default=None,
        help='Override kline cache directory',
    )
    screen_parser.add_argument(
        '-v', '--verbose', action='store_true',
        help='Enable debug logging',
    )
    screen_parser.set_defaults(func=cmd_screen)

    # swap-preview command
    swap_preview_parser = subparsers.add_parser(
        'swap-preview',
        help='Preview a Binance Convert/Spot token swap without placing an order',
    )
    swap_preview_parser.add_argument('--from', dest='from_symbol', required=True, help='Asset to swap from')
    swap_preview_parser.add_argument('--to', dest='to_symbol', required=True, help='Asset to receive')
    swap_preview_parser.add_argument('--amount', type=float, default=None, help='Amount of source asset')
    swap_preview_parser.add_argument('--amount-usd', type=float, default=None, help='Approximate USD value to swap')
    swap_preview_parser.add_argument('--no-convert', action='store_true', help='Skip Binance Convert and preview Spot route only')
    swap_preview_parser.set_defaults(func=cmd_swap_preview)

    # swap-execute command
    swap_execute_parser = subparsers.add_parser(
        'swap-execute',
        help='Execute a Binance token swap and record the actual fill in the portfolio',
    )
    swap_execute_parser.add_argument('--from', dest='from_symbol', required=True, help='Asset to swap from')
    swap_execute_parser.add_argument('--to', dest='to_symbol', required=True, help='Asset to receive')
    swap_execute_parser.add_argument('--amount', type=float, default=None, help='Amount of source asset')
    swap_execute_parser.add_argument('--amount-usd', type=float, default=None, help='Approximate USD value to swap')
    swap_execute_parser.add_argument('--quote-id', default=None, help='Optional Binance Convert quote ID to accept')
    swap_execute_parser.add_argument('--no-convert', action='store_true', help='Skip Binance Convert and execute Spot route only')
    swap_execute_parser.add_argument(
        '--confirm',
        action='store_true',
        help='Required for live Binance execution; omitted means preview only',
    )
    swap_execute_parser.set_defaults(func=cmd_swap_execute)

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
