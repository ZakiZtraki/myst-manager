"""Portfolio analysis and risk assessment."""

from typing import Dict, List


class PortfolioAnalyzer:
    """Analyze portfolio metrics and assess risks."""
    
    def analyze(self, holdings: List[Dict], current_prices: Dict) -> Dict:
        """
        Comprehensive portfolio analysis.
        
        Args:
            holdings: List of holding dictionaries
            current_prices: Price data from CoinGecko
        
        Returns:
            Analysis with value, P&L, allocation, and metrics
        """
        results = {
            'total_value': 0,
            'total_cost': 0,
            'positions': [],
            'allocation': {},
            'risk_metrics': {}
        }
        
        # Map symbol to CoinGecko ID (kept in sync with api_client.COINGECKO_ID_MAP)
        from .api_client import COINGECKO_ID_MAP as symbol_map
        
        for holding in holdings:
            symbol = holding['symbol']
            amount = holding['amount']
            avg_price = holding.get('avg_purchase_price', 0)
            
            # Get CoinGecko ID
            cg_id = symbol_map.get(symbol, symbol.lower())
            
            # Get current price
            price_data = current_prices.get(cg_id, {})
            current_price = price_data.get('usd', 0)
            
            if current_price == 0:
                # Try without mapping
                current_price = current_prices.get(symbol.lower(), {}).get('usd', 0)
            
            # Calculate metrics
            current_value = amount * current_price
            cost_basis = amount * avg_price
            
            pnl = current_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0
            
            daily_change = price_data.get('usd_24h_change', 0)
            
            position = {
                'symbol': symbol,
                'amount': amount,
                'current_price': current_price,
                'current_value': current_value,
                'cost_basis': cost_basis,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
                'daily_change': daily_change,
                'market_cap': price_data.get('usd_market_cap', 0)
            }
            
            results['positions'].append(position)
            results['total_value'] += current_value
            results['total_cost'] += cost_basis
        
        # Calculate allocation percentages
        if results['total_value'] > 0:
            for pos in results['positions']:
                results['allocation'][pos['symbol']] = (
                    pos['current_value'] / results['total_value'] * 100
                )
        
        # Overall portfolio metrics
        results['total_pnl'] = results['total_value'] - results['total_cost']
        results['total_pnl_pct'] = (
            results['total_pnl'] / results['total_cost'] * 100
            if results['total_cost'] > 0 else 0
        )
        
        # Calculate portfolio-wide daily change
        total_daily_change = sum(
            (pos['current_value'] * (pos['daily_change'] or 0) / 100)
            for pos in results['positions']
        )
        results['portfolio_daily_change'] = (
            total_daily_change / results['total_value'] * 100
            if results['total_value'] > 0 else 0
        )
        
        return results
    
    def assess_risk(self, portfolio_analysis: Dict, target_allocation: Dict) -> List[Dict]:
        """
        Evaluate portfolio risk and concentration.
        
        Args:
            portfolio_analysis: Results from analyze()
            target_allocation: Target allocation percentages
        
        Returns:
            List of risk warnings sorted by severity
        """
        risks = []
        
        # Check concentration risk
        for symbol, pct in portfolio_analysis['allocation'].items():
            if pct > 50:
                risks.append({
                    'type': 'HIGH_CONCENTRATION',
                    'severity': 'high',
                    'asset': symbol,
                    'value': pct,
                    'message': f'{symbol} represents {pct:.1f}% of portfolio (>50% threshold)'
                })
            elif pct > 30:
                risks.append({
                    'type': 'MODERATE_CONCENTRATION',
                    'severity': 'medium',
                    'asset': symbol,
                    'value': pct,
                    'message': f'{symbol} represents {pct:.1f}% of portfolio (>30%)'
                })
        
        # Check allocation drift from targets
        for symbol, target_pct in target_allocation.items():
            current_pct = portfolio_analysis['allocation'].get(symbol, 0)
            drift = abs(current_pct - target_pct * 100)
            
            if drift > 15:
                risks.append({
                    'type': 'ALLOCATION_DRIFT',
                    'severity': 'high',
                    'asset': symbol,
                    'drift': drift,
                    'message': f'{symbol} allocation drifted {drift:.1f}% from target ({target_pct*100:.0f}%)'
                })
            elif drift > 10:
                risks.append({
                    'type': 'ALLOCATION_DRIFT',
                    'severity': 'medium',
                    'asset': symbol,
                    'drift': drift,
                    'message': f'{symbol} allocation drifted {drift:.1f}% from target'
                })
        
        # Check for large unrealized gains
        for pos in portfolio_analysis['positions']:
            if pos['pnl_pct'] > 100:
                risks.append({
                    'type': 'LARGE_UNREALIZED_GAIN',
                    'severity': 'low',
                    'asset': pos['symbol'],
                    'gain_pct': pos['pnl_pct'],
                    'message': f'{pos["symbol"]} up {pos["pnl_pct"]:.1f}% - consider taking profits'
                })
            elif pos['pnl_pct'] > 50:
                risks.append({
                    'type': 'MODERATE_UNREALIZED_GAIN',
                    'severity': 'low',
                    'asset': pos['symbol'],
                    'gain_pct': pos['pnl_pct'],
                    'message': f'{pos["symbol"]} up {pos["pnl_pct"]:.1f}%'
                })
        
        # Check for large unrealized losses
        for pos in portfolio_analysis['positions']:
            if pos['pnl_pct'] < -50:
                risks.append({
                    'type': 'LARGE_UNREALIZED_LOSS',
                    'severity': 'high',
                    'asset': pos['symbol'],
                    'loss_pct': pos['pnl_pct'],
                    'message': f'{pos["symbol"]} down {pos["pnl_pct"]:.1f}% - review investment thesis'
                })
            elif pos['pnl_pct'] < -30:
                risks.append({
                    'type': 'MODERATE_UNREALIZED_LOSS',
                    'severity': 'medium',
                    'asset': pos['symbol'],
                    'loss_pct': pos['pnl_pct'],
                    'message': f'{pos["symbol"]} down {pos["pnl_pct"]:.1f}%'
                })
        
        # Sort by severity
        severity_order = {'high': 0, 'medium': 1, 'low': 2}
        return sorted(risks, key=lambda x: severity_order[x['severity']])
    
    def calculate_volatility(self, historical_prices: List[Dict]) -> float:
        """
        Calculate annualized volatility from historical prices.
        
        Args:
            historical_prices: List of price dictionaries with 'price' key
        
        Returns:
            Annual volatility percentage
        """
        import numpy as np
        
        if len(historical_prices) < 2:
            return 0
        
        prices = [p['price'] for p in historical_prices]
        returns = np.diff(prices) / prices[:-1]
        
        # Daily volatility
        daily_vol = np.std(returns)
        
        # Annualized (365 days)
        annual_vol = daily_vol * np.sqrt(365)
        
        return annual_vol * 100
