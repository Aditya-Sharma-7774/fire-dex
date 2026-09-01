"""Directional signal, computed deterministically from indicator votes.

WHY THIS IS NOT AN LLM OUTPUT
-----------------------------
The obvious way to produce a buy/sell suggestion is to ask the model. That
answer cannot be defended: "why does it say Buy?" has no reply except "the
model said so", and the same evidence could produce a different answer on
the next run.

So the signal is a VOTE COUNT over indicators, using published thresholds.
This is the same approach TradingView uses for its Technical Rating, and it
has three properties the model-generated version lacks:

  1. Deterministic  - identical evidence always produces the identical signal
  2. Explainable    - every vote can be listed with the value behind it
  3. Auditable      - the thresholds are in this file and can be argued with

The language model's job is to EXPLAIN this signal in plain language and
say how well grounded it is. It does not choose it.

WHAT THIS IS NOT
----------------
It is not financial advice, and the interface says so next to every signal.
It is a summary of what a set of conventional technical indicators currently
agree on, which is a statement about indicator readings, not a prediction
about price.
"""

from dataclasses import dataclass, field
from enum import Enum

from app.indicators.service import IndicatorSnapshot


class Direction(str, Enum):
    """Which way one indicator is currently leaning."""

    BUY = "buy"
    SELL = "sell"
    NEUTRAL = "neutral"


class Signal(str, Enum):
    """The aggregate rating."""

    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


@dataclass
class Vote:
    """One indicator's contribution to the signal."""

    indicator: str
    direction: Direction
    #: The measured value that produced this vote.
    value: float | None
    #: The rule applied, stated plainly so it can be checked.
    rule: str
    #: Which group this vote belongs to.
    group: str


@dataclass
class SignalResult:
    signal: Signal
    #: -1.0 (all sell) .. +1.0 (all buy)
    score: float
    buy_votes: int
    sell_votes: int
    neutral_votes: int
    votes: list[Vote] = field(default_factory=list)
    #: Fraction of indicators that could be evaluated at all.
    coverage: float = 1.0
    note: str = ""

    @property
    def total_directional(self) -> int:
        return self.buy_votes + self.sell_votes


# Conventional thresholds. These are the standard published levels, stated
# here so they are arguable rather than hidden inside a prompt.
RSI_OVERSOLD = 30.0
RSI_OVERBOUGHT = 70.0
BOLLINGER_LOW = 0.20
BOLLINGER_HIGH = 0.80

# Rating bands over the vote score.
STRONG_THRESHOLD = 0.50
LEAN_THRESHOLD = 0.15


