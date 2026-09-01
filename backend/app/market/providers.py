"""Market data providers.

The application never calls a price website directly. It defines what a
market data provider must be able to do, and plugs a concrete one in behind
that interface. If a provider changes its terms, its rate limits, or
disappears, we swap the implementation and nothing above this layer changes.

Two are implemented:

  CoinGeckoProvider  primary. One request returns price, 24h change, market
                     cap and volume for many assets at once.
  CoinbaseProvider   fallback. Spot price only -- no change or volume -- but
                     it is a completely independent service, so it keeps the
                     dashboard alive when CoinGecko rate limits us.

The fallback is deliberately weaker rather than absent. Partial data,
clearly labelled, beats a blank screen; inventing the missing fields would
not.
"""

from datetime import datetime, timezone
from typing import Protocol

import httpx

from app.core.errors import ProviderError, RateLimitError
from app.core.logging import get_logger
from app.market.types import Price

log = get_logger(__name__)

REQUEST_TIMEOUT = 12.0


class MarketDataProvider(Protocol):
    """What every market data source must be able to do."""

    @property
    def name(self) -> str: ...

    async def get_prices(self, coingecko_ids: list[str]) -> dict[str, Price]:
        """Prices keyed by CoinGecko id.

        A provider may return fewer entries than requested if it does not
        know an asset. It must never invent one.
        """
        ...


class CoinGeckoProvider:
    """Primary provider.

    Free tier, no API key required. Rate limits are strict -- we hit HTTP 429
    after nine rapid requests during development -- so this is always used
    behind the cache, and it batches every id into a single request.
    """

    BASE_URL = "https://api.coingecko.com/api/v3"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    @property
    def name(self) -> str:
        return "coingecko"

    async def get_prices(self, coingecko_ids: list[str]) -> dict[str, Price]:
        if not coingecko_ids:
            return {}

        params = {
            "ids": ",".join(coingecko_ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
            "include_last_updated_at": "true",
        }
        headers = {"User-Agent": "fire-dex/0.1"}
        if self._api_key:
            headers["x-cg-demo-api-key"] = self._api_key

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(
                    f"{self.BASE_URL}/simple/price", params=params, headers=headers
                )
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach CoinGecko.", detail=str(exc)) from exc

        if response.status_code == 429:
            raise RateLimitError(
                "CoinGecko rate limit reached.",
                detail="Free tier allows only a few requests per minute.",
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"CoinGecko returned HTTP {response.status_code}.",
                detail=response.text[:200],
            )

        payload = response.json()
        fetched_at = datetime.now(timezone.utc)
        prices: dict[str, Price] = {}

        for coin_id, entry in payload.items():
            usd = entry.get("usd")
            # A missing price is skipped, not defaulted to zero. Zero would
            # read as "this asset is worthless".
            if usd is None:
                log.warning("price_missing", provider=self.name, coin=coin_id)
                continue

            last_updated = entry.get("last_updated_at")
            prices[coin_id] = Price(
                coingecko_id=coin_id,
                symbol=coin_id,
                usd=float(usd),
                change_24h=entry.get("usd_24h_change"),
                market_cap=entry.get("usd_market_cap"),
                volume_24h=entry.get("usd_24h_vol"),
                data_timestamp=(
                    datetime.fromtimestamp(last_updated, tz=timezone.utc)
                    if last_updated
                    else None
                ),
                fetched_at=fetched_at,
                source=self.name,
            )

        return prices


class CoinbaseProvider:
    """Fallback provider.

    Spot price only. Independent of CoinGecko, so it survives their rate
    limit. Requires one request per asset, which is why it is the fallback
    and not the primary.
    """

    BASE_URL = "https://api.coinbase.com/v2"

    # Coinbase works in ticker symbols, so we need a mapping. Only assets
    # Coinbase actually lists appear here -- anything missing is simply not
    # priced by this provider, which the caller handles.
    ID_TO_TICKER = {
        "ethereum": "ETH",
        "tether": "USDT",
        "usd-coin": "USDC",
        "dai": "DAI",
        "wrapped-bitcoin": "WBTC",
        "chainlink": "LINK",
        "uniswap": "UNI",
        "aave": "AAVE",
        "shiba-inu": "SHIB",
    }

    @property
    def name(self) -> str:
        return "coinbase"

    async def get_prices(self, coingecko_ids: list[str]) -> dict[str, Price]:
        wanted = [(cid, self.ID_TO_TICKER[cid]) for cid in coingecko_ids if cid in self.ID_TO_TICKER]
        if not wanted:
            return {}

        fetched_at = datetime.now(timezone.utc)
        prices: dict[str, Price] = {}

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                for coin_id, ticker in wanted:
                    response = await client.get(f"{self.BASE_URL}/prices/{ticker}-USD/spot")
                    if response.status_code != 200:
                        continue

                    amount = response.json().get("data", {}).get("amount")
                    if amount is None:
                        continue

                    prices[coin_id] = Price(
                        coingecko_id=coin_id,
                        symbol=ticker,
                        usd=float(amount),
                        # Coinbase's spot endpoint gives no change, volume or
                        # market cap. They stay None rather than being faked.
                        change_24h=None,
                        market_cap=None,
                        volume_24h=None,
                        data_timestamp=None,
                        fetched_at=fetched_at,
                        source=self.name,
                    )
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach Coinbase.", detail=str(exc)) from exc

        return prices
