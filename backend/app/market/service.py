"""Market data service: cache, then primary provider, then fallback.

The lookup order is deliberate:

  1. Fresh cache        -- free, instant, and protects the rate limit
  2. Primary provider   -- CoinGecko, full data
  3. Fallback provider  -- Coinbase, price only, independent service
  4. Stale cache        -- last known value, FLAGGED AS STALE
  5. Nothing            -- the asset is reported as unpriced

Step 4 is the interesting one. When everything fails we would rather show a
two-minute-old price labelled "stale" than a blank screen. What we will not
do is show it unlabelled. Step 5 exists because "we do not know this price"
is a legitimate answer, and far better than a fabricated one.
"""

import asyncio

from app.core.logging import get_logger
from app.market.cache import TtlCache
from app.market.providers import CoinbaseProvider, CoinGeckoProvider, MarketDataProvider
from app.market.types import Price

log = get_logger(__name__)

# Crypto prices move constantly, but not meaningfully within 45 seconds for
# an analysis dashboard. This TTL keeps us comfortably inside the free tier
# while the data still reads as live.
PRICE_TTL_SECONDS = 45.0

# Past this age a cached price is no longer worth showing at all.
MAX_STALE_AGE_SECONDS = 900.0  # 15 minutes

# Refresh slightly before the TTL expires so an entry is replaced while it
# is still fresh. This is what keeps user requests off the network path.
REFRESH_INTERVAL_SECONDS = 40.0


class MarketDataService:
    """Fetches prices with caching and provider fallback."""

    def __init__(
        self,
        primary: MarketDataProvider | None = None,
        fallback: MarketDataProvider | None = None,
        cache: TtlCache[Price] | None = None,
    ) -> None:
        # `is None` rather than `or`. TtlCache implements __len__, so an
        # empty cache is falsy -- `cache or TtlCache(...)` would silently
        # discard an injected empty cache and build a second one, which is
        # exactly the kind of bug that only shows up under load or in tests.
        self._primary = primary if primary is not None else CoinGeckoProvider()
        self._fallback = fallback if fallback is not None else CoinbaseProvider()
        self._cache: TtlCache[Price] = (
            cache if cache is not None else TtlCache(default_ttl_seconds=PRICE_TTL_SECONDS)
        )

    async def get_prices(self, coingecko_ids: list[str]) -> dict[str, Price]:
        """Prices for the given ids. May return fewer than requested."""
        if not coingecko_ids:
            return {}

        result: dict[str, Price] = {}
        missing: list[str] = []

        # 1. fresh cache
        for coin_id in coingecko_ids:
            cached = self._cache.get_fresh(coin_id)
            if cached is not None:
                result[coin_id] = cached
            else:
                missing.append(coin_id)

        if not missing:
            return result

        # 2. primary provider
        fetched = await self._try_provider(self._primary, missing)
        result.update(fetched)
        missing = [c for c in missing if c not in fetched]

        # 3. fallback provider
        if missing:
            log.info("falling_back", provider=self._fallback.name, assets=len(missing))
            fetched = await self._try_provider(self._fallback, missing)
            result.update(fetched)
            missing = [c for c in missing if c not in fetched]

        # 4. stale cache, clearly flagged
        for coin_id in missing:
            stale = self._cache.get_stale(coin_id)
            if stale is None:
                continue
            value, age = stale
            if age > MAX_STALE_AGE_SECONDS:
                log.warning("stale_price_too_old", coin=coin_id, age_seconds=round(age))
                continue

            log.warning("serving_stale_price", coin=coin_id, age_seconds=round(age))
            result[coin_id] = value.model_copy(update={"is_stale": True})

        # 5. anything still missing is simply absent from the result, and the
        #    caller reports it as unpriced.
        return result

    async def warm(self) -> int:
        """Populate the cache before anyone asks.

        The first page load was paying for a cold CoinGecko round trip
        (~1-1.5s) while the user watched a skeleton. Fetching once at
        startup makes that first request a cache hit instead.

        Returns how many assets were primed. Never raises: a failure here
        just means the first request pays what it used to.
        """
        from app.tokens.registry import all_coingecko_ids

        try:
            prices = await self.get_prices(all_coingecko_ids())
            log.info("price_cache_warmed", assets=len(prices))
            return len(prices)
        except Exception as exc:  # noqa: BLE001
            log.warning("price_cache_warm_failed", error=str(exc))
            return 0

    async def keep_warm(self, interval_seconds: float = REFRESH_INTERVAL_SECONDS) -> None:
        """Refresh the cache just before it expires, forever.

        With a 45-second TTL and a 40-second refresh, an entry is replaced
        while it is still fresh, so a user request is essentially always a
        cache hit. Without this, whoever asks first after each expiry pays
        the network cost on everyone else's behalf.

        Runs as a background task for the life of the process.
        """
        from app.tokens.registry import all_coingecko_ids

        while True:
            await asyncio.sleep(interval_seconds)
            try:
                # Force a refresh by bypassing the fresh-cache check: ask
                # the provider directly and overwrite what is stored.
                await self._try_provider(self._primary, all_coingecko_ids())
            except Exception as exc:  # noqa: BLE001
                log.warning("price_refresh_failed", error=str(exc))

    async def _try_provider(
        self, provider: MarketDataProvider, coin_ids: list[str]
    ) -> dict[str, Price]:
        """Call a provider, caching what it returns. Never raises."""
        try:
            prices = await provider.get_prices(coin_ids)
        except Exception as exc:  # noqa: BLE001 - deliberately broad
            # A provider failing must not take down the request. We log it
            # and let the caller fall through to the next option.
            log.warning("provider_failed", provider=provider.name, error=str(exc))
            return {}

        for coin_id, price in prices.items():
            self._cache.set(coin_id, price)

        return prices


# One instance for the process, so the cache is actually shared between
# requests. Injected via FastAPI's dependency system so tests can replace it.
_service: MarketDataService | None = None


def get_market_service() -> MarketDataService:
    global _service
    if _service is None:
        _service = MarketDataService()
    return _service
