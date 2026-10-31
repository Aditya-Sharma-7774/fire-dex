"""Technical indicators, implemented and tested here rather than imported.

WHY WE WROTE THESE OURSELVES
----------------------------
This is the most important file in the project to be able to defend.

The architectural rule is that a language model may never produce a number.
It follows that every number must come from code we can prove correct. So:

  1. These are deterministic. The same candles always give the same RSI.
  2. They are unit tested against worked examples, so "our RSI is right"
     is a demonstrable claim rather than an assertion.
  3. No C toolchain. TA-Lib needs one and is painful on Windows; the main
     pure-Python alternative has maintenance gaps.

The language model's job is to INTERPRET these values. "RSI is 68" is an
observation produced here. "Momentum is elevated" is an interpretation
produced by an agent, and it must cite this observation as evidence.

CONVENTIONS
-----------
Every function takes a list of floats, oldest first, and returns a list of
the same length whose leading entries are None until enough data exists to
compute the indicator. Returning None rather than padding with zeros or
dropping entries keeps each output index aligned with its input candle,
which matters when several indicators are read together.
"""

from dataclasses import dataclass


def simple_moving_average(values: list[float], period: int) -> list[float | None]:
    """SMA: the mean of the last `period` values.

        SMA_t = (v_t + v_{t-1} + ... + v_{t-period+1}) / period
    """
    _validate(values, period)

    out: list[float | None] = [None] * len(values)
    running = 0.0

    for index, value in enumerate(values):
        running += value
        if index >= period:
            running -= values[index - period]
        if index >= period - 1:
            out[index] = running / period

    return out


def exponential_moving_average(values: list[float], period: int) -> list[float | None]:
    """EMA: a weighted average that reacts faster than the SMA.

        multiplier = 2 / (period + 1)
        EMA_t = (v_t - EMA_{t-1}) * multiplier + EMA_{t-1}

    The first EMA value is seeded with the SMA of the first `period` values,
    which is the standard convention.
    """
    _validate(values, period)

    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out

    multiplier = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    out[period - 1] = ema

    for index in range(period, len(values)):
        ema = (values[index] - ema) * multiplier + ema
        out[index] = ema

    return out


def relative_strength_index(values: list[float], period: int = 14) -> list[float | None]:
    """RSI: momentum on a 0-100 scale.

        RS  = average gain / average loss   (over `period`)
        RSI = 100 - (100 / (1 + RS))

    Uses Wilder's smoothing, which is the original definition and what
    charting platforms show:

        avg_gain_t = (avg_gain_{t-1} * (period - 1) + gain_t) / period

    A simple rolling mean gives noticeably different numbers, so this
    distinction matters if the value is going to be quoted as evidence.

    Edge case: when there are no losses in the window, RS is undefined
    (division by zero). RSI is 100 by convention.
    """
    _validate(values, period)

    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, len(values)):
        change = values[index] - values[index - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    out[period] = _rsi_from(avg_gain, avg_loss)

    for index in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        out[index + 1] = _rsi_from(avg_gain, avg_loss)

    return out


def _rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        # No downward movement in the window: momentum is maximal.
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


@dataclass
class MacdResult:
    """MACD line, its signal line, and the histogram between them."""

    macd: list[float | None]
    signal: list[float | None]
    histogram: list[float | None]


def macd(
    values: list[float],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MacdResult:
    """MACD: the gap between a fast and a slow EMA.

        MACD      = EMA(fast) - EMA(slow)
        signal    = EMA(MACD, signal_period)
        histogram = MACD - signal

    The signal line is an EMA *of the MACD line*, so it can only start once
    enough MACD values exist.
    """
    if fast_period >= slow_period:
        raise ValueError("fast_period must be smaller than slow_period")

    fast = exponential_moving_average(values, fast_period)
    slow = exponential_moving_average(values, slow_period)

    macd_line: list[float | None] = [
        None if f is None or s is None else f - s for f, s in zip(fast, slow, strict=True)
    ]

    # Compute the signal EMA over the defined section only, then map the
    # results back to their original indices.
    defined = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    signal_line: list[float | None] = [None] * len(values)

    if len(defined) >= signal_period:
        signal_values = exponential_moving_average([v for _, v in defined], signal_period)
        for (original_index, _), signal_value in zip(defined, signal_values, strict=True):
            signal_line[original_index] = signal_value

    histogram: list[float | None] = [
        None if m is None or s is None else m - s
        for m, s in zip(macd_line, signal_line, strict=True)
    ]

    return MacdResult(macd=macd_line, signal=signal_line, histogram=histogram)


@dataclass
class BollingerResult:
    upper: list[float | None]
    middle: list[float | None]
    lower: list[float | None]


def bollinger_bands(
    values: list[float], period: int = 20, std_dev: float = 2.0
) -> BollingerResult:
    """Bollinger Bands: an SMA with volatility bands either side.

        middle = SMA(period)
        upper  = middle + std_dev * sigma
        lower  = middle - std_dev * sigma

    sigma is the POPULATION standard deviation over the same window
    (divide by n, not n-1), which is the standard definition for this
    indicator.
    """
    _validate(values, period)

    middle = simple_moving_average(values, period)
    upper: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)

    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        mean = middle[index]
        assert mean is not None  # guaranteed by the SMA above
        variance = sum((v - mean) ** 2 for v in window) / period
        sigma = variance**0.5
        upper[index] = mean + std_dev * sigma
        lower[index] = mean - std_dev * sigma

    return BollingerResult(upper=upper, middle=middle, lower=lower)


def realised_volatility(values: list[float], period: int = 14) -> float | None:
    """Annualised volatility from log returns over the last `period` values.

    Feeds the risk score. Crypto trades continuously, so we annualise with
    365 rather than the 252 trading days used for equities.
    """
    if len(values) < period + 1:
        return None

    import math

    window = values[-(period + 1) :]
    returns = [
        math.log(window[i] / window[i - 1])
        for i in range(1, len(window))
        if window[i] > 0 and window[i - 1] > 0
    ]
    if len(returns) < 2:
        return None

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return (variance**0.5) * math.sqrt(365)


def average_true_range(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[float | None]:
    """ATR: how far price typically travels in one bar.

        TR  = max(high - low,
                  |high - previous close|,
                  |low  - previous close|)
        ATR = Wilder-smoothed mean of TR over `period`

    Wilder defined both this and the RSI, and both use the same smoothing,
    so the recursion below is deliberately identical to the one in
    `relative_strength_index`.

    WHY THIS IS NOT JUST ANOTHER VOLATILITY NUMBER
    ----------------------------------------------
    Realised volatility measures dispersion of returns. ATR measures the
    distance price actually covers, including the gaps between one bar's
    close and the next bar's range -- which dispersion of closes cannot see.
    That distinction is what makes it the right input for a stop distance or
    a position size, and why it is worth having alongside the existing
    volatility figure rather than instead of it.

    The three series must be the same length. The first element has no
    previous close, so true range there falls back to the bar's own range.
    """
    _validate(closes, period)
    if not (len(highs) == len(lows) == len(closes)):
        raise ValueError("highs, lows and closes must be the same length")

    out: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return out

    true_ranges: list[float] = []
    for index in range(len(closes)):
        if index == 0:
            true_ranges.append(highs[index] - lows[index])
            continue
        previous_close = closes[index - 1]
        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - previous_close),
                abs(lows[index] - previous_close),
            )
        )

    atr = sum(true_ranges[1 : period + 1]) / period
    out[period] = atr

    for index in range(period + 1, len(true_ranges)):
        atr = (atr * (period - 1) + true_ranges[index]) / period
        out[index] = atr

    return out


