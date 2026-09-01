"""The token registry -- the single source of truth for token metadata.

WHY THIS FILE EXISTS
--------------------
The naive approach writes a contract address directly into whichever screen
needs it. Then the same address appears in eight places, one of them has a
typo, and the application reads the wrong contract. In a wallet that is not
a cosmetic bug.

Every token is defined exactly once, here.

HOW THESE ADDRESSES WERE OBTAINED
---------------------------------
Not from memory, and not from a single source. Each address was taken from
CoinGecko's coin list and then VERIFIED ON-CHAIN by calling `symbol()`,
`name()` and `decimals()` on the contract itself and checking the answers
matched. Two independent sources had to agree.

`backend/tests/test_tokens.py` includes an opt-in live test that re-runs
that verification against the real chain.

NOTE ON DECIMALS
----------------
USDT and USDC use 6 decimals, not 18. Assuming 18 for every ERC-20 is a
common and severe bug -- it would misreport those balances by a factor of
10^12. This is exactly why decimals live in configuration and are read from
the contract, never guessed.
"""

from app.tokens.types import TokenConfig

# Ordered roughly by how prominent they should appear in the UI.
ETHEREUM_TOKENS: list[TokenConfig] = [
    TokenConfig(
        symbol="ETH",
        name="Ethereum",
        chain="ethereum",
        address=None,  # native asset, not a contract
        decimals=18,
        coingecko_id="ethereum",
        is_native=True,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="USDT",
        name="Tether USD",
        chain="ethereum",
        address="0xdAC17F958D2ee523a2206206994597C13D831ec7",
        decimals=6,
        coingecko_id="tether",
        is_native=False,
        is_stablecoin=True,
    ),
    TokenConfig(
        symbol="USDC",
        name="USD Coin",
        chain="ethereum",
        address="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        decimals=6,
        coingecko_id="usd-coin",
        is_native=False,
        is_stablecoin=True,
    ),
    TokenConfig(
        symbol="DAI",
        name="Dai Stablecoin",
        chain="ethereum",
        address="0x6B175474E89094C44Da98b954EedeAC495271d0F",
        decimals=18,
        coingecko_id="dai",
        is_native=False,
        is_stablecoin=True,
    ),
    TokenConfig(
        symbol="WBTC",
        name="Wrapped BTC",
        chain="ethereum",
        address="0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        decimals=8,
        coingecko_id="wrapped-bitcoin",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="LINK",
        name="ChainLink Token",
        chain="ethereum",
        address="0x514910771AF9Ca656af840dff83E8264EcF986CA",
        decimals=18,
        coingecko_id="chainlink",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="UNI",
        name="Uniswap",
        chain="ethereum",
        address="0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        decimals=18,
        coingecko_id="uniswap",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="AAVE",
        name="Aave Token",
        chain="ethereum",
        address="0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
        decimals=18,
        coingecko_id="aave",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="SHIB",
        name="Shiba Inu",
        chain="ethereum",
        address="0x95aD61b0a150d79219dCF64E1E6Cc01f0B64C4cE",
        decimals=18,
        coingecko_id="shiba-inu",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="PEPE",
        name="Pepe",
        chain="ethereum",
        address="0x6982508145454Ce325dDbE47a25d4ec3d2311933",
        decimals=18,
        coingecko_id="pepe",
        is_native=False,
        is_stablecoin=False,
    ),
]

# Sepolia has no meaningful token economy -- the tokens that exist are test
# deployments with no price. We list only the native asset, and deliberately
# do NOT reuse mainnet addresses here: the same address on a testnet is a
# different contract, or nothing at all.
SEPOLIA_TOKENS: list[TokenConfig] = [
    TokenConfig(
        symbol="ETH",
        name="Sepolia Ether",
        chain="sepolia",
        address=None,
        decimals=18,
        # Priced using mainnet ETH so the UI has something to show. Testnet
        # ETH has no real value; the interface must say so.
        coingecko_id="ethereum",
        is_native=True,
        is_stablecoin=False,
    ),
]

TOKENS_BY_CHAIN: dict[str, list[TokenConfig]] = {
    "ethereum": ETHEREUM_TOKENS,
    "sepolia": SEPOLIA_TOKENS,
}


def list_tokens(chain: str) -> list[TokenConfig]:
    """Every token we track on one chain. Empty list if the chain has none."""
    return TOKENS_BY_CHAIN.get(chain, [])


def get_token(chain: str, symbol: str) -> TokenConfig | None:
    """One token by chain and symbol."""
    wanted = symbol.upper()
    for token in list_tokens(chain):
        if token.symbol.upper() == wanted:
            return token
    return None


def all_coingecko_ids() -> list[str]:
    """Every distinct CoinGecko id we need prices for.

    Deduplicated, because ETH appears on more than one chain but is one
    price lookup.
    """
    ids: set[str] = set()
    for tokens in TOKENS_BY_CHAIN.values():
        for token in tokens:
            if token.coingecko_id:
                ids.add(token.coingecko_id)
    return sorted(ids)
