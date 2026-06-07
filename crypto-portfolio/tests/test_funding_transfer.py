"""Tests for Binance Funding-to-Spot transfer orchestration."""

import json

import pytest

from crypto_portfolio.manager import PortfolioManager


class FakeTransferBinance:
    def __init__(self, balances):
        self.balances = balances
        self.transfers = []

    def get_funding_wallet_balance(self, asset):
        return self.balances.get(asset.upper(), 0)

    def transfer_to_spot(self, asset, amount):
        self.transfers.append((asset, amount))
        return {'tranId': 12345}


def make_manager(tmp_path, balances):
    portfolio_path = tmp_path / 'portfolio.json'
    portfolio_path.write_text(json.dumps({'holdings': [], 'target_allocation': {}}))
    pm = PortfolioManager(str(portfolio_path), use_binance=False)
    pm.binance = FakeTransferBinance(balances)
    return pm


def test_transfer_asset_to_spot_exact_amount(tmp_path):
    pm = make_manager(tmp_path, {'POL': 500})

    result = pm.transfer_asset_to_spot('pol', 250.7)

    assert result['status'] == 'transferred'
    assert result['asset'] == 'POL'
    assert result['transferred'] == 250.7
    assert result['tran_id'] == 12345
    assert pm.binance.transfers == [('POL', 250.7)]


def test_transfer_asset_to_spot_all_above_reserve(tmp_path):
    pm = make_manager(tmp_path, {'TRX': 100})

    result = pm.transfer_asset_to_spot('TRX', -1, keep_reserve=12.5)

    assert result['status'] == 'transferred'
    assert result['transferred'] == 87.5
    assert pm.binance.transfers == [('TRX', 87.5)]


def test_transfer_asset_to_spot_skips_when_reserve_consumes_balance(tmp_path):
    pm = make_manager(tmp_path, {'POL': 10})

    result = pm.transfer_asset_to_spot('POL', -1, keep_reserve=10)

    assert result['status'] == 'skipped'
    assert pm.binance.transfers == []


def test_transfer_asset_to_spot_rejects_insufficient_funding_balance(tmp_path):
    pm = make_manager(tmp_path, {'POL': 10})

    with pytest.raises(ValueError, match='Insufficient POL'):
        pm.transfer_asset_to_spot('POL', 11)

    assert pm.binance.transfers == []
