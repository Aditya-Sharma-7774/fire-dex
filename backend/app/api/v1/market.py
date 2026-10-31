"""Token, price and portfolio endpoints."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.v1.params import AddressPath, ChainPath, Interval, SymbolPath
from app.backtest.engine import (
    DEFAULT_HORIZON,
    DEFAULT_WARMUP,
    BacktestResult,
    run_backtest,
)
from app.blockchain.factory import get_adapter
from app.config import Settings, get_settings
from app.core.errors import ProviderError
from app.indicators.service import (
    IndicatorSeries,
    IndicatorSnapshot,
    build_series,
    build_snapshot,
)
from app.market.candles import get_candle_provider
from app.market.service import MarketDataService, get_market_service
from app.market.types import Price
from app.services.portfolio import build_portfolio
from app.tokens.registry import all_coingecko_ids, list_tokens
from app.tokens.types import PortfolioSnapshot, TokenConfig

router = APIRouter(tags=["market"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
MarketDep = Annotated[MarketDataService, Depends(get_market_service)]

# ponytail: one process-wide gate. Per-client limits need real rate limiting,
# which a localhost-only service does not yet warrant.
_backtest_gate = asyncio.Semaphore(1)


@router.get("/tokens/{chain}", response_model=list[TokenConfig])
async def get_tokens(
    chain: ChainPath,
) -> list[TokenConfig]:
    """Every token we track on a chain, with verified contract metadata."""
    return list_tokens(chain)


@router.get("/market/prices", response_model=dict[str, Price])
async def get_prices(
    market: MarketDep,
    ids: Annotated[
        str | None,
        Query(description="Comma-separated CoinGecko ids. Omit for everything we track."),
    ] = None,
) -> dict[str, Price]:
    """Current USD prices.

    An asset we could not price is simply absent from the response rather
    than being returned with a zero or a guessed value. Each entry carries
    its source and an `is_stale` flag.
    """
    wanted = [i.strip() for i in ids.split(",") if i.strip()] if ids else all_coingecko_ids()
    return await market.get_prices(wanted)


@router.get("/portfolio/{chain}/{address}", response_model=PortfolioSnapshot)
async def get_portfolio(
    chain: ChainPath,
    address: AddressPath,
    settings: SettingsDep,
    market: MarketDep,
    include_zero: Annotated[
        bool, Query(description="Include tokens with a zero balance")
    ] = False,
) -> PortfolioSnapshot:
    """Every tracked token held by an address on a chain, valued in USD.

    Balances come from the chain; prices come from the market layer. Where
    either is unavailable the holding is reported as unpriced or unavailable
    -- never zero-filled.
    """
    adapter = get_adapter(chain, settings)
    return await build_portfolio(
        chain=chain,
        address=address,
        adapter=adapter,
        market=market,
        include_zero_balances=include_zero,
    )


@router.get("/candles/{symbol}", response_model=IndicatorSeries)
async def get_candles(
    symbol: SymbolPath,
    interval: Annotated[Interval, Query(description="Candle timeframe")] = "1h",
    limit: Annotated[int, Query(ge=50, le=1000, description="Number of candles")] = 300,
) -> IndicatorSeries:
    """OHLCV candles with indicator series, for charting.

    Indicators are computed by our own tested engine, never by a model.
    """
    candles = await get_candle_provider().get_candles(symbol, interval, limit)
    return build_series(symbol, interval, candles)


@router.get("/indicators/{symbol}", response_model=IndicatorSnapshot)
async def get_indicators(
    symbol: SymbolPath,
    interval: Annotated[Interval, Query(description="Candle timeframe")] = "1h",
) -> IndicatorSnapshot:
    """Latest value of every indicator for one asset.

    This is exactly what the Technical Analysis Agent receives. It never
    sees a price series or a chart -- only these computed numbers, which it
    may interpret but must cite.
    """
    candles = await get_candle_provider().get_candles(symbol, interval, 300)
    return build_snapshot(symbol, interval, candles)


@router.get("/backtest/{symbol}", response_model=BacktestResult)
async def get_backtest(
    symbol: SymbolPath,
    interval: Annotated[Interval, Query(description="Candle timeframe")] = "1d",
    horizon: Annotated[
        int, Query(ge=1, le=200, description="Bars ahead used to judge each signal")
    ] = DEFAULT_HORIZON,
    step: Annotated[
        int | None,
        Query(
            ge=1,
            le=200,
            description="Sample every nth bar. Defaults to the horizon, giving disjoint windows.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=300, le=1000, description="Candles of history")] = 1000,
) -> BacktestResult:
    """Replay the signal engine over history and score what it said.

    This is the only endpoint in the project that reports anything resembling
    predictive accuracy, and it never reports one alone: `baseline_accuracy`
    is what always saying "buy" would have scored on the same bars, and
    `edge` is the difference. `caveats` lists what the number does not
    account for. Read all three or none of them.
    """
    # Default to disjoint windows: overlapping ones inflate the apparent
    # sample without adding independent evidence.
    effective_step = step if step is not None else horizon

    candles = await get_candle_provider().get_candles(symbol, interval, limit)
    if len(candles) <= DEFAULT_WARMUP + horizon:
        raise ProviderError(
            f"Not enough history to backtest {symbol} on the {interval} timeframe.",
            detail=(
                f"Got {len(candles)} candles; need more than "
                f"{DEFAULT_WARMUP + horizon} for a {horizon}-bar horizon."
            ),
        )

    # The replay is CPU-bound. Run on the event loop it would stall every
    # other request, and as a GET it can be triggered from any web page by
    # an <img> tag. So it runs on a worker thread, one at a time.
    async with _backtest_gate:
        return await asyncio.to_thread(
            run_backtest, symbol, interval, candles, horizon_bars=horizon, step=effective_step
        )
