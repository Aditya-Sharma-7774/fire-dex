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


# BNB Smart Chain. Verified the same two-source way: symbol() and decimals()
# read from each contract on-chain, and CoinGecko's contract lookup mapping
# the same address to the same coin.
#
# The decimals are the point of this list. The same asset has different
# decimals on different chains: USDT and USDC are 6 on Ethereum but 18 here,
# and Bitcoin is 8 as WBTC but 18 as BTCB. Reusing Ethereum's values would
# misreport a USDT balance by a factor of 10^12. DOGE is 8 even here.
#
# CoinGecko prices these as separate bridged assets, not as the originals,
# so each uses the id CoinGecko returned for its exact address.
BSC_TOKENS: list[TokenConfig] = [
    TokenConfig(
        symbol="BNB",
        name="BNB",
        chain="bsc",
        address=None,
        decimals=18,
        coingecko_id="binancecoin",
        is_native=True,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="WBNB",
        name="Wrapped BNB",
        chain="bsc",
        address="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        decimals=18,
        coingecko_id="wbnb",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="USDT",
        name="Tether USD (Binance-bridged)",
        chain="bsc",
        address="0x55d398326f99059fF775485246999027B3197955",
        decimals=18,
        coingecko_id="binance-bridged-usdt-bnb-smart-chain",
        is_native=False,
        is_stablecoin=True,
    ),
    TokenConfig(
        symbol="USDC",
        name="USD Coin (Binance-bridged)",
        chain="bsc",
        address="0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
        decimals=18,
        coingecko_id="binance-bridged-usdc-bnb-smart-chain",
        is_native=False,
        is_stablecoin=True,
    ),
    TokenConfig(
        symbol="FDUSD",
        name="First Digital USD",
        chain="bsc",
        address="0xc5f0f7b66764F6ec8C8Dff7BA683102295E16409",
        decimals=18,
        coingecko_id="first-digital-usd",
        is_native=False,
        is_stablecoin=True,
    ),
    TokenConfig(
        symbol="DAI",
        name="Dai (Binance-Peg)",
        chain="bsc",
        address="0x1AF3F329e8BE154074D8769D1FFa4eE058B1DBc3",
        decimals=18,
        coingecko_id="binance-peg-dai",
        is_native=False,
        is_stablecoin=True,
    ),
    TokenConfig(
        symbol="BTCB",
        name="Bitcoin BEP2 (Binance-Peg)",
        chain="bsc",
        address="0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c",
        decimals=18,
        coingecko_id="binance-bitcoin",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="ETH",
        name="Ethereum (Binance-Peg)",
        chain="bsc",
        address="0x2170Ed0880ac9A755fd29B2688956BD959F933F8",
        decimals=18,
        coingecko_id="binance-peg-weth",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="CAKE",
        name="PancakeSwap",
        chain="bsc",
        address="0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82",
        decimals=18,
        coingecko_id="pancakeswap-token",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="XRP",
        name="XRP (Binance-Peg)",
        chain="bsc",
        address="0x1D2F0da169ceB9fC7B3144628dB156f3F6c60dBE",
        decimals=18,
        coingecko_id="binance-peg-xrp",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="DOGE",
        name="Dogecoin (Binance-Peg)",
        chain="bsc",
        address="0xbA2aE424d960c26247Dd6c32edC70B295c744C43",
        decimals=8,
        coingecko_id="binance-peg-dogecoin",
        is_native=False,
        is_stablecoin=False,
    ),
]

# Solana. Decimals read from each mint account on-chain, and each mint mapped
# to its coin by CoinGecko. BONK uses 5 decimals and JTO and mSOL use 9.
#
# mSOL is not priced as SOL. It is staked SOL that accrues rewards, and at
# verification it traded at $159 against SOL's $113 -- pricing it 1:1 would
# understate it by about 40%.
SOLANA_TOKENS: list[TokenConfig] = [
    TokenConfig(
        symbol="SOL",
        name="Solana",
        chain="solana",
        address=None,
        decimals=9,
        coingecko_id="solana",
        is_native=True,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="USDC",
        name="USD Coin",
        chain="solana",
        address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        decimals=6,
        coingecko_id="usd-coin",
        is_native=False,
        is_stablecoin=True,
    ),
    TokenConfig(
        symbol="USDT",
        name="Tether USD",
        chain="solana",
        address="Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        decimals=6,
        coingecko_id="tether",
        is_native=False,
        is_stablecoin=True,
    ),
    TokenConfig(
        symbol="wSOL",
        name="Wrapped SOL",
        chain="solana",
        address="So11111111111111111111111111111111111111112",
        decimals=9,
        coingecko_id="wrapped-solana",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="mSOL",
        name="Marinade Staked SOL",
        chain="solana",
        address="mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
        decimals=9,
        coingecko_id="msol",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="JUP",
        name="Jupiter",
        chain="solana",
        address="JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        decimals=6,
        coingecko_id="jupiter-exchange-solana",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="JTO",
        name="Jito",
        chain="solana",
        address="jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
        decimals=9,
        coingecko_id="jito-governance-token",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="PYTH",
        name="Pyth Network",
        chain="solana",
        address="HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
        decimals=6,
        coingecko_id="pyth-network",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="RAY",
        name="Raydium",
        chain="solana",
        address="4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R",
        decimals=6,
        coingecko_id="raydium",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="BONK",
        name="Bonk",
        chain="solana",
        address="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        decimals=5,
        coingecko_id="bonk",
        is_native=False,
        is_stablecoin=False,
    ),
    TokenConfig(
        symbol="WIF",
        name="dogwifhat",
        chain="solana",
        address="EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
        decimals=6,
        coingecko_id="dogwifcoin",
        is_native=False,
        is_stablecoin=False,
    ),
]

# Bitcoin has no tokens: there is no general-purpose contract layer to hold them.
BITCOIN_TOKENS: list[TokenConfig] = [
    TokenConfig(
        symbol="BTC",
        name="Bitcoin",
        chain="bitcoin",
        address=None,
        decimals=8,
        coingecko_id="bitcoin",
        is_native=True,
        is_stablecoin=False,
    ),
]

TOKENS_BY_CHAIN: dict[str, list[TokenConfig]] = {
    "ethereum": ETHEREUM_TOKENS,
    "sepolia": SEPOLIA_TOKENS,
    "bsc": BSC_TOKENS,
    "solana": SOLANA_TOKENS,
    "bitcoin": BITCOIN_TOKENS,
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


# Where to look first when a symbol exists on several chains. BSC comes last
# because its tokens are bridged copies that CoinGecko prices separately from
# the originals: "USDT" should mean Tether, not Binance's bridged USDT.
ASSET_LOOKUP_ORDER = ["ethereum", "bitcoin", "solana", "bsc"]


def find_asset(symbol: str) -> TokenConfig | None:
    """The canonical token for a symbol, across every chain.

    Used when analysing an asset rather than a wallet. A chain's native asset
    wins outright -- "ETH" is Ether, not the Binance-Peg copy on BSC -- and
    otherwise the first match in ASSET_LOOKUP_ORDER.
    """
    wanted = symbol.upper()
    matches = [
        token
        for chain in ASSET_LOOKUP_ORDER
        for token in TOKENS_BY_CHAIN[chain]
        if token.symbol.upper() == wanted
    ]
    natives = [token for token in matches if token.is_native]
    return (natives or matches or [None])[0]


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
