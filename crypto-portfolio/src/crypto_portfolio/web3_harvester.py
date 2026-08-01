"""
On-chain MYST harvesting for Polygon network.

Pipeline:
  1. Check MYST balance in automation wallet
  2. If above reserve, swap MYST → POL via 1inch (falls back to QuickSwap)
  3. Send POL to Binance Exchange Funding deposit address
  4. Caller then uses MCP tools: transfer_asset_to_trade_account → execute_binance_swap
"""

import logging
import os
import time
from typing import Dict, Optional

import requests
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
POLYGON_CHAIN_ID = 137

MYST_ADDRESS  = Web3.to_checksum_address("0x1379e8886a944d2d9d440b3d88df536aea08d9f3")
WPOL_ADDRESS  = Web3.to_checksum_address("0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270")

ONEINCH_ROUTER = Web3.to_checksum_address("0x111111125421ca6dc452d289314280a0f8842a65")
ONEINCH_API    = "https://api.1inch.dev/v6.0/137"
NATIVE_TOKEN   = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

QUICKSWAP_ROUTER = Web3.to_checksum_address("0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff")

ERC20_ABI = [
    {"name": "balanceOf", "type": "function",
     "inputs": [{"name": "account", "type": "address"}],
     "outputs": [{"type": "uint256"}], "stateMutability": "view"},
    {"name": "allowance", "type": "function",
     "inputs": [{"name": "owner", "type": "address"},
                {"name": "spender", "type": "address"}],
     "outputs": [{"type": "uint256"}], "stateMutability": "view"},
    {"name": "approve", "type": "function",
     "inputs": [{"name": "spender", "type": "address"},
                {"name": "amount", "type": "uint256"}],
     "outputs": [{"type": "bool"}], "stateMutability": "nonpayable"},
]

