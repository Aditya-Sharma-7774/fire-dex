"""Turns raw candles into the indicator snapshot agents and charts consume.

This is the boundary between raw market data and everything above it. The
Technical Analysis Agent receives one of these -- never a price series, and
never a chart. It reasons about numbers this module computed.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.indicators.engine import (
    average_true_range,
    bollinger_bands,
    exponential_moving_average,
    find_divergences,
    macd,
    realised_volatility,
    relative_strength_index,
    simple_moving_average,
)
from app.market.candles import Candle, PROXY_SYMBOLS


class IndicatorSnapshot(BaseModel):
    """Every indicator value at the most recent candle.

    Each field may be None when there was not enough history to compute it.
    None means "not computable", and any agent reading this must say so
    rather than guessing at a value.
    """

    symbol: str
    interval: str
    candle_count: int
    last_close: float
    last_candle_time: datetime

    # When the candles came from a different asset used as a stand-in.
    proxy_for: str | None = Field(
        default=None,
        description="Set when candles are a proxy, e.g. WBTC priced from BTC",
    )

    sma_20: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    ema_12: float | None = None
    ema_26: float | None = None

    rsi_14: float | None = None

    macd_line: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None

    bollinger_upper: float | None = None
    bollinger_middle: float | None = None
    bollinger_lower: float | None = None
    # Where price sits inside the bands: 0 = lower band, 1 = upper band.
    bollinger_position: float | None = None

    realised_volatility: float | None = None

    atr_14: float | None = Field(
        default=None, description="Average true range: typical distance travelled per bar"
    )
    atr_percent: float | None = Field(
        default=None, description="ATR as a percentage of the last close"
    )

    divergence: Literal["bullish", "bearish"] | None = Field(
        default=None,
        description="Most recent price/RSI divergence, if one occurred recently",
    )
    divergence_bars_ago: int | None = Field(
        default=None, description="How many bars back the divergence was confirmed"
    )
    divergence_detail: str | None = Field(
        default=None, description="The two pivots compared, stated so it can be checked"
    )

    support: float | None = Field(default=None, description="Lowest low in the window")
    resistance: float | None = Field(default=None, description="Highest high in the window")

    volume_last: float | None = None
    volume_average: float | None = None
    volume_ratio: float | None = Field(
        default=None, description="Last volume divided by the average"
    )

    price_change_pct: float | None = Field(
        default=None, description="Percent change across the candle window"
    )


class IndicatorSeries(BaseModel):
    """Full indicator series, for charting."""

    symbol: str
    interval: str
    times: list[datetime]
    open: list[float]
    high: list[float]
    low: list[float]
    close: list[float]
    volume: list[float]
    sma_20: list[float | None]
    sma_50: list[float | None]
    ema_12: list[float | None]
    rsi_14: list[float | None]
    macd_line: list[float | None]
    macd_signal: list[float | None]
    macd_histogram: list[float | None]
    bollinger_upper: list[float | None]
    bollinger_lower: list[float | None]


def _last(series: list[float | None]) -> float | None:
    """Most recent computable value, or None."""
    return series[-1] if series and series[-1] is not None else None


def build_snapshot(symbol: str, interval: str, candles: list[Candle]) -> IndicatorSnapshot:
    """Compute every indicator and return only the latest value of each."""
    if not candles:
        raise ValueError("cannot build an indicator snapshot from zero candles")

    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    volumes = [c.volume for c in candles]

    macd_result = macd(closes)
    bands = bollinger_bands(closes, 20)
    rsi_series = relative_strength_index(closes, 14)

    upper = _last(bands.upper)
    lower = _last(bands.lower)
    last_close = closes[-1]

    atr = _last(average_true_range(highs, lows, closes, 14))
    atr_percent = (atr / last_close * 100) if atr is not None and last_close > 0 else None

    # Only the most recent divergence is carried on the snapshot. Older ones
    # are still computable from the series, but an agent given a list would
    # have to decide which mattered, and that decision belongs in code.
    divergences = find_divergences(closes, rsi_series)
    latest = divergences[0] if divergences else None
    divergence_detail = (
        f"price {latest.price_from:,.2f} -> {latest.price_to:,.2f} while "
        f"RSI {latest.rsi_from:.1f} -> {latest.rsi_to:.1f}"
        if latest is not None
        else None
    )

    # Where price sits between the bands. Guard the degenerate case where
    # the bands have collapsed to zero width on a perfectly flat series.
    position: float | None = None
    if upper is not None and lower is not None and upper > lower:
        position = (last_close - lower) / (upper - lower)

    average_volume = sum(volumes) / len(volumes) if volumes else None

    return IndicatorSnapshot(
        symbol=symbol.upper(),
        interval=interval,
        candle_count=len(candles),
        last_close=last_close,
        last_candle_time=candles[-1].open_time,
        proxy_for=PROXY_SYMBOLS.get(symbol.upper()),
        sma_20=_last(simple_moving_average(closes, 20)),
        sma_50=_last(simple_moving_average(closes, 50)),
        sma_200=_last(simple_moving_average(closes, 200)),
        ema_12=_last(exponential_moving_average(closes, 12)),
        ema_26=_last(exponential_moving_average(closes, 26)),
        rsi_14=_last(rsi_series),
        macd_line=_last(macd_result.macd),
        macd_signal=_last(macd_result.signal),
        macd_histogram=_last(macd_result.histogram),
        bollinger_upper=upper,
        bollinger_middle=_last(bands.middle),
        bollinger_lower=lower,
        bollinger_position=position,
        realised_volatility=realised_volatility(closes, 14),
        atr_14=atr,
        atr_percent=atr_percent,
        divergence=latest.kind if latest is not None else None,  # type: ignore[arg-type]
        divergence_bars_ago=latest.bars_ago if latest is not None else None,
        divergence_detail=divergence_detail,
        support=min(lows) if lows else None,
        resistance=max(highs) if highs else None,
        volume_last=volumes[-1] if volumes else None,
        volume_average=average_volume,
        volume_ratio=(
            volumes[-1] / average_volume if average_volume and average_volume > 0 else None
        ),
        price_change_pct=(
            ((closes[-1] - closes[0]) / closes[0]) * 100 if closes[0] > 0 else None
        ),
    )


def build_series(symbol: str, interval: str, candles: list[Candle]) -> IndicatorSeries:
    """Compute full indicator series for charting."""
    closes = [c.close for c in candles]
    macd_result = macd(closes)
    bands = bollinger_bands(closes, 20)

    return IndicatorSeries(
        symbol=symbol.upper(),
        interval=interval,
        times=[c.open_time for c in candles],
        open=[c.open for c in candles],
        high=[c.high for c in candles],
        low=[c.low for c in candles],
        close=closes,
        volume=[c.volume for c in candles],
        sma_20=simple_moving_average(closes, 20),
        sma_50=simple_moving_average(closes, 50),
        ema_12=exponential_moving_average(closes, 12),
        rsi_14=relative_strength_index(closes, 14),
        macd_line=macd_result.macd,
        macd_signal=macd_result.signal,
        macd_histogram=macd_result.histogram,
        bollinger_upper=bands.upper,
        bollinger_lower=bands.lower,
    )


TrendLabel = Literal["strong_uptrend", "uptrend", "sideways", "downtrend", "strong_downtrend"]


def classify_trend(snapshot: IndicatorSnapshot) -> TrendLabel | None:
    """Label the trend from moving-average alignment.

    DELIBERATELY DETERMINISTIC. The rules are fixed and published here, so
    the label can be defended and reproduced. The language model may explain
    what the label implies; it does not decide the label.

    Rules, in order:
      price above both SMAs and SMA20 above SMA50   -> strong uptrend
      price above SMA20                             -> uptrend
      price below both SMAs and SMA20 below SMA50   -> strong downtrend
      price below SMA20                             -> downtrend
      otherwise                                     -> sideways
    """
    price = snapshot.last_close
    sma_20 = snapshot.sma_20
    sma_50 = snapshot.sma_50

    if sma_20 is None:
        return None

    if sma_50 is not None:
        if price > sma_20 and price > sma_50 and sma_20 > sma_50:
            return "strong_uptrend"
        if price < sma_20 and price < sma_50 and sma_20 < sma_50:
            return "strong_downtrend"

    if price > sma_20:
        return "uptrend"
    if price < sma_20:
        return "downtrend"
    return "sideways"
