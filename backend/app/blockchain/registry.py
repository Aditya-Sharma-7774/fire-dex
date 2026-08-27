"""The chain registry -- the single source of truth for supported chains.

Nothing else in the backend may hard-code a chain ID, a native symbol or a
decimal count. Everything reads from here.

The frontend mirrors this in `frontend/src/config/chains.ts`. The two are
kept consistent by a test that compares the frontend file against this
registry, so they cannot drift apart unnoticed.
"""

from app.blockchain.types import ChainConfig, ChainFamily
from app.core.errors import ChainNotSupportedError

CHAINS: dict[str, ChainConfig] = {
    "ethereum": ChainConfig(
        id="ethereum",
        name="Ethereum",
        short_name="ETH",
        family=ChainFamily.EVM,
        chain_id=1,
        native_symbol="ETH",
        native_decimals=18,
        is_testnet=False,
        explorer_url="https://etherscan.io",
        color="#627EEA",
        is_active=True,
    ),
    "sepolia": ChainConfig(
        id="sepolia",
        name="Sepolia Testnet",
        short_name="SEP",
        family=ChainFamily.EVM,
        chain_id=11155111,
        native_symbol="ETH",
        native_decimals=18,
        is_testnet=True,
        explorer_url="https://sepolia.etherscan.io",
        color="#8B9DC3",
        is_active=True,
    ),
    "bsc": ChainConfig(
        id="bsc",
        name="BNB Smart Chain",
        short_name="BNB",
        family=ChainFamily.EVM,
        chain_id=56,
        native_symbol="BNB",
        native_decimals=18,
        is_testnet=False,
        explorer_url="https://bscscan.com",
        color="#F0B90B",
        is_active=False,
    ),
    "solana": ChainConfig(
        id="solana",
        name="Solana",
        short_name="SOL",
        family=ChainFamily.SOLANA,
        chain_id=None,
        native_symbol="SOL",
        native_decimals=9,
        is_testnet=False,
        explorer_url="https://solscan.io",
        color="#14F195",
        is_active=False,
    ),
    "bitcoin": ChainConfig(
        id="bitcoin",
        name="Bitcoin",
        short_name="BTC",
        family=ChainFamily.BITCOIN,
        chain_id=None,
        native_symbol="BTC",
        native_decimals=8,
        is_testnet=False,
        explorer_url="https://mempool.space",
        color="#F7931A",
        is_active=False,
    ),
}


def list_chains() -> list[ChainConfig]:
    """Every chain the application knows about, implemented or not."""
    return list(CHAINS.values())


def get_chain(chain_id: str) -> ChainConfig:
    """Look up one chain by its internal key.

    Raises:
        ChainNotSupportedError: if no such chain exists.
    """
    chain = CHAINS.get(chain_id.lower())
    if chain is None:
        known = ", ".join(sorted(CHAINS))
        raise ChainNotSupportedError(
            f"Unknown chain '{chain_id}'.",
            detail=f"Supported chains: {known}",
        )
    return chain


def get_evm_chain_by_chain_id(chain_id: int) -> ChainConfig | None:
    """Find an EVM chain by its EIP-155 chain ID.

    Used to work out which network a wallet is currently connected to.
    """
    for chain in CHAINS.values():
        if chain.family is ChainFamily.EVM and chain.chain_id == chain_id:
            return chain
    return None
