"""Tests for Binance Web3 Wallet CLI wrapper."""

import json
from types import SimpleNamespace

import pytest

from crypto_portfolio.web3_wallet import BinanceWeb3WalletClient, Web3WalletError


def test_quote_swap_builds_baw_command(monkeypatch):
    calls = []

    def fake_run(command, capture_output, text, timeout, check):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({'success': True, 'data': {'toCoinAmount': '12.3'}}),
            stderr='',
        )

    monkeypatch.setattr('crypto_portfolio.web3_wallet.shutil.which', lambda _: 'baw')
    monkeypatch.setattr('crypto_portfolio.web3_wallet.subprocess.run', fake_run)

    client = BinanceWeb3WalletClient()
    result = client.quote_swap(
        from_token_qty=10,
        from_token='0xsource',
        to_token='0xtarget',
        chain_id='137',
        slippage='2.5',
    )

    assert result['data']['toCoinAmount'] == '12.3'
    assert calls == [[
        'baw',
        'market-order',
        'quote',
        '--fromTokenQty',
        '10',
        '--fromToken',
        '0xsource',
        '--toToken',
        '0xtarget',
        '--binanceChainId',
        '137',
        '--slippage',
        '2.5',
        '--json',
    ]]


def test_execute_swap_builds_confirmed_market_order_command(monkeypatch):
    calls = []

    def fake_run(command, capture_output, text, timeout, check):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({'success': True, 'data': {'orderId': 'order-1'}}),
            stderr='',
        )

    monkeypatch.setattr('crypto_portfolio.web3_wallet.shutil.which', lambda _: 'baw')
    monkeypatch.setattr('crypto_portfolio.web3_wallet.subprocess.run', fake_run)

    client = BinanceWeb3WalletClient()
    result = client.execute_swap(
        from_token_qty=5,
        from_token='0xsource',
        to_token='0xtarget',
        chain_id='137',
        mev=False,
        gas_level='medium',
    )

    assert result['data']['orderId'] == 'order-1'
    assert '--mev' in calls[0]
    assert 'false' in calls[0]
    assert '--gasLevel' in calls[0]
    assert 'MEDIUM' in calls[0]


def test_missing_baw_raises_clear_error(monkeypatch):
    monkeypatch.setattr('crypto_portfolio.web3_wallet.shutil.which', lambda _: None)

    client = BinanceWeb3WalletClient()

    with pytest.raises(Web3WalletError, match='CLI not found'):
        client.status()


def test_nonzero_exit_raises_stderr(monkeypatch):
    def fake_run(command, capture_output, text, timeout, check):
        return SimpleNamespace(returncode=1, stdout='', stderr='not signed in')

    monkeypatch.setattr('crypto_portfolio.web3_wallet.shutil.which', lambda _: 'baw')
    monkeypatch.setattr('crypto_portfolio.web3_wallet.subprocess.run', fake_run)

    client = BinanceWeb3WalletClient()

    with pytest.raises(Web3WalletError, match='not signed in'):
        client.status()


def test_failed_json_response_raises(monkeypatch):
    def fake_run(command, capture_output, text, timeout, check):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({'success': False, 'error': 'blocked'}),
            stderr='',
        )

    monkeypatch.setattr('crypto_portfolio.web3_wallet.shutil.which', lambda _: 'baw')
    monkeypatch.setattr('crypto_portfolio.web3_wallet.subprocess.run', fake_run)

    client = BinanceWeb3WalletClient()

    with pytest.raises(Web3WalletError, match='blocked'):
        client.status()
