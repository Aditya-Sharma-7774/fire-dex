"""Replay the signal engine over history and score what it said.

WHY THIS EXISTS
---------------
Everywhere else this project refuses to claim predictive accuracy, because
accuracy needs ground truth and we had none. This module supplies it: for
each historical bar it recomputes the signal from only the data available at
that bar, then looks at what price actually did next.

That turns "we make no accuracy claim" into a measured number -- but only if
the measurement is honest about three things, so all three are enforced
here rather than left to the caller.

  1. NO LOOKAHEAD. The snapshot at bar t is built from candles[:t+1] and
     nothing later. This is the single way a backtest most often lies, and
     the one thing worth paying O(n^2) to be sure of.

  2. A BASELINE. "55% accurate" is meaningless alone. If price rose over
     53% of windows, always saying buy scores 53%, and the signal added two
     points. Every result here reports the baseline beside the accuracy and
     the difference between them.

  3. ITS OWN LIMITS. Sample size, absence of costs, and the fact that the
     thresholds were not fitted here are all reported as caveats on the
     result object, so a reader cannot pick up the number without them.

WHAT IT IS NOT
--------------
Not a trading simulator. There is no position sizing, no fees, no slippage
and no compounding. It measures one question only: when the signal leaned a
direction, did price go that way over the next N bars?
"""

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.indicators.service import build_snapshot
from app.market.candles import Candle
from app.signals.engine import Signal, compute_signal

log = get_logger(__name__)

#: SMA(200) is the slowest indicator, so nothing before bar 200 can produce
#: a full vote. Starting earlier would score signals computed from a
#: deliberately crippled indicator set.
DEFAULT_WARMUP = 200

#: How many bars ahead we look to judge a signal.
DEFAULT_HORIZON = 24

#: Below this the result is reported but should not be read as a measurement.
MIN_USEFUL_SAMPLE = 30

BUY_SIGNALS = {Signal.BUY, Signal.STRONG_BUY}
SELL_SIGNALS = {Signal.SELL, Signal.STRONG_SELL}


@dataclass
class Observation:
    """One bar: what the signal said, and what happened next."""

    index: int
    close: float
    signal: Signal
    score: float
    #: (close[t+horizon] - close[t]) / close[t]
    forward_return: float
    #: True/False for directional signals, None for neutral ones.
    correct: bool | None


@dataclass
class BandStats:
    """How one signal band performed."""

    signal: str
    count: int
    correct: int
    accuracy: float | None
    mean_forward_return: float


@dataclass
class BacktestResult:
    symbol: str
    interval: str
    horizon_bars: int
    warmup_bars: int

    #: Bars that produced a signal and had a full forward window.
    evaluated: int
    #: Of those, the ones that leaned buy or sell.
    directional: int
    neutral: int

    correct: int
    #: correct / directional, or None when nothing was directional.
    accuracy: float | None

    #: What always saying "buy" would have scored on the same windows.
    baseline_accuracy: float | None
    #: accuracy - baseline_accuracy. The only number worth quoting.
    edge: float | None

    mean_forward_return: float
    by_signal: list[BandStats] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def run_backtest(
    symbol: str,
    interval: str,
    candles: list[Candle],
    *,
    horizon_bars: int = DEFAULT_HORIZON,
    warmup_bars: int = DEFAULT_WARMUP,
    step: int = 1,
) -> BacktestResult:
    """Score the signal engine over `candles`.

    `step` samples every nth bar. Consecutive bars overlap heavily -- with a
    24-bar horizon, bar t and bar t+1 share 23 bars of outcome -- so their
    results are not independent observations. Stepping by the horizon gives
    disjoint windows at the cost of a smaller sample; the default of 1 keeps
    every bar and the caveat below says what that costs.
    """
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be at least 1")
    if warmup_bars < 1:
        raise ValueError("warmup_bars must be at least 1")
    if step < 1:
        raise ValueError("step must be at least 1")

    observations: list[Observation] = []
    closes = [c.close for c in candles]

    # The last bar we can score is the one whose forward window still fits.
    last_scorable = len(candles) - horizon_bars - 1

    for index in range(warmup_bars, last_scorable + 1, step):
        # The whole point: only candles up to and including `index`.
        window = candles[: index + 1]
        try:
            snapshot = build_snapshot(symbol, interval, window)
        except ValueError:
            continue

        result = compute_signal(snapshot)
        if result is None:
            continue

        entry = closes[index]
        if entry <= 0:
            continue
        forward_return = (closes[index + horizon_bars] - entry) / entry

        observations.append(
            Observation(
                index=index,
                close=entry,
                signal=result.signal,
                score=result.score,
                forward_return=forward_return,
                correct=_was_correct(result.signal, forward_return),
            )
        )

    return _summarise(
        symbol=symbol,
        interval=interval,
        horizon_bars=horizon_bars,
        warmup_bars=warmup_bars,
        step=step,
        candle_count=len(candles),
        observations=observations,
    )