QUICKSWAP_ABI = [
    {"name": "swapExactTokensForETH", "type": "function",
     "inputs": [
         {"name": "amountIn", "type": "uint256"},
         {"name": "amountOutMin", "type": "uint256"},
         {"name": "path", "type": "address[]"},
         {"name": "to", "type": "address"},
         {"name": "deadline", "type": "uint256"},
     ],
     "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "nonpayable"},
    {"name": "getAmountsOut", "type": "function",
     "inputs": [
         {"name": "amountIn", "type": "uint256"},
         {"name": "path", "type": "address[]"},
     ],
     "outputs": [{"name": "amounts", "type": "uint256[]"}],
     "stateMutability": "view"},
]


# ---------------------------------------------------------------------------
# Harvester
# ---------------------------------------------------------------------------

class Web3Harvester:
    """
    Signs and broadcasts Polygon transactions to sweep MYST → POL → Exchange.

    Required env vars (or pass explicitly):
        WEB3_PRIVATE_KEY              hex private key of the automation wallet
        POLYGON_RPC_URL               e.g. https://polygon-rpc.com
        BINANCE_POL_DEPOSIT_ADDRESS   Binance Funding deposit address for POL (Polygon)
    Optional:
        ONEINCH_API_KEY               1inch Developer Portal key (free tier)
    """

    def __init__(
        self,
        private_key: str,
        rpc_url: str,
        binance_deposit_address: str,
        oneinch_api_key: str = "",
    ):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 30}))

        # Polygon is a PoA chain — inject middleware to handle extra block data
        try:
            from web3.middleware import ExtraDataToPOAMiddleware
            self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        except ImportError:
            try:
                from web3.middleware import geth_poa_middleware
                self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)
            except ImportError:
                pass

        self.account: LocalAccount = Account.from_key(private_key)
        self.address = self.account.address
        self.binance_deposit = Web3.to_checksum_address(binance_deposit_address)
        self.api_key = oneinch_api_key

        self.myst      = self.w3.eth.contract(address=MYST_ADDRESS, abi=ERC20_ABI)
        self.quickswap = self.w3.eth.contract(address=QUICKSWAP_ROUTER, abi=QUICKSWAP_ABI)

    # ------------------------------------------------------------------
    # Balance queries
    # ------------------------------------------------------------------

    def get_myst_balance(self) -> float:
        raw = self.myst.functions.balanceOf(self.address).call()
        return raw / 1e18

    def get_pol_balance(self) -> float:
        raw = self.w3.eth.get_balance(self.address)
        return raw / 1e18

    # ------------------------------------------------------------------
    # Internal: sign + broadcast + wait
    # ------------------------------------------------------------------

    def _sign_and_send(self, tx: dict) -> str:
        tx.setdefault("chainId", POLYGON_CHAIN_ID)
        tx.setdefault("nonce", self.w3.eth.get_transaction_count(self.address))
        tx.setdefault("gasPrice", self.w3.eth.gas_price)
        if "gas" not in tx:
            tx["gas"] = int(self.w3.eth.estimate_gas(tx) * 1.2)
        signed = self.account.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return h.hex()

    def _wait(self, tx_hash: str, timeout: int = 120) -> dict:
        return dict(self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout))

    # ------------------------------------------------------------------
    # ERC-20 approval
    # ------------------------------------------------------------------

    def _ensure_approval(self, spender: str, amount_wei: int) -> Optional[str]:
        allowance = self.myst.functions.allowance(self.address, spender).call()
        if allowance >= amount_wei:
            return None
        logger.info("Approving %s to spend MYST …", spender)
        tx = self.myst.functions.approve(
            spender, 2**256 - 1
        ).build_transaction({
            "from": self.address,
            "nonce": self.w3.eth.get_transaction_count(self.address),
            "gasPrice": self.w3.eth.gas_price,
            "chainId": POLYGON_CHAIN_ID,
        })
        tx["gas"] = int(self.w3.eth.estimate_gas(tx) * 1.2)
        signed = self.account.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        self._wait(h.hex())
        logger.info("Approval confirmed: %s", h.hex())
        return h.hex()

    # ------------------------------------------------------------------
    # Swap: MYST → POL via QuickSwap (fallback)
    # ------------------------------------------------------------------

    def _swap_quickswap(self, amount_wei: int, slippage_pct: float) -> Dict:
        path = [MYST_ADDRESS, WPOL_ADDRESS]
        amounts_out = self.quickswap.functions.getAmountsOut(amount_wei, path).call()
        min_out = int(amounts_out[-1] * (1 - slippage_pct / 100))
        deadline = int(time.time()) + 300

        self._ensure_approval(QUICKSWAP_ROUTER, amount_wei)

        tx = self.quickswap.functions.swapExactTokensForETH(
            amount_wei, min_out, path, self.address, deadline
        ).build_transaction({
            "from": self.address,
            "nonce": self.w3.eth.get_transaction_count(self.address),
            "gasPrice": self.w3.eth.gas_price,
            "chainId": POLYGON_CHAIN_ID,
        })
        tx["gas"] = int(self.w3.eth.estimate_gas(tx) * 1.2)
        signed = self.account.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._wait(h.hex())
        pol_received = amounts_out[-1] / 1e18 if receipt["status"] == 1 else 0
        return {
            "method": "quickswap",
            "tx_hash": h.hex(),
            "status": "success" if receipt["status"] == 1 else "failed",
            "pol_received_est": pol_received,
        }

    # ------------------------------------------------------------------
    # Swap: MYST → POL (1inch preferred)
    # ------------------------------------------------------------------

    def swap_myst_to_pol(self, myst_amount: float, slippage_pct: float = 1.0) -> Dict:
        """Swap MYST → native POL. Tries 1inch first, falls back to QuickSwap."""
        amount_wei = int(myst_amount * 1e18)

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            resp = requests.get(
                f"{ONEINCH_API}/swap",
                params={
                    "src": MYST_ADDRESS,
                    "dst": NATIVE_TOKEN,
                    "amount": str(amount_wei),
                    "from": self.address,
                    "slippage": slippage_pct,
                    "disableEstimate": "true",
                },
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                tx_data = resp.json()["tx"]
                self._ensure_approval(ONEINCH_ROUTER, amount_wei)
                tx = {
                    "from": self.address,
                    "to": Web3.to_checksum_address(tx_data["to"]),
                    "data": tx_data["data"],
                    "value": int(tx_data.get("value", 0)),
                    "gasPrice": int(tx_data.get("gasPrice", self.w3.eth.gas_price)),
                    "gas": int(int(tx_data.get("gas", 300_000)) * 1.2),
                    "nonce": self.w3.eth.get_transaction_count(self.address),
                    "chainId": POLYGON_CHAIN_ID,
                }
                signed = self.account.sign_transaction(tx)
                h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                receipt = self._wait(h.hex())
                pol_after = self.get_pol_balance()
                return {
                    "method": "1inch",
                    "tx_hash": h.hex(),
                    "status": "success" if receipt["status"] == 1 else "failed",
                    "pol_balance_after": pol_after,
                }
            logger.warning("1inch API returned %s, falling back to QuickSwap.", resp.status_code)
        except Exception as exc:
            logger.warning("1inch swap error (%s), falling back to QuickSwap.", exc)

        return self._swap_quickswap(amount_wei, slippage_pct)

    # ------------------------------------------------------------------
    # Send POL to Binance Exchange
    # ------------------------------------------------------------------

    def send_pol_to_exchange(self, pol_amount: float, keep_gas: float = 0.5) -> Dict:
        """Send POL to Binance Exchange Funding address, keeping keep_gas POL for gas."""
        balance = self.get_pol_balance()
        available = balance - keep_gas
        to_send = min(pol_amount, available)

        if to_send <= 0:
            return {
                "status": "skipped",
                "reason": f"POL balance {balance:.4f}, after keep_gas {keep_gas} nothing to send",
            }

        gas_price = self.w3.eth.gas_price
        gas_limit = 21_000
        gas_cost = gas_price * gas_limit

        amount_wei = int(to_send * 1e18)
        if amount_wei + gas_cost > int(balance * 1e18):
            amount_wei = int(balance * 1e18) - gas_cost - int(keep_gas * 1e18)

        if amount_wei <= 0:
            return {"status": "skipped", "reason": "After gas deduction, nothing to send."}

        tx = {
            "to": self.binance_deposit,
            "value": amount_wei,
            "gas": gas_limit,
            "gasPrice": gas_price,
            "nonce": self.w3.eth.get_transaction_count(self.address),
            "chainId": POLYGON_CHAIN_ID,
        }
        signed = self.account.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self._wait(h.hex())

        return {
            "status": "success" if receipt["status"] == 1 else "failed",
            "tx_hash": h.hex(),
            "pol_sent": amount_wei / 1e18,
            "destination": self.binance_deposit,
        }

    # ------------------------------------------------------------------
    # Full harvest pipeline
    # ------------------------------------------------------------------

    def run_harvest(
        self,
        myst_keep_reserve: float = 5.0,
        min_value_usd: float = 5.0,
        myst_price_usd: float = 0.0,
        slippage_pct: float = 1.0,
    ) -> Dict:
        """
        Full pipeline: check MYST → swap to POL → send to Exchange.

        Args:
            myst_keep_reserve: MYST to leave in wallet (for node staking gas).
            min_value_usd:     Skip if swap value is below this (avoids micro-txs).
            myst_price_usd:    Used for min_value check. 0 = skip check.
            slippage_pct:      Max DEX slippage % (default 1%).
        """
        result: Dict = {"steps": []}

        myst_balance = self.get_myst_balance()
        result["myst_balance"] = myst_balance
        myst_to_swap = max(0.0, myst_balance - myst_keep_reserve)

        if myst_to_swap <= 0:
            result["status"] = "skipped"
            result["reason"] = (
                f"MYST balance {myst_balance:.4f} ≤ reserve {myst_keep_reserve}"
            )
            return result

        if myst_price_usd > 0 and myst_to_swap * myst_price_usd < min_value_usd:
            result["status"] = "skipped"
            result["reason"] = (
                f"Swap value ${myst_to_swap * myst_price_usd:.2f} "
                f"below min ${min_value_usd:.2f}"
            )
            return result

        logger.info("Swapping %.4f MYST → POL …", myst_to_swap)
        swap_result = self.swap_myst_to_pol(myst_to_swap, slippage_pct)
        result["steps"].append({"step": "swap_myst_to_pol", **swap_result})

        if swap_result.get("status") != "success":
            result["status"] = "failed"
            result["reason"] = "Swap failed"
            return result

        time.sleep(3)

        pol_balance = self.get_pol_balance()
        logger.info("Sending %.4f POL → Binance Exchange …", pol_balance)
        send_result = self.send_pol_to_exchange(pol_balance)
        result["steps"].append({"step": "send_pol_to_exchange", **send_result})

        result["status"] = (
            "success" if send_result.get("status") == "success" else "partial"
        )
        result["pol_sent_to_exchange"] = send_result.get("pol_sent", 0)
        return result


def harvester_from_env() -> "Web3Harvester":
    """Construct a Web3Harvester from environment variables."""
    pk      = os.environ.get("WEB3_PRIVATE_KEY", "")
    rpc     = os.environ.get("POLYGON_RPC_URL", "https://polygon-rpc.com")
    deposit = os.environ.get("BINANCE_POL_DEPOSIT_ADDRESS", "")
    api_key = os.environ.get("ONEINCH_API_KEY", "")

    if not pk:
        raise ValueError("WEB3_PRIVATE_KEY not set in environment")
    if not deposit:
        raise ValueError("BINANCE_POL_DEPOSIT_ADDRESS not set in environment")

    return Web3Harvester(pk, rpc, deposit, api_key)
