"""Tests for on-chain MYST wallet balance reader."""

from types import SimpleNamespace

import pytest

from crypto_portfolio.myst_wallet import MystWalletClient


def test_get_balances_aggregates_chain_balances(monkeypatch):
    raw_values = iter([
        10 * 10**18,
        5 * 10**18,
    ])

    def fake_post(url, json, timeout):
        value = next(raw_values)
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {'result': hex(value)},
        )

    monkeypatch.setattr('crypto_portfolio.myst_wallet.requests.post', fake_post)

    client = MystWalletClient()
    result = client.get_balances(
        '0x3fade093f91d6bddbdb802c01fab2a949bac3fa6',
        chains=['polygon', 'bsc'],
    )

    assert result['total_balance'] == 15.0
    assert result['balances'][0]['balance'] == 10.0
    assert result['balances'][1]['balance'] == 5.0


def test_get_balances_rejects_invalid_address():
    client = MystWalletClient()

    with pytest.raises(ValueError, match='Expected a 20-byte EVM address'):
        client.get_balances('not-an-address')


def test_get_balances_rejects_unknown_chain():
    client = MystWalletClient()

    with pytest.raises(ValueError, match='Unsupported chain'):
        client.get_balances(
            '0x3fade093f91d6bddbdb802c01fab2a949bac3fa6',
            chains=['unknown'],
        )


def test_get_token_balances_reads_native_pol(monkeypatch):
    def fake_post(url, json, timeout):
        assert json['method'] == 'eth_getBalance'
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {'result': hex(7 * 10**18)},
        )

    monkeypatch.setattr('crypto_portfolio.myst_wallet.requests.post', fake_post)

    client = MystWalletClient()
    result = client.get_token_balances(
        '0x3fade093f91d6bddbdb802c01fab2a949bac3fa6',
        'POL',
        chains=['polygon'],
    )

    assert result['token'] == 'POL'
    assert result['total_balance'] == 7.0
    assert result['balances'][0]['native'] is True


def test_get_token_balances_rejects_unknown_token():
    client = MystWalletClient()

    with pytest.raises(ValueError, match='Unsupported token'):
        client.get_token_balances(
            '0x3fade093f91d6bddbdb802c01fab2a949bac3fa6',
            'NOPE',
        )
