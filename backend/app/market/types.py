"""Market data types."""

from datetime import datetime

from pydantic import BaseModel, Field


class Price(BaseModel):
    """A price quote for one asset.

    Note the two timestamps, which mean different things:

      data_timestamp  when the price was true, according to the provider
      fetched_at      when we retrieved it

    Keeping them apart matters. A price fetched a second ago may describe a
    market state from a minute ago, and the freshness check needs both. The
    evidence layer in a later phase depends on this distinction.
    """

    coingecko_id: str
    symbol: str
    usd: float
    change_24h: float | None = None
    market_cap: float | None = None
    volume_24h: float | None = None
    data_timestamp: datetime | None = None
    fetched_at: datetime
    source: str = Field(description="Which provider produced this")
    is_stale: bool = Field(
        default=False,
        description="Served from cache past its TTL because refresh failed",
    )


class ProviderHealth(BaseModel):
    """Status of one market data provider."""

    name: str
    reachable: bool
    latency_ms: int | None = None
    error: str | None = None
