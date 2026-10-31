"""Tests for average true range and price/RSI divergence.

Both are asserted against values worked out by hand from the formula, not
against another library. Agreement between two implementations would only
prove they agree; the arithmetic is written out in the comments so the
expected numbers can be checked independently.
"""

import pytest

from app.indicators.engine import (
    average_true_range,
    find_divergences,
    find_pivots,
    relative_strength_index,
)


# ---------------------------------------------------------------------
# Average true range
# ---------------------------------------------------------------------


def test_atr_matches_a_hand_calculation():
    """Worked by hand on a deliberately simple series.

    Every bar has high = low + 2 and closes at its midpoint, and each bar
    sits exactly 1 above the last. So for every bar after the first:

        high - low            = 2
        |high - prev close|   = (low + 2) - (prev low + 1) = 2
        |low  - prev close|   = low - (prev low + 1)       = 0
        true range            = 2

    With a constant true range of 2, the Wilder average is 2 at every
    point, regardless of period.
    """
    lows = [float(10 + i) for i in range(30)]
    highs = [low + 2 for low in lows]
    closes = [low + 1 for low in lows]

    atr = average_true_range(highs, lows, closes, period=14)

    assert atr[13] is None, "ATR cannot exist before period+1 bars"
    assert atr[14] == pytest.approx(2.0)
    assert atr[-1] == pytest.approx(2.0)


def test_atr_counts_the_gap_between_bars_not_just_the_bar_range():
    """The property that distinguishes ATR from plain range.

    Bar 1 gaps far above bar 0: its low is above bar 0's close. The true
    range must span from the previous close to this bar's high, not merely
    the bar's own high-to-low.
    """
    highs = [10.0, 30.0]
    lows = [9.0, 28.0]
    closes = [9.5, 29.0]

    atr = average_true_range(highs, lows, closes, period=1)

    # period=1: out[1] is the true range of bar 1 alone.
    #   high - low          = 30 - 28 = 2
    #   |high - prev close| = |30 - 9.5| = 20.5   <- the gap
    #   |low  - prev close| = |28 - 9.5| = 18.5
    assert atr[1] == pytest.approx(20.5)


def test_atr_is_none_until_enough_bars_exist():
    highs = [float(i + 2) for i in range(10)]
    lows = [float(i) for i in range(10)]
    closes = [float(i + 1) for i in range(10)]

    atr = average_true_range(highs, lows, closes, period=14)

    assert all(value is None for value in atr)


def test_atr_rejects_mismatched_series():
    with pytest.raises(ValueError):
        average_true_range([1.0, 2.0], [1.0], [1.0, 2.0], period=1)


def test_atr_rejects_a_zero_period():
    with pytest.raises(ValueError):
        average_true_range([2.0], [1.0], [1.5], period=0)


# ---------------------------------------------------------------------
# Pivots
# ---------------------------------------------------------------------


def test_a_pivot_needs_confirmation_on_both_sides():
    """The last bars can never be pivots, and that is the point.

    A pivot is only known once `width` bars have formed after it. If the
    final bar could be a pivot, a divergence would appear to be visible
    before it actually was -- which is lookahead by another name.
    """
    values = [1.0, 2.0, 3.0, 9.0, 3.0, 2.0, 1.0, 5.0, 9.0]
    highs, lows = find_pivots(values, width=2)

    assert 3 in highs
    assert len(values) - 1 not in highs, "the final bar was treated as a pivot"
    assert all(index <= len(values) - 1 - 2 for index in highs + lows)


def test_flat_stretches_do_not_produce_pivots():
    """A plateau has no single highest bar, so none of it is a pivot."""
    values = [1.0, 5.0, 5.0, 5.0, 1.0]
    highs, _ = find_pivots(values, width=1)

    assert highs == []


def test_pivot_width_must_be_positive():
    with pytest.raises(ValueError):
        find_pivots([1.0, 2.0, 3.0], width=0)


# ---------------------------------------------------------------------
# Divergence
# ---------------------------------------------------------------------


