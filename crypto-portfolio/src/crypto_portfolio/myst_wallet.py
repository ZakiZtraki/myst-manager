"""On-chain token wallet balance reader."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, Optional

import requests


@dataclass(frozen=True)
class MystChain:
    name: str
    rpc_url: str
    contract: str
    native: bool = False


MYST_CHAINS: Dict[str, MystChain] = {
    "polygon": MystChain(
        name="Polygon",
        rpc_url="https://1rpc.io/matic",
        contract="0x1379e8886a944d2d9d440b3d88df536aea08d9f3",
    ),
    "bsc": MystChain(
        name="BSC",
        rpc_url="https://bsc-dataseed.binance.org",
        contract="0x2ff0b946a6782190c4fe5d4971cfe79f0b6e4df2",
    ),
    "ethereum": MystChain(
        name="Ethereum",
        rpc_url="https://ethereum.publicnode.com",
        contract="0x4cf89ca06ad997bc732dc876ed2a7f26a9e7f361",
    ),
}

TOKEN_CHAINS: Dict[str, Dict[str, MystChain]] = {
    "MYST": MYST_CHAINS,
    "POL": {
        "polygon": MystChain(
            name="Polygon",
            rpc_url="https://1rpc.io/matic",
            contract="native",
            native=True,
        ),
        "ethereum": MystChain(
            name="Ethereum",
            rpc_url="https://ethereum.publicnode.com",
            contract="0x455e53cbb86018ac2b8092fdcd39d8444affc3f6",
        ),
    },
}


class MystWalletClient:
    """Read supported on-chain token balances across supported chains."""

    def __init__(self, timeout: int = 20):
        self.timeout = timeout

    def get_balances(
        self,
        address: str,
        chains: Optional[Iterable[str]] = None,
        token: str = "MYST",
    ) -> Dict:
        """Return token balances for an EVM address across configured chains."""
        normalized = self._normalize_address(address)
        token_symbol = token.upper()
        if token_symbol not in TOKEN_CHAINS:
            raise ValueError(f"Unsupported token: {token_symbol}")
        token_chains = TOKEN_CHAINS[token_symbol]
        selected = [c.lower() for c in chains] if chains else list(token_chains)
        balances = []

        for key in selected:
            if key not in token_chains:
                raise ValueError(f"Unsupported chain: {key}")
            chain = token_chains[key]
            raw = self._native_balance(chain, normalized) if chain.native else self._balance_of(chain, normalized)
            balances.append({
                "chain": chain.name,
                "contract": chain.contract,
                "native": chain.native,
                "raw": str(raw),
                "balance": float(Decimal(raw) / Decimal(10**18)),
            })

        total = sum(Decimal(item["raw"]) for item in balances) / Decimal(10**18)
        return {
            "address": normalized,
            "token": token_symbol,
            "balances": balances,
            "total_balance": float(total),
        }

    def get_token_balances(
        self,
        address: str,
        token: str,
        chains: Optional[Iterable[str]] = None,
    ) -> Dict:
        """Return balances for a supported token."""
        return self.get_balances(address, chains=chains, token=token)

    def _balance_of(self, chain: MystChain, address: str) -> int:
        data = "0x70a08231" + ("0" * 24) + address[2:]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": chain.contract, "data": data}, "latest"],
        }
        response = requests.post(chain.rpc_url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"{chain.name} RPC error: {body['error']}")
        result = body.get("result")
        if not result:
            raise RuntimeError(f"{chain.name} RPC returned no result")
        return int(result, 16)

    def _native_balance(self, chain: MystChain, address: str) -> int:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getBalance",
            "params": [address, "latest"],
        }
        response = requests.post(chain.rpc_url, json=payload, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"{chain.name} RPC error: {body['error']}")
        result = body.get("result")
        if not result:
            raise RuntimeError(f"{chain.name} RPC returned no result")
        return int(result, 16)

    def _normalize_address(self, address: str) -> str:
        value = address.strip().lower()
        if not value.startswith("0x") or len(value) != 42:
            raise ValueError("Expected a 20-byte EVM address starting with 0x")
        int(value[2:], 16)
        return value
