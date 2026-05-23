"""Generate actionable recommendations based on portfolio state."""

from typing import Dict, List


class ActionRecommender:
    """Generate prioritized action recommendations."""
    
    def generate(
        self,
        portfolio_analysis: Dict,
        risk_assessment: List[Dict],
        target_allocation: Dict,
        cash_reserves: float = 0
    ) -> List[Dict]:
        """
        Generate actionable recommendations.
        
        Args:
            portfolio_analysis: Results from PortfolioAnalyzer.analyze()
            risk_assessment: Results from PortfolioAnalyzer.assess_risk()
            target_allocation: Target allocation percentages
            cash_reserves: Available cash for new purchases
        
        Returns:
            List of prioritized actions with rationale
        """
        recommendations = []
        
        # 1. Rebalancing recommendations
        rebalance_recs = self._generate_rebalancing(
            portfolio_analysis,
            target_allocation
        )
        recommendations.extend(rebalance_recs)
        
        # 2. Profit-taking recommendations
        profit_recs = self._generate_profit_taking(
            portfolio_analysis,
            risk_assessment
        )
        recommendations.extend(profit_recs)
        
        # 3. DCA recommendations
        if cash_reserves > 1000:
            dca_recs = self._generate_dca(
                portfolio_analysis,
                target_allocation,
                cash_reserves
            )
            recommendations.extend(dca_recs)
        
        # 4. Loss management recommendations
        loss_recs = self._generate_loss_management(
            risk_assessment
        )
        recommendations.extend(loss_recs)
        
        # Sort by priority
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        return sorted(
            recommendations,
            key=lambda x: priority_order[x['priority']]
        )
    
    def _generate_rebalancing(
        self,
        analysis: Dict,
        target_allocation: Dict
    ) -> List[Dict]:
        """Generate rebalancing recommendations."""
        recommendations = []
        total_value = analysis['total_value']
        
        for symbol, target_pct in target_allocation.items():
            current_pct = analysis['allocation'].get(symbol, 0) / 100
            drift = current_pct - target_pct
            
            # Only recommend if drift > 10%
            if abs(drift) > 0.10:
                target_value = total_value * target_pct
                current_value = total_value * current_pct
                delta_usd = target_value - current_value
                
                action = 'BUY' if delta_usd > 0 else 'SELL'
                
                # Determine priority based on drift magnitude
                if abs(drift) > 0.20:
                    priority = 'high'
                elif abs(drift) > 0.15:
                    priority = 'medium'
                else:
                    priority = 'low'
                
                recommendations.append({
                    'priority': priority,
                    'action': action,
                    'asset': symbol,
                    'amount_usd': abs(delta_usd),
                    'current_pct': current_pct * 100,
                    'target_pct': target_pct * 100,
                    'rationale': f'Rebalance {symbol} from {current_pct*100:.1f}% to {target_pct*100:.1f}%',
                    'type': 'REBALANCE'
                })
        
        return recommendations
    
    def _generate_profit_taking(
        self,
        analysis: Dict,
        risks: List[Dict]
    ) -> List[Dict]:
        """Generate profit-taking recommendations."""
        recommendations = []
        
        for risk in risks:
            if risk['type'] in ['LARGE_UNREALIZED_GAIN', 'MODERATE_UNREALIZED_GAIN']:
                pos = next(
                    (p for p in analysis['positions'] if p['symbol'] == risk['asset']),
                    None
                )
                
                if not pos:
                    continue
                
                # Suggest taking 25-50% of position based on gain size
                if risk['gain_pct'] > 200:
                    take_profit_pct = 0.50  # 50% for huge gains
                    priority = 'high'
                elif risk['gain_pct'] > 100:
                    take_profit_pct = 0.33  # 33% for large gains
                    priority = 'medium'
                else:
                    take_profit_pct = 0.25  # 25% for moderate gains
                    priority = 'low'
                
                take_profit_amount = pos['amount'] * take_profit_pct
                take_profit_usd = pos['current_value'] * take_profit_pct
                
                recommendations.append({
                    'priority': priority,
                    'action': 'SELL',
                    'asset': risk['asset'],
                    'amount': take_profit_amount,
                    'amount_usd': take_profit_usd,
                    'percentage': take_profit_pct * 100,
                    'rationale': f'Take profits on {risk["asset"]} (+{risk["gain_pct"]:.0f}% gain)',
                    'type': 'PROFIT_TAKING'
                })
        
        return recommendations
    
    def _generate_dca(
        self,
        analysis: Dict,
        target_allocation: Dict,
        cash_reserves: float
    ) -> List[Dict]:
        """Generate dollar-cost averaging recommendations."""
        recommendations = []
        
        # Find underweight positions
        for symbol, target_pct in target_allocation.items():
            current_pct = analysis['allocation'].get(symbol, 0) / 100
            
            if current_pct < target_pct - 0.05:  # 5% underweight
                # Suggest DCA with 20-25% of cash reserves
                dca_amount = min(cash_reserves * 0.25, 2000)
                
                if dca_amount >= 100:  # Minimum $100 for DCA
                    recommendations.append({
                        'priority': 'low',
                        'action': 'BUY',
                        'asset': symbol,
                        'amount_usd': dca_amount,
                        'rationale': f'DCA into underweight {symbol} position (current: {current_pct*100:.1f}%, target: {target_pct*100:.1f}%)',
                        'type': 'DCA'
                    })
        
        return recommendations
    
    def _generate_loss_management(
        self,
        risks: List[Dict]
    ) -> List[Dict]:
        """Generate recommendations for managing losses."""
        recommendations = []
        
        for risk in risks:
            if risk['type'] == 'LARGE_UNREALIZED_LOSS':
                # Suggest reviewing the investment thesis
                recommendations.append({
                    'priority': 'medium',
                    'action': 'REVIEW',
                    'asset': risk['asset'],
                    'loss_pct': risk['loss_pct'],
                    'rationale': f'{risk["asset"]} down {risk["loss_pct"]:.1f}% - review fundamentals and consider tax-loss harvesting',
                    'type': 'LOSS_MANAGEMENT'
                })
        
        return recommendations
