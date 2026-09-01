"""Token and balance types."""

from datetime import datetime

from pydantic import BaseModel, Field


class TokenConfig(BaseModel):
    """Metadata for one token on one chain.

    A token is identified by (chain, address). The same symbol on two chains
    is two different tokens -- "USDC on Ethereum" and "USDC on Solana" are
    separate contracts, and treating them as one would be wrong.
    """

    symbol: str
    name: str
    chain: str
    address: str | None = Field(
        default=None,
        description="Contract address. None for the chain's native asset.",
    )
    decimals: int = Field(description="Read from the contract, never assumed")
    coingecko_id: str | None = Field(
        default=None, description="Price lookup key; None if we cannot price it"
    )
    is_native: bool
    is_stablecoin: bool


class TokenBalance(BaseModel):
    """A held amount of one token."""

    symbol: str
    name: str
    chain: str
    address: str | None
    decimals: int
    is_native: bool
    raw: str = Field(description="Exact amount in the smallest unit, as a string")
    formatted: str
    # Value fields are None when we have no price. They are never zero-filled:
    # "we do not know" and "it is worth nothing" are different statements.
    price_usd: float | None = None
    value_usd: float | None = None
    change_24h: float | None = None
    price_is_stale: bool = False


class PortfolioSnapshot(BaseModel):
    """Everything one address holds on one chain, at one moment."""

    chain: str
    address: str
    balances: list[TokenBalance]
    total_value_usd: float | None = Field(
        default=None,
        description="Sum of priced holdings. None if no holding could be priced.",
    )
    priced_count: int = Field(description="How many holdings we could price")
    unpriced_count: int = Field(description="How many we could not")
    fetched_at: datetime
    contains_stale_prices: bool = Field(
        default=False,
        description="True when at least one price came from stale cache",
    )
