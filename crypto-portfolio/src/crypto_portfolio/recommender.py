"""Generate actionable recommendations based on portfolio state."""

from typing import Dict, List, Optional


class ActionRecommender:
    """Generate prioritized action recommendations."""

    def generate(
        self,
        portfolio_analysis: Dict,
        risk_assessment: List[Dict],
        target_allocation: Dict,
        cash_reserves: float = 0,
        myst_balance: float = 0,
        swap_routes: Optional[Dict] = None,
        swap_config: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        Generate actionable recommendations.

        Swap mode (swap_routes provided): all actions are SWAP operations, no fiat needed.
        Cash mode (default): classic BUY/SELL against cash_reserves.
        """
        swap_mode = bool(swap_routes)
        recommendations = []

        if swap_mode:
            recommendations.extend(
                self._generate_swap_rebalancing(portfolio_analysis, target_allocation, swap_routes)
            )
        else:
            recommendations.extend(
                self._generate_rebalancing(portfolio_analysis, target_allocation)
            )

        recommendations.extend(
            self._generate_profit_taking(portfolio_analysis, risk_assessment, swap_mode=swap_mode)
        )

        if swap_mode and myst_balance > 0:
            recommendations.extend(
                self._generate_myst_deployment(
                    portfolio_analysis, target_allocation,
                    myst_balance, swap_routes, swap_config or {}
                )
            )
        elif not swap_mode and cash_reserves > 1000:
            recommendations.extend(
                self._generate_dca(portfolio_analysis, target_allocation, cash_reserves)
            )

        recommendations.extend(self._generate_loss_management(risk_assessment, swap_mode=swap_mode))

        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        return sorted(recommendations, key=lambda x: priority_order[x['priority']])

    # ------------------------------------------------------------------
    # Swap-mode rebalancing
    # ------------------------------------------------------------------

    def _generate_swap_rebalancing(
        self,
        analysis: Dict,
        target_allocation: Dict,
        swap_routes: Dict,
    ) -> List[Dict]:
        """Match overweight assets against underweight ones as swap pairs."""
        recommendations = []
        total_value = analysis['total_value']

        overweight, underweight = [], []
        for symbol, target_pct in target_allocation.items():
            current_pct = analysis['allocation'].get(symbol, 0) / 100
            drift = current_pct - target_pct
            if drift > 0.10:
                overweight.append({'symbol': symbol, 'drift': drift, 'delta_usd': total_value * drift})
            elif drift < -0.10:
                underweight.append({'symbol': symbol, 'drift': abs(drift), 'delta_usd': total_value * abs(drift)})

        overweight.sort(key=lambda x: -x['drift'])
        underweight.sort(key=lambda x: -x['drift'])

        for ow in overweight:
            for uw in underweight:
                swap_usd = min(ow['delta_usd'], uw['delta_usd'])
                route = self._find_route(ow['symbol'], uw['symbol'], swap_routes)
                priority = 'high' if (ow['drift'] > 0.20 or uw['drift'] > 0.20) else 'medium'
                recommendations.append({
                    'priority': priority,
                    'action': 'SWAP',
                    'from_asset': ow['symbol'],
                    'asset': uw['symbol'],
                    'amount_usd': swap_usd,
                    'route': route,
                    'rationale': (
                        f'Rebalance: {ow["symbol"]} {ow["drift"]*100:.1f}% overweight → '
                        f'{uw["symbol"]} {uw["drift"]*100:.1f}% underweight'
                    ),
                    'type': 'REBALANCE_SWAP',
                })

        return recommendations

    # ------------------------------------------------------------------
    # MYST income deployment
    # ------------------------------------------------------------------

    def _generate_myst_deployment(
        self,
        analysis: Dict,
        target_allocation: Dict,
        myst_balance: float,
        swap_routes: Dict,
        swap_config: Dict,
    ) -> List[Dict]:
        """Suggest when and how to deploy accumulated MYST node earnings."""
        min_swap_usd = swap_config.get('min_swap_usd', 50)
        keep_reserve = swap_config.get('myst_keep_reserve', 100)
        myst_price = swap_config.get('myst_current_price', 0)
        myst_ma_7d = swap_config.get('myst_ma_7d')
        myst_ma_30d = swap_config.get('myst_ma_30d')

        if not myst_price:
            return []

        deployable_myst = max(0.0, myst_balance - keep_reserve)
        deployable_usd = deployable_myst * myst_price

        if deployable_usd < min_swap_usd:
            return []

        # Price timing signal
        if myst_ma_30d and myst_price >= myst_ma_30d * 1.10:
            priority = 'high'
            timing_note = (
                f'MYST is {((myst_price / myst_ma_30d) - 1) * 100:.0f}% above 30d avg — '
                'strong window to swap out'
            )
        elif myst_ma_7d and myst_price >= myst_ma_7d:
            priority = 'medium'
            timing_note = 'MYST is above 7d avg — reasonable swap window'
        else:
            priority = 'low'
            timing_note = (
                'MYST is below 7d avg — consider waiting unless rebalancing is urgent'
            )

        # Find underweight assets (skip MYST itself)
        total_value = analysis['total_value'] + deployable_usd
        underweight = []
        for symbol, target_pct in target_allocation.items():
            if symbol == 'MYST':
                continue
            current_usd = analysis['total_value'] * (analysis['allocation'].get(symbol, 0) / 100)
            target_usd = total_value * target_pct
            needed_usd = target_usd - current_usd
            if needed_usd >= min_swap_usd:
                underweight.append({'symbol': symbol, 'needed_usd': needed_usd})

        if not underweight:
            return []

        underweight.sort(key=lambda x: -x['needed_usd'])
        total_needed = sum(u['needed_usd'] for u in underweight)

        recommendations = []
        for uw in underweight[:3]:
            proportion = uw['needed_usd'] / total_needed
            swap_usd = min(deployable_usd * proportion, uw['needed_usd'])
            swap_myst = swap_usd / myst_price
            if swap_usd < min_swap_usd:
                continue

            route = self._find_route('MYST', uw['symbol'], swap_routes)
            recommendations.append({
                'priority': priority,
                'action': 'SWAP',
                'from_asset': 'MYST',
                'from_amount': round(swap_myst, 4),
                'asset': uw['symbol'],
                'amount_usd': swap_usd,
                'route': route,
                'rationale': (
                    f'{timing_note}. Deploy {swap_myst:.1f} MYST (~${swap_usd:,.0f}) '
                    f'via {route} to bring {uw["symbol"]} to target'
                ),
                'type': 'MYST_DEPLOYMENT',
            })

        return recommendations

    # ------------------------------------------------------------------
    # Cash-mode helpers (unchanged behaviour)
    # ------------------------------------------------------------------

    def _generate_rebalancing(self, analysis: Dict, target_allocation: Dict) -> List[Dict]:
        recommendations = []
        total_value = analysis['total_value']

        for symbol, target_pct in target_allocation.items():
            current_pct = analysis['allocation'].get(symbol, 0) / 100
            drift = current_pct - target_pct
            if abs(drift) <= 0.10:
                continue
            delta_usd = total_value * (target_pct - current_pct)
            action = 'BUY' if delta_usd > 0 else 'SELL'
            priority = 'high' if abs(drift) > 0.20 else ('medium' if abs(drift) > 0.15 else 'low')
            recommendations.append({
                'priority': priority,
                'action': action,
                'asset': symbol,
                'amount_usd': abs(delta_usd),
                'current_pct': current_pct * 100,
                'target_pct': target_pct * 100,
                'rationale': f'Rebalance {symbol} from {current_pct*100:.1f}% to {target_pct*100:.1f}%',
                'type': 'REBALANCE',
            })
        return recommendations

    def _generate_profit_taking(
        self, analysis: Dict, risks: List[Dict], swap_mode: bool = False
    ) -> List[Dict]:
        recommendations = []
        for risk in risks:
            if risk['type'] not in ('LARGE_UNREALIZED_GAIN', 'MODERATE_UNREALIZED_GAIN'):
                continue
            pos = next((p for p in analysis['positions'] if p['symbol'] == risk['asset']), None)
            if not pos:
                continue
            if risk['gain_pct'] > 200:
                take_pct, priority = 0.50, 'high'
            elif risk['gain_pct'] > 100:
                take_pct, priority = 0.33, 'medium'
            else:
                take_pct, priority = 0.25, 'low'

            take_usd = pos['current_value'] * take_pct
            action = 'SWAP_TO_MYST' if swap_mode else 'SELL'
            rationale = f'Take profits on {risk["asset"]} (+{risk["gain_pct"]:.0f}% gain)'
            if swap_mode:
                rationale += ' — swap portion back to MYST income pool'

            recommendations.append({
                'priority': priority,
                'action': action,
                'asset': risk['asset'],
                'amount': pos['amount'] * take_pct,
                'amount_usd': take_usd,
                'percentage': take_pct * 100,
                'rationale': rationale,
                'type': 'PROFIT_TAKING',
            })
        return recommendations

    def _generate_dca(
        self, analysis: Dict, target_allocation: Dict, cash_reserves: float
    ) -> List[Dict]:
        recommendations = []
        for symbol, target_pct in target_allocation.items():
            current_pct = analysis['allocation'].get(symbol, 0) / 100
            if current_pct < target_pct - 0.05:
                dca_amount = min(cash_reserves * 0.25, 2000)
                if dca_amount >= 100:
                    recommendations.append({
                        'priority': 'low',
                        'action': 'BUY',
                        'asset': symbol,
                        'amount_usd': dca_amount,
                        'rationale': (
                            f'DCA into underweight {symbol} '
                            f'(current: {current_pct*100:.1f}%, target: {target_pct*100:.1f}%)'
                        ),
                        'type': 'DCA',
                    })
        return recommendations

    def _generate_loss_management(
        self, risks: List[Dict], swap_mode: bool = False
    ) -> List[Dict]:
        recommendations = []
        for risk in risks:
            if risk['type'] == 'LARGE_UNREALIZED_LOSS':
                note = (
                    'consider swapping to a stronger asset rather than holding'
                    if swap_mode else
                    'review fundamentals and consider tax-loss harvesting'
                )
                recommendations.append({
                    'priority': 'medium',
                    'action': 'REVIEW',
                    'asset': risk['asset'],
                    'loss_pct': risk['loss_pct'],
                    'rationale': f'{risk["asset"]} down {risk["loss_pct"]:.1f}% — {note}',
                    'type': 'LOSS_MANAGEMENT',
                })
        return recommendations

    # ------------------------------------------------------------------
    # Routing helper
    # ------------------------------------------------------------------

    def _find_route(self, from_sym: str, to_sym: str, swap_routes: Dict) -> str:
        """Return the best swap path between two assets."""
        direct = swap_routes.get(from_sym, [])
        if to_sym in direct:
            return f'{from_sym} → {to_sym}'
        for intermediary in direct:
            if to_sym in swap_routes.get(intermediary, []):
                return f'{from_sym} → {intermediary} → {to_sym}'
        return f'{from_sym} → {to_sym} (manual route needed)'
