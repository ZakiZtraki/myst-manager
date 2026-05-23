"""Basic tests for portfolio manager."""

import pytest
from crypto_portfolio.analyzer import PortfolioAnalyzer


def test_portfolio_analysis():
    """Test P&L calculation accuracy."""
    analyzer = PortfolioAnalyzer()
    
    test_holdings = [
        {'symbol': 'BTC', 'amount': 1.0, 'avg_purchase_price': 30000}
    ]
    
    test_prices = {
        'bitcoin': {'usd': 40000, 'usd_24h_change': 2.5}
    }
    
    result = analyzer.analyze(test_holdings, test_prices)
    
    assert result['total_value'] == 40000
    assert result['total_cost'] == 30000
    assert result['total_pnl'] == 10000
    assert abs(result['total_pnl_pct'] - 33.33) < 0.01
    
    print("✅ Portfolio P&L test passed")


def test_allocation_calculation():
    """Test allocation percentage calculation."""
    analyzer = PortfolioAnalyzer()
    
    test_holdings = [
        {'symbol': 'BTC', 'amount': 1.0, 'avg_purchase_price': 30000},
        {'symbol': 'ETH', 'amount': 10.0, 'avg_purchase_price': 2000}
    ]
    
    test_prices = {
        'bitcoin': {'usd': 40000, 'usd_24h_change': 2.5},
        'ethereum': {'usd': 3000, 'usd_24h_change': 3.0}
    }
    
    result = analyzer.analyze(test_holdings, test_prices)
    
    # BTC: 40000, ETH: 30000, Total: 70000
    # BTC should be ~57.14%, ETH ~42.86%
    assert abs(result['allocation']['BTC'] - 57.14) < 0.1
    assert abs(result['allocation']['ETH'] - 42.86) < 0.1
    
    print("✅ Allocation calculation test passed")


if __name__ == '__main__':
    test_portfolio_analysis()
    test_allocation_calculation()
    print("\n✅ All tests passed!")
