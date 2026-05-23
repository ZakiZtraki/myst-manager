"""Core portfolio manager that coordinates all portfolio operations."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from .api_client import CoinGeckoClient, BinanceClient
from .analyzer import PortfolioAnalyzer
from .recommender import ActionRecommender


class PortfolioManager:
    """Main portfolio management interface."""
    
    def __init__(self, portfolio_file: str, use_binance: bool = False):
        """
        Initialize portfolio manager.
        
        Args:
            portfolio_file: Path to portfolio JSON config
            use_binance: If True, sync balances from Binance API
        """
        self.portfolio_file = Path(portfolio_file)
        self.portfolio_data = self._load_portfolio()
        
        # Initialize API clients
        self.coingecko = CoinGeckoClient()
        self.binance = BinanceClient() if use_binance else None
        
        # Initialize analyzer and recommender
        self.analyzer = PortfolioAnalyzer()
        self.recommender = ActionRecommender()
        
    def _load_portfolio(self) -> Dict:
        """Load portfolio configuration from JSON file."""
        if not self.portfolio_file.exists():
            raise FileNotFoundError(
                f"Portfolio file not found: {self.portfolio_file}\n"
                f"Create one using: cp examples/portfolio.example.json portfolio.json"
            )
        
        with open(self.portfolio_file) as f:
            return json.load(f)
    
    def _save_portfolio(self):
        """Save portfolio data back to file."""
        with open(self.portfolio_file, 'w') as f:
            json.dump(self.portfolio_data, f, indent=2)
    
    def sync_from_binance(self):
        """Sync holdings from Binance account."""
        if not self.binance:
            raise ValueError("Binance client not initialized. Set use_binance=True")
        
        balances = self.binance.get_account_balances()
        
        # Update holdings
        for balance in balances:
            symbol = balance['asset']
            amount = balance['amount']
            
            # Find or create holding
            holding = next(
                (h for h in self.portfolio_data['holdings'] if h['symbol'] == symbol),
                None
            )
            
            if holding:
                holding['amount'] = amount
            else:
                # New asset, need to set purchase price manually
                self.portfolio_data['holdings'].append({
                    'symbol': symbol,
                    'amount': amount,
                    'avg_purchase_price': 0,  # TODO: Fetch from trade history
                    'purchase_dates': []
                })
        
        self._save_portfolio()
        return balances
    
    def get_status(self, format: str = 'dict') -> Dict:
        """
        Get current portfolio status.
        
        Args:
            format: Output format ('dict', 'json', 'text')
        
        Returns:
            Portfolio status with current values and P&L
        """
        # Get symbols from holdings
        symbols = [h['symbol'] for h in self.portfolio_data['holdings']]
        
        # Fetch current prices
        prices = self.coingecko.fetch_prices(symbols)
        
        # Analyze portfolio
        analysis = self.analyzer.analyze(
            self.portfolio_data['holdings'],
            prices
        )
        
        if format == 'json':
            return json.dumps(analysis, indent=2)
        elif format == 'text':
            return self._format_status_text(analysis)
        
        return analysis
    
    def get_recommendations(self) -> List[Dict]:
        """
        Get actionable recommendations based on current portfolio state.

        Automatically activates swap mode when portfolio.json contains 'swap_routes'.
        Fetches MYST price moving averages for timing signals when swap mode is on.
        """
        analysis = self.get_status(format='dict')
        risks = self.analyzer.assess_risk(
            analysis,
            self.portfolio_data.get('target_allocation', {})
        )

        swap_routes = self.portfolio_data.get('swap_routes')
        swap_config = dict(self.portfolio_data.get('swap_config', {}))
        myst_balance = self.portfolio_data.get(
            'myst_balance',
            self.portfolio_data.get('cash_reserves', 0)
        )

        if swap_routes and myst_balance > 0:
            try:
                ma_data = self.coingecko.fetch_moving_averages('MYST')
                swap_config.update({
                    'myst_current_price': ma_data.get('current_price') or 0,
                    'myst_ma_7d': ma_data.get('ma_7d'),
                    'myst_ma_30d': ma_data.get('ma_30d'),
                })
            except Exception as exc:
                logger.warning('Could not fetch MYST moving averages: %s', exc)

        return self.recommender.generate(
            analysis,
            risks,
            self.portfolio_data.get('target_allocation', {}),
            cash_reserves=self.portfolio_data.get('cash_reserves', 0),
            myst_balance=myst_balance,
            swap_routes=swap_routes,
            swap_config=swap_config,
        )
    
    def update_portfolio_config(
        self,
        target_allocation: Optional[Dict] = None,
        myst_balance: Optional[float] = None,
        swap_routes: Optional[Dict] = None,
        swap_config: Optional[Dict] = None,
    ) -> None:
        """Update portfolio config fields and persist to disk."""
        if target_allocation is not None:
            total = sum(target_allocation.values())
            if not (0.95 <= total <= 1.05):
                raise ValueError(
                    f'target_allocation must sum to 1.0, got {total:.2f}'
                )
            self.portfolio_data['target_allocation'] = target_allocation
        if myst_balance is not None:
            self.portfolio_data['myst_balance'] = myst_balance
        if swap_routes is not None:
            self.portfolio_data['swap_routes'] = swap_routes
        if swap_config is not None:
            self.portfolio_data['swap_config'] = swap_config
        self._save_portfolio()

    def record_swap(
        self,
        from_symbol: str,
        from_amount: float,
        to_symbol: str,
        to_amount: float,
    ) -> None:
        """
        Record a completed swap, updating holdings and myst_balance accordingly.

        MYST swaps deduct from myst_balance; all other assets deduct from holdings.
        The received asset is added to (or created in) holdings.
        """
        if from_symbol.upper() == 'MYST':
            current = self.portfolio_data.get('myst_balance', 0)
            if from_amount > current + 1e-9:
                raise ValueError(
                    f'Insufficient MYST balance: have {current}, need {from_amount}'
                )
            self.portfolio_data['myst_balance'] = max(0.0, current - from_amount)
        else:
            holding = next(
                (h for h in self.portfolio_data['holdings']
                 if h['symbol'].upper() == from_symbol.upper()),
                None,
            )
            if not holding:
                raise ValueError(f'{from_symbol} not found in holdings')
            if from_amount > holding['amount'] + 1e-9:
                raise ValueError(
                    f'Insufficient {from_symbol}: have {holding["amount"]}, need {from_amount}'
                )
            holding['amount'] = max(0.0, holding['amount'] - from_amount)
            if holding['amount'] < 1e-9:
                self.portfolio_data['holdings'].remove(holding)

        to_holding = next(
            (h for h in self.portfolio_data['holdings']
             if h['symbol'].upper() == to_symbol.upper()),
            None,
        )
        if to_holding:
            to_holding['amount'] += to_amount
        else:
            self.portfolio_data['holdings'].append({
                'symbol': to_symbol.upper(),
                'amount': to_amount,
                'avg_purchase_price': 0,
                'purchase_dates': [datetime.now().strftime('%Y-%m-%d')],
            })
        self._save_portfolio()

    def get_daily_report(self) -> str:
        """Generate formatted daily portfolio report."""
        status = self.get_status(format='dict')
        recommendations = self.get_recommendations()
        
        report = f"""