def compute_signal(snapshot: IndicatorSnapshot | None) -> SignalResult | None:
    """Aggregate indicator votes into a directional signal.

    Returns None when nothing could be evaluated -- reported as "no signal",
    never as NEUTRAL, because "we could not tell" and "the indicators
    disagree evenly" are different statements.
    """
    if snapshot is None:
        return None

    votes: list[Vote] = []
    price = snapshot.last_close

    # ---------------- oscillators ----------------

    if snapshot.rsi_14 is not None:
        rsi = snapshot.rsi_14
        if rsi < RSI_OVERSOLD:
            direction, rule = Direction.BUY, f"RSI {rsi:.1f} is below the oversold level of {RSI_OVERSOLD:.0f}"
        elif rsi > RSI_OVERBOUGHT:
            direction, rule = Direction.SELL, f"RSI {rsi:.1f} is above the overbought level of {RSI_OVERBOUGHT:.0f}"
        else:
            direction, rule = Direction.NEUTRAL, f"RSI {rsi:.1f} sits between {RSI_OVERSOLD:.0f} and {RSI_OVERBOUGHT:.0f}"
        votes.append(Vote("RSI (14)", direction, rsi, rule, "oscillator"))

    if snapshot.macd_histogram is not None:
        hist = snapshot.macd_histogram
        if hist > 0:
            direction, rule = Direction.BUY, "MACD histogram is positive (MACD above its signal line)"
        elif hist < 0:
            direction, rule = Direction.SELL, "MACD histogram is negative (MACD below its signal line)"
        else:
            direction, rule = Direction.NEUTRAL, "MACD is level with its signal line"
        votes.append(Vote("MACD histogram", direction, hist, rule, "oscillator"))

    if snapshot.bollinger_position is not None:
        pos = snapshot.bollinger_position
        if pos < BOLLINGER_LOW:
            direction, rule = Direction.BUY, f"Price sits in the lowest {BOLLINGER_LOW:.0%} of the Bollinger band range"
        elif pos > BOLLINGER_HIGH:
            direction, rule = Direction.SELL, f"Price sits in the highest {1 - BOLLINGER_HIGH:.0%} of the Bollinger band range"
        else:
            direction, rule = Direction.NEUTRAL, "Price sits in the middle of the Bollinger band range"
        votes.append(Vote("Bollinger position", direction, pos, rule, "oscillator"))

    # ---------------- moving averages ----------------
    # Each is a simple "is price above or below" vote. Individually weak;
    # the point is agreement across several of them.

    for label, value in [
        ("SMA (20)", snapshot.sma_20),
        ("SMA (50)", snapshot.sma_50),
        ("SMA (200)", snapshot.sma_200),
    ]:
        if value is None:
            continue
        if price > value:
            direction, rule = Direction.BUY, f"Price {price:,.2f} is above {label} at {value:,.2f}"
        elif price < value:
            direction, rule = Direction.SELL, f"Price {price:,.2f} is below {label} at {value:,.2f}"
        else:
            direction, rule = Direction.NEUTRAL, f"Price is level with {label}"
        votes.append(Vote(label, direction, value, rule, "moving average"))

    if snapshot.ema_12 is not None and snapshot.ema_26 is not None:
        fast, slow = snapshot.ema_12, snapshot.ema_26
        if fast > slow:
            direction, rule = Direction.BUY, f"EMA(12) {fast:,.2f} is above EMA(26) {slow:,.2f}"
        elif fast < slow:
            direction, rule = Direction.SELL, f"EMA(12) {fast:,.2f} is below EMA(26) {slow:,.2f}"
        else:
            direction, rule = Direction.NEUTRAL, "EMA(12) is level with EMA(26)"
        votes.append(Vote("EMA cross", direction, fast - slow, rule, "moving average"))

    if not votes:
        return None

    buy = sum(1 for v in votes if v.direction is Direction.BUY)
    sell = sum(1 for v in votes if v.direction is Direction.SELL)
    neutral = sum(1 for v in votes if v.direction is Direction.NEUTRAL)

    # Neutral votes are counted in the denominator on purpose. Six
    # indicators of which two say buy and four say nothing is a much weaker
    # signal than two out of two, and the score should reflect that.
    score = (buy - sell) / len(votes)

    if score >= STRONG_THRESHOLD:
        signal = Signal.STRONG_BUY
    elif score >= LEAN_THRESHOLD:
        signal = Signal.BUY
    elif score <= -STRONG_THRESHOLD:
        signal = Signal.STRONG_SELL
    elif score <= -LEAN_THRESHOLD:
        signal = Signal.SELL
    else:
        signal = Signal.NEUTRAL

    # Eight indicators are possible in total; fewer means less history.
    coverage = len(votes) / 8.0
    note = ""
    if coverage < 0.75:
        note = (
            f"Only {len(votes)} of 8 indicators could be evaluated -- "
            "not enough price history for the rest."
        )

    return SignalResult(
        signal=signal,
        score=round(score, 4),
        buy_votes=buy,
        sell_votes=sell,
        neutral_votes=neutral,
        votes=votes,
        coverage=round(min(coverage, 1.0), 3),
        note=note,
    )


def describe_signal(result: SignalResult) -> str:
    """One plain sentence summarising the vote, for the prompt and the UI."""
    return (
        f"{result.signal.value.replace('_', ' ').title()} "
        f"({result.buy_votes} buy, {result.sell_votes} sell, "
        f"{result.neutral_votes} neutral out of {len(result.votes)} indicators)"
    )
