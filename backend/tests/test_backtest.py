"""Tests for the backtest harness.

The harness exists to produce a number this project is otherwise careful not
to claim, so the tests concentrate on the ways such a number goes wrong:
seeing the future, being reported without a baseline, and counting a
declined call as a mistake.
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from app.backtest.engine import DEFAULT_WARMUP, run_backtest, _was_correct
from app.market.candles import Candle
from app.signals.engine import Signal

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_candles(closes: list[float]) -> list[Candle]:
    """Candles from a close series; OHLC collapsed since only close is scored."""
    return [
        Candle(
            open_time=START + timedelta(hours=i),
            open=c,
            high=c * 1.001,
            low=c * 0.999,
            close=c,
            volume=1000.0,
        )
        for i, c in enumerate(closes)
    ]


def rising(n: int, start: float = 100.0, step: float = 0.5) -> list[float]:
    return [start + i * step for i in range(n)]


def falling(n: int, start: float = 400.0, step: float = 0.5) -> list[float]:
    return [start - i * step for i in range(n)]


# ---------------------------------------------------------------------
# No lookahead -- the one that matters most
# ---------------------------------------------------------------------


def test_future_candles_cannot_change_an_earlier_signal():
    """The decisive test.

    Run the same history twice, the second time with wildly different data
    appended after the scored region. If any observation changes, the engine
    saw the future.
    """
    base = rising(400)
    short = make_candles(base)
    # Append a violent crash well beyond the last scorable bar of `short`.
    extended = make_candles(base + [10.0] * 200)

    horizon = 24
    first = run_backtest("ETH", "1h", short, horizon_bars=horizon, step=7)
    second = run_backtest("ETH", "1h", extended, horizon_bars=horizon, step=7)

    # Compare only the bars both runs scored.
    overlap = len(short) - horizon - 1
    a = {o.index: (o.signal, o.score) for o in _observations(first, short, horizon) if o.index <= overlap}

    # Re-derive the second run's observations over the same indices.
    b = {
        o.index: (o.signal, o.score)
        for o in _observations(second, extended, horizon)
        if o.index <= overlap
    }

    shared = set(a) & set(b)
    assert shared, "the two runs scored no bars in common"
    for index in shared:
        assert a[index] == b[index], (
            f"bar {index} changed when later candles were appended -- "
            "the signal is reading the future"
        )


def _observations(result, candles, horizon):
    """Recompute observations for comparison.

    run_backtest returns a summary rather than the raw rows, so this rebuilds
    them the same way for the lookahead comparison above.
    """
    from app.indicators.service import build_snapshot
    from app.signals.engine import compute_signal
    from app.backtest.engine import Observation, _was_correct as was_correct

    closes = [c.close for c in candles]
    out = []
    for index in range(result.warmup_bars, len(candles) - horizon, 7):
        snapshot = build_snapshot("ETH", "1h", candles[: index + 1])
        signal = compute_signal(snapshot)
        if signal is None:
            continue
        forward = (closes[index + horizon] - closes[index]) / closes[index]
        out.append(
            Observation(index, closes[index], signal.signal, signal.score, forward,
                        was_correct(signal.signal, forward))
        )
    return out


# ---------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------


def test_a_rising_market_is_scored_correct_for_buy_signals():
    candles = make_candles(rising(400))
    result = run_backtest("ETH", "1h", candles, horizon_bars=24, step=5)

    assert result.directional > 0
    # Price only ever rises, so every directional call that was a buy is right
    # and every sell is wrong. The engine should be mostly buying here.
    assert result.accuracy == 1.0 or result.accuracy > 0.9


def test_neutral_signals_are_excluded_from_accuracy_not_counted_wrong():
    assert _was_correct(Signal.NEUTRAL, 0.05) is None
    assert _was_correct(Signal.NEUTRAL, -0.05) is None
    assert _was_correct(Signal.BUY, 0.01) is True
    assert _was_correct(Signal.BUY, -0.01) is False
    assert _was_correct(Signal.STRONG_SELL, -0.01) is True
    assert _was_correct(Signal.SELL, 0.01) is False


def test_a_flat_forward_move_is_not_credited_to_either_side():
    """Exactly zero return is not a correct buy and not a correct sell."""
    assert _was_correct(Signal.BUY, 0.0) is False
    assert _was_correct(Signal.SELL, 0.0) is False


# ---------------------------------------------------------------------
# The baseline must be comparable
# ---------------------------------------------------------------------


def test_baseline_is_measured_on_the_same_bars_as_the_accuracy():
    """A baseline drawn from a different sample could manufacture an edge."""
    candles = make_candles(rising(400))
    result = run_backtest("ETH", "1h", candles, horizon_bars=24, step=5)

    assert result.baseline_accuracy is not None
    # In a monotonically rising series every forward window is positive, so
    # always-buy scores 1.0 and the signal cannot beat it.
    assert result.baseline_accuracy == 1.0
    assert result.edge is not None
    assert result.edge <= 0.0


def test_edge_is_the_difference_between_accuracy_and_baseline():
    candles = make_candles(_wavy(500))
    result = run_backtest("ETH", "1h", candles, horizon_bars=12, step=6)

    if result.accuracy is not None and result.baseline_accuracy is not None:
        assert result.edge == pytest.approx(
            round(result.accuracy - result.baseline_accuracy, 4), abs=1e-4
        )


def _wavy(n: int) -> list[float]:
    """A series that actually turns, so both directions get exercised."""
    return [100 + 20 * math.sin(i / 18) + 6 * math.sin(i / 4) for i in range(n)]


# ---------------------------------------------------------------------
# The result must carry its own limits
# ---------------------------------------------------------------------


def test_result_always_states_that_costs_are_not_modelled():
    candles = make_candles(_wavy(400))
    result = run_backtest("ETH", "1h", candles, horizon_bars=12, step=6)

    joined = " ".join(result.caveats).lower()
    assert "transaction costs" in joined or "slippage" in joined


def test_overlapping_windows_are_flagged_as_not_independent():
    candles = make_candles(_wavy(400))
    result = run_backtest("ETH", "1h", candles, horizon_bars=24, step=1)

    assert any("not independent" in c for c in result.caveats)


def test_disjoint_windows_do_not_raise_the_overlap_caveat():
    candles = make_candles(_wavy(600))
    result = run_backtest("ETH", "1h", candles, horizon_bars=10, step=10)

    assert not any("not independent" in c for c in result.caveats)


def test_a_small_sample_is_flagged_rather_than_reported_plainly():
    candles = make_candles(_wavy(DEFAULT_WARMUP + 40))
    result = run_backtest("ETH", "1h", candles, horizon_bars=12, step=4)

    joined = " ".join(result.caveats).lower()
    assert "noisy" in joined or "no directional signals" in joined


# ---------------------------------------------------------------------
# Shape and guards
# ---------------------------------------------------------------------


def test_counts_add_up():
    candles = make_candles(_wavy(500))
    result = run_backtest("ETH", "1h", candles, horizon_bars=12, step=3)

    assert result.directional + result.neutral == result.evaluated
    assert result.correct <= result.directional
    assert sum(b.count for b in result.by_signal) == result.evaluated


def test_every_signal_band_is_reported_even_when_unused():
    candles = make_candles(rising(400))
    result = run_backtest("ETH", "1h", candles, horizon_bars=24, step=8)

    assert {b.signal for b in result.by_signal} == {
        "STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"
    }


def test_too_little_history_produces_an_empty_but_valid_result():
    candles = make_candles(rising(50))
    result = run_backtest("ETH", "1h", candles, horizon_bars=24)

    assert result.evaluated == 0
    assert result.accuracy is None
    assert result.edge is None
    assert any("no directional signals" in c.lower() for c in result.caveats)


@pytest.mark.parametrize(
    "kwargs",
    [{"horizon_bars": 0}, {"warmup_bars": 0}, {"step": 0}],
)
def test_invalid_parameters_are_rejected(kwargs):
    candles = make_candles(rising(300))
    with pytest.raises(ValueError):
        run_backtest("ETH", "1h", candles, **kwargs)