@dataclass
class Divergence:
    """A disagreement between price and momentum.

    `bullish` means price made a lower low while the RSI made a higher low:
    the move down is losing force. `bearish` is the mirror -- a higher high
    in price on a lower high in RSI.
    """

    kind: str  # "bullish" or "bearish"
    #: Indices of the two price pivots compared.
    from_index: int
    to_index: int
    price_from: float
    price_to: float
    rsi_from: float
    rsi_to: float
    #: How many bars ago the later pivot was, counting back from the end.
    bars_ago: int


def find_pivots(values: list[float], width: int = 3) -> tuple[list[int], list[int]]:
    """Indices of local highs and lows.

    A bar is a pivot high when no bar within `width` on either side is
    higher, and a pivot low when none is lower. Requiring confirmation on
    BOTH sides is what keeps this honest: a pivot is only known `width` bars
    after it happened, so the most recent `width` bars can never be pivots.
    A one-sided test would mark the final bar as a pivot and make the
    divergence look visible earlier than it really was.
    """
    if width < 1:
        raise ValueError("width must be at least 1")

    highs: list[int] = []
    lows: list[int] = []

    for index in range(width, len(values) - width):
        window = values[index - width : index + width + 1]
        centre = values[index]
        if centre == max(window) and window.count(centre) == 1:
            highs.append(index)
        elif centre == min(window) and window.count(centre) == 1:
            lows.append(index)

    return highs, lows


def find_divergences(
    closes: list[float],
    rsi: list[float | None],
    *,
    width: int = 3,
    lookback: int = 60,
    max_results: int = 4,
) -> list[Divergence]:
    """Price and RSI pivots that disagree, most recent first.

    Only pivots within the last `lookback` bars are considered, because a
    divergence from three hundred bars ago says nothing about now.
    """
    if len(closes) != len(rsi):
        raise ValueError("closes and rsi must be the same length")

    highs, lows = find_pivots(closes, width)
    cutoff = max(0, len(closes) - lookback)
    found: list[Divergence] = []

    def rsi_at(index: int) -> float | None:
        value = rsi[index]
        return value

    # Bearish: higher high in price, lower high in RSI.
    recent_highs = [i for i in highs if i >= cutoff]
    for later, earlier in _consecutive_pairs(recent_highs):
        a, b = rsi_at(earlier), rsi_at(later)
        if a is None or b is None:
            continue
        if closes[later] > closes[earlier] and b < a:
            found.append(
                Divergence(
                    "bearish", earlier, later, closes[earlier], closes[later],
                    a, b, len(closes) - 1 - later,
                )
            )

    # Bullish: lower low in price, higher low in RSI.
    recent_lows = [i for i in lows if i >= cutoff]
    for later, earlier in _consecutive_pairs(recent_lows):
        a, b = rsi_at(earlier), rsi_at(later)
        if a is None or b is None:
            continue
        if closes[later] < closes[earlier] and b > a:
            found.append(
                Divergence(
                    "bullish", earlier, later, closes[earlier], closes[later],
                    a, b, len(closes) - 1 - later,
                )
            )

    found.sort(key=lambda d: d.bars_ago)
    return found[:max_results]


def _consecutive_pairs(indices: list[int]) -> list[tuple[int, int]]:
    """(later, earlier) for each adjacent pair, newest first.

    Only adjacent pivots are compared. Comparing every pivot against every
    other would find a "divergence" somewhere in almost any series.
    """
    return [(indices[i], indices[i - 1]) for i in range(len(indices) - 1, 0, -1)]


def _validate(values: list[float], period: int) -> None:
    if period < 1:
        raise ValueError("period must be at least 1")
    if not isinstance(values, list):
        raise TypeError("values must be a list of floats")
