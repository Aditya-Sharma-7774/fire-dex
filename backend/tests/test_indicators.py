"""Tests for the indicator engine.

These are the most important tests in the project.

The whole "the AI never calculates" argument rests on these numbers being
provably correct. Where possible each indicator is checked against a value
computed by hand from the published formula, not against another library --
otherwise we would only be proving that two implementations agree.
"""

import math

import pytest

from app.indicators.engine import (
    bollinger_bands,
    exponential_moving_average,
    macd,
    realised_volatility,
    relative_strength_index,
    simple_moving_average,
)

# Wilder's original worked example for RSI, from "New Concepts in Technical
# Trading Systems" (1978). Widely reproduced, so it is a genuine external
# reference rather than our own output.
WILDER_CLOSES = [
    44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
    45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
    46.03, 46.41, 46.22, 45.64,
]


# ---------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------


def test_sma_matches_hand_calculation() -> None:
    # mean(1,2,3) = 2 ; mean(2,3,4) = 3 ; mean(3,4,5) = 4
    assert simple_moving_average([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


def test_sma_is_none_until_the_window_is_full() -> None:
    """Alignment matters: index 0 of the output is index 0 of the input."""
    result = simple_moving_average([10, 20, 30, 40], 3)
    assert result[:2] == [None, None]
    assert result[2] == 20.0


def test_sma_period_one_is_the_series_itself() -> None:
    assert simple_moving_average([5, 7, 9], 1) == [5.0, 7.0, 9.0]


def test_sma_handles_series_shorter_than_period() -> None:
    assert simple_moving_average([1, 2], 5) == [None, None]


def test_sma_rolling_sum_does_not_drift() -> None:
    """The rolling implementation must agree with a naive recomputation."""
    values = [float(i % 17) + 0.5 for i in range(300)]
    rolling = simple_moving_average(values, 12)

    for index in range(11, len(values)):
        expected = sum(values[index - 11 : index + 1]) / 12
        assert rolling[index] == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------


def test_ema_seeds_with_sma_then_applies_the_multiplier() -> None:
    values = [1, 2, 3, 4, 5]
    result = exponential_moving_average(values, 3)

    # Seed = mean(1,2,3) = 2. Multiplier = 2/(3+1) = 0.5
    assert result[2] == pytest.approx(2.0)
    # (4 - 2) * 0.5 + 2 = 3.0
    assert result[3] == pytest.approx(3.0)
    # (5 - 3) * 0.5 + 3 = 4.0
    assert result[4] == pytest.approx(4.0)


def test_ema_reacts_faster_than_sma_after_a_jump() -> None:
    """A defining property, worth asserting rather than assuming."""
    values = [10.0] * 20 + [20.0] * 5
    ema = exponential_moving_average(values, 10)[-1]
    sma = simple_moving_average(values, 10)[-1]

    assert ema is not None and sma is not None
    assert ema > sma


def test_ema_of_a_constant_series_is_that_constant() -> None:
    result = exponential_moving_average([7.0] * 30, 10)
    assert result[-1] == pytest.approx(7.0)


# ---------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------


def test_rsi_matches_a_hand_calculation() -> None:
    """First RSI value, computed by hand from Wilder's formula.

    Working, for the first 14 price changes of WILDER_CLOSES:

        sum of gains  = 3.34   ->  average gain = 3.34 / 14 = 0.238571
        sum of losses = 1.40   ->  average loss = 1.40 / 14 = 0.100000
        RS  = 0.238571 / 0.100000 = 2.385714
        RSI = 100 - 100 / (1 + 2.385714) = 70.4641

    Asserting against arithmetic we can reproduce on paper is stronger than
    asserting against a constant copied from somewhere, or against another
    library -- that would only prove two implementations agree with each
    other, not that either is right.
    """
    result = relative_strength_index(WILDER_CLOSES, period=14)

    assert result[14] == pytest.approx(70.4641, abs=0.0005)


def test_rsi_continues_with_wilder_smoothing() -> None:
    """Subsequent values use smoothed averages, not a fresh rolling mean.

        avg_gain_t = (avg_gain_{t-1} * 13 + gain_t) / 14

    Continuing the calculation above by hand gives 66.2496 then 66.4809.
    A plain rolling mean over the same window gives visibly different
    numbers, so this test is what pins the implementation to Wilder's
    definition rather than a lookalike.
    """
    result = relative_strength_index(WILDER_CLOSES, period=14)

    assert result[15] == pytest.approx(66.2496, abs=0.0005)
    assert result[16] == pytest.approx(66.4809, abs=0.0005)


def test_rsi_stays_within_zero_and_one_hundred() -> None:
    import random

    random.seed(42)
    values = [100.0]
    for _ in range(200):
        values.append(max(1.0, values[-1] * (1 + random.uniform(-0.08, 0.08))))

    for value in relative_strength_index(values, 14):
        if value is not None:
            assert 0.0 <= value <= 100.0


def test_rsi_is_one_hundred_when_price_only_rises() -> None:
    """No losses means RS is undefined; RSI is 100 by convention.

    Without the explicit guard this divides by zero.
    """
    values = [float(i) for i in range(1, 40)]
    result = relative_strength_index(values, 14)

    assert result[-1] == 100.0


def test_rsi_is_zero_when_price_only_falls() -> None:
    values = [float(i) for i in range(40, 1, -1)]
    result = relative_strength_index(values, 14)

    assert result[-1] == pytest.approx(0.0, abs=1e-9)


def test_rsi_is_none_without_enough_data() -> None:
    assert all(v is None for v in relative_strength_index([1, 2, 3], 14))


# ---------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------


def test_macd_line_is_the_difference_of_the_two_emas() -> None:
    values = [float(i) for i in range(1, 80)]
    result = macd(values, fast_period=12, slow_period=26, signal_period=9)

    fast = exponential_moving_average(values, 12)
    slow = exponential_moving_average(values, 26)

    for index in range(len(values)):
        if fast[index] is None or slow[index] is None:
            assert result.macd[index] is None
        else:
            assert result.macd[index] == pytest.approx(fast[index] - slow[index])


def test_macd_histogram_is_macd_minus_signal() -> None:
    values = [float(i % 20) + 50 for i in range(120)]
    result = macd(values)

    for m, s, h in zip(result.macd, result.signal, result.histogram, strict=True):
        if m is None or s is None:
            assert h is None
        else:
            assert h == pytest.approx(m - s)


def test_macd_signal_starts_later_than_the_macd_line() -> None:
    """The signal is an EMA of the MACD, so it needs MACD values first."""
    values = [float(i) for i in range(1, 80)]
    result = macd(values)

    first_macd = next(i for i, v in enumerate(result.macd) if v is not None)
    first_signal = next(i for i, v in enumerate(result.signal) if v is not None)

    assert first_signal > first_macd


def test_macd_rejects_fast_period_not_smaller_than_slow() -> None:
    with pytest.raises(ValueError):
        macd([1.0] * 50, fast_period=26, slow_period=12)


# ---------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------


def test_bollinger_matches_hand_calculation() -> None:
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    result = bollinger_bands(values, period=8, std_dev=2.0)

    # mean = 5.0, population sigma = 2.0
    assert result.middle[-1] == pytest.approx(5.0)
    assert result.upper[-1] == pytest.approx(9.0)
    assert result.lower[-1] == pytest.approx(1.0)


def test_bollinger_bands_collapse_on_a_flat_series() -> None:
    """Zero volatility means zero width -- a good sanity check."""
    result = bollinger_bands([10.0] * 30, period=20)

    assert result.upper[-1] == pytest.approx(10.0)
    assert result.lower[-1] == pytest.approx(10.0)


def test_bollinger_upper_is_always_above_lower() -> None:
    import random

    random.seed(7)
    values = [100 + random.uniform(-5, 5) for _ in range(100)]
    result = bollinger_bands(values, 20)

    for upper, lower in zip(result.upper, result.lower, strict=True):
        if upper is not None and lower is not None:
            assert upper >= lower


def test_bollinger_uses_population_not_sample_sigma() -> None:
    """Divide by n, not n-1. Using the sample sigma widens the bands."""
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    result = bollinger_bands(values, period=8, std_dev=1.0)

    population_sigma = 2.0
    sample_sigma = math.sqrt(sum((v - 5.0) ** 2 for v in values) / 7)

    assert result.upper[-1] == pytest.approx(5.0 + population_sigma)
    assert result.upper[-1] != pytest.approx(5.0 + sample_sigma)


# ---------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------


def test_volatility_of_a_flat_series_is_zero() -> None:
    assert realised_volatility([100.0] * 30, 14) == pytest.approx(0.0, abs=1e-12)


def test_volatility_rises_with_larger_swings() -> None:
    calm = [100 + (1 if i % 2 else -1) * 0.5 for i in range(40)]
    wild = [100 + (1 if i % 2 else -1) * 10 for i in range(40)]

    calm_vol = realised_volatility(calm, 14)
    wild_vol = realised_volatility(wild, 14)

    assert calm_vol is not None and wild_vol is not None
    assert wild_vol > calm_vol


def test_volatility_is_none_without_enough_data() -> None:
    assert realised_volatility([1.0, 2.0], 14) is None


# ---------------------------------------------------------------------
# Shared guarantees
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    [simple_moving_average, exponential_moving_average, relative_strength_index],
)
def test_output_length_always_matches_input_length(fn) -> None:
    """Index alignment is what lets several indicators be read together."""
    values = [float(i) for i in range(50)]
    assert len(fn(values, 14)) == len(values)


@pytest.mark.parametrize("fn", [simple_moving_average, exponential_moving_average])
def test_invalid_period_is_rejected(fn) -> None:
    with pytest.raises(ValueError):
        fn([1.0, 2.0, 3.0], 0)


def test_empty_input_produces_empty_output() -> None:
    assert simple_moving_average([], 14) == []
    assert exponential_moving_average([], 14) == []
    assert relative_strength_index([], 14) == []
