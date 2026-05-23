"""Tax lot tracking for cryptocurrency cost basis calculation."""

from datetime import datetime
from typing import List, Dict


class TaxLotTracker:
    """Track individual tax lots for accurate cost basis."""
    
    def __init__(self, method: str = 'FIFO'):
        """
        Initialize tax lot tracker.
        
        Args:
            method: Cost basis method - 'FIFO', 'LIFO', or 'HIFO'
        """
        if method not in ['FIFO', 'LIFO', 'HIFO']:
            raise ValueError(f"Invalid method: {method}. Use FIFO, LIFO, or HIFO")
        
        self.method = method
    
    def calculate_realized_gains(
        self,
        purchases: List[Dict],
        sales: List[Dict]
    ) -> List[Dict]:
        """
        Calculate realized gains/losses from sales.
        
        Args:
            purchases: List of purchase transactions
                [{'date': '2024-01-15', 'amount': 0.1, 'price': 45000}, ...]
            sales: List of sale transactions
                [{'date': '2024-06-20', 'amount': 0.05, 'price': 50000}, ...]
        
        Returns:
            List of realized gain/loss records
        """
        # Sort lots based on method
        if self.method == 'FIFO':
            lots = sorted(purchases, key=lambda x: x['date'])
        elif self.method == 'LIFO':
            lots = sorted(purchases, key=lambda x: x['date'], reverse=True)
        else:  # HIFO
            lots = sorted(purchases, key=lambda x: x['price'], reverse=True)
        
        # Make a copy to avoid modifying original
        lots = [dict(lot) for lot in lots]
        
        realized_gains = []
        
        for sale in sales:
            sale_amount = sale['amount']
            sale_price = sale['price']
            sale_date = sale['date']
            
            remaining_to_sell = sale_amount
            
            while remaining_to_sell > 0 and lots:
                lot = lots[0]
                lot_amount = lot['amount']
                
                # How much from this lot?
                sold_from_lot = min(lot_amount, remaining_to_sell)
                
                # Calculate gain/loss
                proceeds = sold_from_lot * sale_price
                cost_basis = sold_from_lot * lot['price']
                gain = proceeds - cost_basis
                
                # Tax treatment (short-term vs long-term)
                purchase_date = datetime.strptime(lot['date'], '%Y-%m-%d')
                sale_date_dt = datetime.strptime(sale_date, '%Y-%m-%d')
                holding_period = (sale_date_dt - purchase_date).days
                
                term = 'long' if holding_period > 365 else 'short'
                
                realized_gains.append({
                    'purchase_date': lot['date'],
                    'sale_date': sale_date,
                    'amount': sold_from_lot,
                    'cost_basis': cost_basis,
                    'proceeds': proceeds,
                    'gain_loss': gain,
                    'holding_period_days': holding_period,
                    'term': term
                })
                
                # Update lot and remaining
                lot['amount'] -= sold_from_lot
                remaining_to_sell -= sold_from_lot
                
                if lot['amount'] <= 0:
                    lots.pop(0)
        
        return realized_gains
    
    def generate_tax_summary(self, realized_gains: List[Dict]) -> Dict:
        """
        Generate tax summary from realized gains.
        
        Args:
            realized_gains: Output from calculate_realized_gains()
        
        Returns:
            Summary with short/long-term totals
        """
        short_term_total = sum(
            g['gain_loss'] for g in realized_gains if g['term'] == 'short'
        )
        
        long_term_total = sum(
            g['gain_loss'] for g in realized_gains if g['term'] == 'long'
        )
        
        return {
            'short_term_gain_loss': short_term_total,
            'long_term_gain_loss': long_term_total,
            'total_gain_loss': short_term_total + long_term_total,
            'num_transactions': len(realized_gains),
            'method': self.method
        }