def build_series_with_bearish_divergence() -> tuple[list[float], list[float | None]]:
    """Price makes a higher high while RSI makes a lower high.

    Constructed directly rather than sampled from real data so the expected
    answer is unambiguous. Verified by hand:

        pivot high at index 12: price 120.0, RSI(5) 93.7
        pivot high at index 24: price 124.0, RSI(5) 85.3

    Price rose between the two peaks while RSI fell, which is the definition
    of a bearish divergence.

    The leading oscillation is not decoration. RSI(5) is undefined for the
    first six bars, so without it the first peak would have no RSI to
    compare and nothing could be detected -- which is exactly how the first
    version of this test fixture was wrong.
    """
    closes: list[float] = [100, 101, 100, 101, 100, 101, 100, 101]
    # First peak: a sharp rally to 120, which drives RSI high.
    closes += [100, 104, 108, 114, 120, 114, 108, 103, 100]
    # Second peak: higher in price (124) but ground out slowly, so the RSI
    # of the move is weaker than the first.
    closes += [101, 103, 106, 110, 115, 119, 122, 124, 122, 119, 115, 112]
    values = [float(c) for c in closes]
    return values, relative_strength_index(values, 5)


def test_a_bearish_divergence_is_found_when_price_rises_but_rsi_does_not():
    closes, rsi = build_series_with_bearish_divergence()

    found = find_divergences(closes, rsi, width=2, lookback=len(closes))

    bearish = [d for d in found if d.kind == "bearish"]
    assert bearish, "expected a bearish divergence"
    d = bearish[0]
    assert (d.price_from, d.price_to) == (120.0, 124.0)
    assert d.rsi_from == pytest.approx(93.7, abs=0.1)
    assert d.rsi_to == pytest.approx(85.3, abs=0.1)
    assert d.price_to > d.price_from, "price should have made a higher high"
    assert d.rsi_to < d.rsi_from, "RSI should have made a lower high"


def test_a_clean_trend_produces_no_divergence():
    """Price and momentum agreeing must not be reported as disagreement."""
    closes = [float(100 + i * 2) for i in range(60)]
    rsi = relative_strength_index(closes, 14)

    found = find_divergences(closes, rsi, width=3, lookback=60)

    assert found == []


def test_old_divergences_are_excluded_by_the_lookback():
    closes, rsi = build_series_with_bearish_divergence()
    # Pad the series so the divergence falls outside a short lookback.
    closes = closes + [112.0] * 80
    rsi = relative_strength_index(closes, 5)

    assert find_divergences(closes, rsi, width=2, lookback=10) == []


def test_divergence_reports_how_long_ago_it_was_confirmed():
    closes, rsi = build_series_with_bearish_divergence()

    found = find_divergences(closes, rsi, width=2, lookback=len(closes))

    assert found
    d = found[0]
    assert d.bars_ago == len(closes) - 1 - d.to_index
    assert d.bars_ago >= 2, "a pivot cannot be confirmed within its own width"


def test_results_are_ordered_most_recent_first():
    closes, rsi = build_series_with_bearish_divergence()

    found = find_divergences(closes, rsi, width=2, lookback=len(closes), max_results=10)

    assert found == sorted(found, key=lambda d: d.bars_ago)


def test_mismatched_series_are_rejected():
    with pytest.raises(ValueError):
        find_divergences([1.0, 2.0, 3.0], [None, None])


# ---------------------------------------------------------------------
# The snapshot carries both
# ---------------------------------------------------------------------


def test_snapshot_exposes_atr_and_its_percentage():
    from datetime import datetime, timedelta, timezone

    from app.indicators.service import build_snapshot
    from app.market.candles import Candle

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            open_time=start + timedelta(hours=i),
            open=100.0 + i,
            high=102.0 + i,
            low=100.0 + i,
            close=101.0 + i,
            volume=10.0,
        )
        for i in range(60)
    ]

    snapshot = build_snapshot("ETH", "1h", candles)

    assert snapshot.atr_14 == pytest.approx(2.0)
    assert snapshot.atr_percent == pytest.approx(
        snapshot.atr_14 / snapshot.last_close * 100
    )
