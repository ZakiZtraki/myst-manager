"""Binance Web3 Wallet integration via the Binance Agentic Wallet CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional


MYST_POLYGON_CONTRACT = "0x1379e8886a944d2d9d440b3d88df536aea08d9f3"
POLYGON_CHAIN_ID = "137"


class Web3WalletError(RuntimeError):
    """Raised when Binance Agentic Wallet CLI calls fail."""


class BinanceWeb3WalletClient:
    """Small wrapper around the `baw` Binance Agentic Wallet CLI."""

    def __init__(self, baw_bin: Optional[str] = None, timeout: int = 60):
        self.baw_bin = baw_bin or os.getenv("BAW_BIN", "baw")
        self.timeout = timeout

    def _run(self, args: List[str]) -> Dict:
        """Run a baw command and return parsed JSON."""
        executable = shutil.which(self.baw_bin)
        if not executable:
            raise Web3WalletError(
                f"Binance Agentic Wallet CLI not found: {self.baw_bin}. "
                "Install @binance/agentic-wallet and ensure `baw` is on PATH."
            )

        command = [executable] + args + ["--json"]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise Web3WalletError(f"baw command timed out: {' '.join(command)}") from exc

        output = completed.stdout.strip()
        if completed.returncode != 0:
            error = completed.stderr.strip() or output or f"exit code {completed.returncode}"
            raise Web3WalletError(error)

        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            raise Web3WalletError(f"baw returned non-JSON output: {output}") from exc

        if data.get("success") is False:
            raise Web3WalletError(json.dumps(data, default=str))

        return data

    def status(self) -> Dict:
        """Return wallet connection status."""
        return self._run(["wallet", "status"])

    def chains(self) -> Dict:
        """Return supported chains."""
        return self._run(["wallet", "chains"])

    def addresses(self) -> Dict:
        """Return wallet addresses."""
        return self._run(["wallet", "address"])

    def balance(
        self,
        symbol: Optional[str] = None,
        token_address: Optional[str] = None,
        chain_id: Optional[str] = None,
    ) -> Dict:
        """Return token balances, optionally filtered by symbol/address/chain."""
        args = ["wallet", "balance"]
        if symbol:
            args += ["--symbol", symbol.upper()]
        if token_address:
            args += ["--tokenAddress", token_address]
        if chain_id:
            args += ["--binanceChainId", str(chain_id)]
        return self._run(args)

    def tx_history(
        self,
        chain_id: Optional[str] = None,
        tx_type: str = "all",
        size: int = 20,
        next_cursor: Optional[str] = None,
    ) -> Dict:
        """Return wallet transaction history."""
        args = ["wallet", "tx-history", "--type", tx_type, "--size", str(size)]
        if chain_id:
            args += ["--binanceChainId", str(chain_id)]
        if next_cursor:
            args += ["--nextCursor", next_cursor]
        return self._run(args)

    def tx_lock(self, chain_id: str) -> Dict:
        """Return whether the wallet is locked by pending confirmations."""
        return self._run(["wallet", "tx-lock", "--binanceChainId", str(chain_id)])

    def quote_swap(
        self,
        from_token_qty: float,
        from_token: str,
        to_token: str,
        chain_id: str,
        slippage: Optional[str] = None,
    ) -> Dict:
        """Get a Web3 market-order quote without executing a swap."""
        args = [
            "market-order",
            "quote",
            "--fromTokenQty",
            str(from_token_qty),
            "--fromToken",
            from_token,
            "--toToken",
            to_token,
            "--binanceChainId",
            str(chain_id),
        ]
        if slippage:
            args += ["--slippage", str(slippage)]
        return self._run(args)

    def execute_swap(
        self,
        from_token_qty: float,
        from_token: str,
        to_token: str,
        chain_id: str,
        slippage: Optional[str] = None,
        mev: Optional[bool] = None,
        gas_level: Optional[str] = None,
    ) -> Dict:
        """Submit a Web3 market-order swap."""
        args = [
            "market-order",
            "swap",
            "--fromTokenQty",
            str(from_token_qty),
            "--fromToken",
            from_token,
            "--toToken",
            to_token,
            "--binanceChainId",
            str(chain_id),
        ]
        if slippage:
            args += ["--slippage", str(slippage)]
        if mev is not None:
            args += ["--mev", "true" if mev else "false"]
        if gas_level:
            args += ["--gasLevel", gas_level.upper()]
        return self._run(args)

    def market_order_status(
        self,
        order_id: Optional[str] = None,
        status: Optional[str] = None,
        chain_id: Optional[str] = None,
        page_size: int = 20,
    ) -> Dict:
        """List or check Web3 market-order status."""
        args = ["market-order", "list", "--pageSize", str(page_size)]
        if order_id:
            args += ["--orderId", order_id]
        if status:
            args += ["--status", status.upper()]
        if chain_id:
            args += ["--binanceChainId", str(chain_id)]
        return self._run(args)
