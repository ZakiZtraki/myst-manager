"""Crypto Portfolio Manager - Portfolio tracking and analysis system."""

from .manager import PortfolioManager
from .api_client import CoinGeckoClient, BinanceClient
from .web3_wallet import BinanceWeb3WalletClient
from .myst_wallet import MystWalletClient
from .analyzer import PortfolioAnalyzer
from .recommender import ActionRecommender

__version__ = "1.0.0"
__all__ = [
    "PortfolioManager",
    "CoinGeckoClient",
    "BinanceClient",
    "BinanceWeb3WalletClient",
    "MystWalletClient",
    "PortfolioAnalyzer",
    "ActionRecommender",
]