def _was_correct(signal: Signal, forward_return: float) -> bool | None:
    """Did price move the way the signal leaned?

    A neutral signal returns None rather than False. Counting neutral as
    wrong would punish the engine for declining to call a direction, which
    is behaviour we want, not an error.
    """
    if signal in BUY_SIGNALS:
        return forward_return > 0
    if signal in SELL_SIGNALS:
        return forward_return < 0
    return None


def _summarise(
    *,
    symbol: str,
    interval: str,
    horizon_bars: int,
    warmup_bars: int,
    step: int,
    candle_count: int,
    observations: list[Observation],
) -> BacktestResult:
    directional = [o for o in observations if o.correct is not None]
    neutral = len(observations) - len(directional)
    correct = sum(1 for o in directional if o.correct)

    accuracy = correct / len(directional) if directional else None

    # The baseline is "always say buy", scored over exactly the same bars
    # the signal was directional on -- not over all bars. Comparing against
    # a different sample would be the easiest way to manufacture an edge.
    rose = sum(1 for o in directional if o.forward_return > 0)
    baseline = rose / len(directional) if directional else None

    edge = None if accuracy is None or baseline is None else accuracy - baseline

    mean_return = (
        sum(o.forward_return for o in observations) / len(observations) if observations else 0.0
    )

    by_signal = [
        _band_stats(label, [o for o in observations if o.signal is label])
        for label in (
            Signal.STRONG_BUY,
            Signal.BUY,
            Signal.NEUTRAL,
            Signal.SELL,
            Signal.STRONG_SELL,
        )
    ]

    result = BacktestResult(
        symbol=symbol.upper(),
        interval=interval,
        horizon_bars=horizon_bars,
        warmup_bars=warmup_bars,
        evaluated=len(observations),
        directional=len(directional),
        neutral=neutral,
        correct=correct,
        accuracy=None if accuracy is None else round(accuracy, 4),
        baseline_accuracy=None if baseline is None else round(baseline, 4),
        edge=None if edge is None else round(edge, 4),
        mean_forward_return=round(mean_return, 6),
        by_signal=by_signal,
        caveats=_caveats(
            directional_count=len(directional),
            horizon_bars=horizon_bars,
            step=step,
            candle_count=candle_count,
            warmup_bars=warmup_bars,
        ),
    )

    log.info(
        "backtest_complete",
        symbol=result.symbol,
        interval=interval,
        evaluated=result.evaluated,
        accuracy=result.accuracy,
        baseline=result.baseline_accuracy,
        edge=result.edge,
    )
    return result


def _band_stats(signal: Signal, rows: list[Observation]) -> BandStats:
    scored = [o for o in rows if o.correct is not None]
    correct = sum(1 for o in scored if o.correct)
    return BandStats(
        signal=signal.value,
        count=len(rows),
        correct=correct,
        accuracy=round(correct / len(scored), 4) if scored else None,
        mean_forward_return=(
            round(sum(o.forward_return for o in rows) / len(rows), 6) if rows else 0.0
        ),
    )


def _caveats(
    *,
    directional_count: int,
    horizon_bars: int,
    step: int,
    candle_count: int,
    warmup_bars: int,
) -> list[str]:
    """State the limits on the result object, not in a docstring nobody reads."""
    notes = [
        "No transaction costs, slippage or position sizing are modelled; this "
        "measures direction only, not profitability.",
        "The indicator thresholds were not fitted to this data -- they are the "
        "published conventional levels -- so this is an out-of-sample test of "
        "those levels, but only on the window and asset shown.",
    ]

    if directional_count == 0:
        notes.append("No directional signals occurred, so no accuracy could be measured.")
    elif directional_count < MIN_USEFUL_SAMPLE:
        notes.append(
            f"Only {directional_count} directional signals. Below about "
            f"{MIN_USEFUL_SAMPLE} the figure is too noisy to read as a measurement."
        )

    if step < horizon_bars:
        notes.append(
            f"Sampling every {step} bar(s) against a {horizon_bars}-bar horizon means "
            "consecutive observations share most of their outcome window, so they are "
            "not independent and the effective sample is smaller than the count shown."
        )

    if candle_count - warmup_bars - horizon_bars < 100:
        notes.append(
            "Short history: the warm-up and forward window consume most of the "
            "candles supplied."
        )

    return notes