╔════════════════════════════════════════════╗
║     CRYPTO PORTFOLIO REPORT                ║
║     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC               ║
╚════════════════════════════════════════════╝

💰 PORTFOLIO VALUE
   Current:    ${status['total_value']:,.2f}
   Cost Basis: ${status['total_cost']:,.2f}
   P&L:        ${status['total_pnl']:+,.2f} ({status['total_pnl_pct']:+.2f}%)

📊 POSITIONS ({len(status['positions'])})
"""
        
        for pos in status['positions']:
            report += f"""
┌──────────────────────────────────────────┐
│ {pos['symbol']:<40} │
│ Amount:     {pos['amount']:<25} │
│ Value:      ${pos['current_value']:,.2f} ({status['allocation'][pos['symbol']]:.1f}%)
│ P&L:        ${pos['pnl']:+,.2f} ({pos['pnl_pct']:+.2f}%)
│ 24h Change: {pos['daily_change']:+.2f}%
└──────────────────────────────────────────┘
"""
        
        if recommendations:
            report += f"\n💡 RECOMMENDATIONS ({len(recommendations)})\n"
            for i, rec in enumerate(recommendations[:5], 1):
                priority_emoji = {'high': '🔴', 'medium': '🟡', 'low': '🟢'}
                emoji = priority_emoji.get(rec['priority'], '⚪')
                if rec['action'] == 'SWAP' and 'from_asset' in rec:
                    summary = (
                        f"{rec.get('route', rec['from_asset'] + ' → ' + rec['asset'])}"
                        f" (~${rec.get('amount_usd', 0):,.0f})"
                    )
                else:
                    summary = f"{rec['action']} {rec['asset']}: ${rec.get('amount_usd', 0):,.2f}"
                report += f"   {i}. [{emoji} {rec['priority'].upper()}] {summary}\n"
                report += f"      {rec['rationale']}\n"
        
        return report
    
    def _format_status_text(self, analysis: Dict) -> str:
        """Format analysis dictionary as readable text."""
        text = f"Portfolio Value: ${analysis['total_value']:,.2f}\n"
        text += f"Total P&L: ${analysis['total_pnl']:+,.2f} ({analysis['total_pnl_pct']:+.2f}%)\n\n"
        
        for pos in analysis['positions']:
            text += f"{pos['symbol']}: ${pos['current_value']:,.2f} "
            text += f"({pos['pnl_pct']:+.2f}%)\n"
        
        return text
    
    def export_to_csv(self, output_file: str):
        """Export portfolio history to CSV format."""
        import csv
        from datetime import datetime
        
        status = self.get_status(format='dict')
        
        with open(output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'timestamp', 'symbol', 'amount', 'price', 'value', 
                'cost_basis', 'pnl', 'pnl_pct'
            ])
            writer.writeheader()
            
            timestamp = datetime.now().isoformat()
            for pos in status['positions']:
                writer.writerow({
                    'timestamp': timestamp,
                    'symbol': pos['symbol'],
                    'amount': pos['amount'],
                    'price': pos['current_price'],
                    'value': pos['current_value'],
                    'cost_basis': pos['cost_basis'],
                    'pnl': pos['pnl'],
                    'pnl_pct': pos['pnl_pct']
                })
