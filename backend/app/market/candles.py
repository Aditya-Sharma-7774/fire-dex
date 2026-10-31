"""OHLCV candle data.

Source: Binance's public klines endpoint. Chosen because it needs no API
key, returns full OHLCV (CoinGecko's free tier gives OHLC without volume),
and allows long histories in one request -- which matters because
indicators need a warm-up period before they produce any value at all.

A 200-period SMA needs 200 candles before its first number exists, so we
always request more history than we intend to display.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.core.errors import ProviderError, RateLimitError
from app.core.logging import get_logger
from app.market.cache import TtlCache

log = get_logger(__name__)

BINANCE_BASE_URL = "https://api.binance.com/api/v3"
REQUEST_TIMEOUT = 15.0

# Candles only change when one closes, so a short cache costs nothing in
# freshness and protects the rate limit during rapid timeframe switching.
_candle_cache: TtlCache[list] = TtlCache(default_ttl_seconds=30.0)


def clear_candle_cache() -> None:
    _candle_cache.clear()


@dataclass
class Candle:
    """One OHLCV bar."""

    open_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


# Timeframes we expose, mapped to Binance's interval codes.
SUPPORTED_INTERVALS = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
    "1w": "1w",
}

# Not every asset we track has a USDT pair, and the ticker is not always the
# same as our symbol. Anything absent here simply has no candle data, which
# the caller reports honestly rather than substituting another asset.
SYMBOL_TO_BINANCE_PAIR = {
    "ETH": "ETHUSDT",
    "WBTC": "BTCUSDT",  # WBTC tracks BTC 1:1; labelled as a proxy to the user
    "LINK": "LINKUSDT",
    "UNI": "UNIUSDT",
    "AAVE": "AAVEUSDT",
    "SHIB": "SHIBUSDT",
    "PEPE": "PEPEUSDT",
    # Added with BNB Smart Chain, Solana and Bitcoin. Every pair was checked
    # to be TRADING on Binance. Two were left out deliberately: DAIUSDT is
    # halted, and mSOL has no pair -- they stay unchartable rather than
    # being given another asset's chart unlabelled.
    "BTC": "BTCUSDT",
    "BNB": "BNBUSDT",
    "SOL": "SOLUSDT",
    "CAKE": "CAKEUSDT",
    "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT",
    "JUP": "JUPUSDT",
    "JTO": "JTOUSDT",
    "PYTH": "PYTHUSDT",
    "RAY": "RAYUSDT",
    "BONK": "BONKUSDT",
    "WIF": "WIFUSDT",
    # Wrapped assets track their underlying 1:1, so they use its chart --
    # always labelled as a proxy to the user.
    "BTCB": "BTCUSDT",
    "WBNB": "BNBUSDT",
    "WSOL": "SOLUSDT",
}

# Symbols where the candle source is a proxy rather than the asset itself.
PROXY_SYMBOLS = {"WBTC": "BTC", "BTCB": "BTC", "WBNB": "BNB", "WSOL": "SOL"}


class CandleProvider:
    """Fetches OHLCV candles."""

    @property
    def name(self) -> str:
        return "binance"

    def supports(self, symbol: str) -> bool:
        return symbol.upper() in SYMBOL_TO_BINANCE_PAIR

    async def get_candles(
        self, symbol: str, interval: str = "1h", limit: int = 300
    ) -> list[Candle]:
        """Candles for one asset, oldest first.

        Raises ProviderError if the asset has no candle source, rather than
        returning an empty list -- silence would be indistinguishable from
        "the market was flat".
        """
        pair = SYMBOL_TO_BINANCE_PAIR.get(symbol.upper())
        if pair is None:
            raise ProviderError(
                f"No candle data source for {symbol}.",
                detail="Stablecoins and some assets have no USDT trading pair we track.",
            )

        binance_interval = SUPPORTED_INTERVALS.get(interval)
        if binance_interval is None:
            raise ProviderError(
                f"Unsupported interval '{interval}'.",
                detail=f"Supported: {', '.join(SUPPORTED_INTERVALS)}",
            )

        limit = max(10, min(limit, 1000))
        cache_key = f"{pair}:{binance_interval}:{limit}"

        cached = _candle_cache.get_fresh(cache_key)
        if cached is not None:
            return [Candle(**c) for c in cached]

        params = {"symbol": pair, "interval": binance_interval, "limit": limit}

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(f"{BINANCE_BASE_URL}/klines", params=params)
        except httpx.HTTPError as exc:
            raise ProviderError("Could not reach the candle provider.", detail=str(exc)) from exc

        if response.status_code == 429:
            raise RateLimitError("Candle provider rate limit reached.")
        if response.status_code >= 400:
            raise ProviderError(
                f"Candle provider returned HTTP {response.status_code}.",
                detail=response.text[:200],
            )

        # Binance returns arrays, not objects. Documented order:
        # [open_time, open, high, low, close, volume, close_time, ...]
        candles = [
            Candle(
                open_time=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
            )
            for row in response.json()
        ]

        _candle_cache.set(cache_key, [c.__dict__ for c in candles])
        log.info("candles_fetched", symbol=symbol, interval=interval, count=len(candles))
        return candles


_provider: CandleProvider | None = None


def get_candle_provider() -> CandleProvider:
    global _provider
    if _provider is None:
        _provider = CandleProvider()
    return _provider
