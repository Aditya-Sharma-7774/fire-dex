"""Tests for the signal engine and groundedness scorer.

Both are computed rather than model-generated, which is the entire reason
they can be defended. That only holds if they are provably correct, so these
tests assert the published rules directly.
"""

from datetime import datetime, timezone

import pytest

from app.agents.contract import AgentResult, AgentStatus, Observation, ValidationReport
from app.agents.groundedness import assess_groundedness
from app.evidence.types import EvidenceBuilder, EvidenceKind
from app.indicators.service import IndicatorSnapshot
from app.signals.engine import Direction, Signal, compute_signal


def _snapshot(**overrides) -> IndicatorSnapshot:
    defaults = dict(
        symbol="ETH",
        interval="1h",
        candle_count=300,
        last_close=2500.0,
        last_candle_time=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


# ---------------------------------------------------------------------
# Signal engine
# ---------------------------------------------------------------------


def test_no_indicators_gives_no_signal_not_neutral() -> None:
    """'We could not tell' and 'the indicators disagree evenly' differ."""
    assert compute_signal(_snapshot()) is None
    assert compute_signal(None) is None


def test_everything_bullish_gives_strong_buy() -> None:
    result = compute_signal(
        _snapshot(
            last_close=2500.0,
            rsi_14=25.0,  # oversold -> buy
            macd_histogram=1.2,  # positive -> buy
            bollinger_position=0.10,  # low in band -> buy
            sma_20=2400.0,
            sma_50=2300.0,
            sma_200=2200.0,  # price above all -> buy
            ema_12=2450.0,
            ema_26=2400.0,  # fast above slow -> buy
        )
    )

    assert result is not None
    assert result.signal is Signal.STRONG_BUY
    assert result.sell_votes == 0
    assert result.score == pytest.approx(1.0)


def test_everything_bearish_gives_strong_sell() -> None:
    result = compute_signal(
        _snapshot(
            last_close=2000.0,
            rsi_14=82.0,  # overbought -> sell
            macd_histogram=-0.8,
            bollinger_position=0.95,
            sma_20=2200.0,
            sma_50=2300.0,
            sma_200=2400.0,
            ema_12=2100.0,
            ema_26=2250.0,
        )
    )

    assert result is not None
    assert result.signal is Signal.STRONG_SELL
    assert result.buy_votes == 0
    assert result.score == pytest.approx(-1.0)


def test_evenly_split_indicators_give_neutral() -> None:
    """One each way must not read as a decision.

    Note the earlier version of this test used 1 buy against 2 sells and
    expected NEUTRAL. That was the test being wrong, not the engine: a
    2-to-1 bearish lean IS a lean, and the engine correctly said SELL.
    """
    result = compute_signal(
        _snapshot(
            last_close=2500.0,
            rsi_14=50.0,  # neutral
            bollinger_position=0.5,  # neutral
            macd_histogram=0.5,  # buy
            sma_20=2600.0,  # sell (price below)
        )
    )

    assert result is not None
    assert result.buy_votes == result.sell_votes == 1
    assert result.score == pytest.approx(0.0)
    assert result.signal is Signal.NEUTRAL


def test_a_mild_lean_gives_buy_not_strong_buy() -> None:
    """The bands must distinguish a lean from a consensus."""
    result = compute_signal(
        _snapshot(
            last_close=2500.0,
            rsi_14=50.0,  # neutral
            bollinger_position=0.5,  # neutral
            macd_histogram=0.5,  # buy
            sma_20=2400.0,  # buy
            sma_50=2600.0,  # sell
        )
    )

    assert result is not None
    assert result.buy_votes == 2 and result.sell_votes == 1
    assert result.score == pytest.approx(0.2)
    assert result.signal is Signal.BUY


def test_neutral_votes_dilute_the_score() -> None:
    """Two buys out of six indicators is weaker than two out of two.

    Neutral votes stay in the denominator on purpose: an indicator that
    says nothing is evidence of indecision, not something to ignore.
    """
    strong = compute_signal(
        _snapshot(last_close=2500.0, sma_20=2400.0, ema_12=2450.0, ema_26=2400.0)
    )
    diluted = compute_signal(
        _snapshot(
            last_close=2500.0,
            sma_20=2400.0,
            ema_12=2450.0,
            ema_26=2400.0,
            rsi_14=50.0,  # neutral
            bollinger_position=0.5,  # neutral
            macd_histogram=0.0,  # neutral
        )
    )

    assert strong is not None and diluted is not None
    assert diluted.score < strong.score


def test_rsi_thresholds_match_the_published_levels() -> None:
    below = compute_signal(_snapshot(rsi_14=29.9))
    inside = compute_signal(_snapshot(rsi_14=50.0))
    above = compute_signal(_snapshot(rsi_14=70.1))

    assert below is not None and below.votes[0].direction is Direction.BUY
    assert inside is not None and inside.votes[0].direction is Direction.NEUTRAL
    assert above is not None and above.votes[0].direction is Direction.SELL


def test_every_vote_carries_the_rule_that_produced_it() -> None:
    """'Why does it say Buy?' must have a listable answer."""
    result = compute_signal(_snapshot(rsi_14=25.0, last_close=2500.0, sma_20=2400.0))

    assert result is not None
    for vote in result.votes:
        assert vote.rule, f"{vote.indicator} has no stated rule"
        assert vote.indicator


def test_signal_is_deterministic() -> None:
    """Identical input must always give the identical signal."""
    snapshot = _snapshot(rsi_14=45.0, macd_histogram=0.3, last_close=2500.0, sma_20=2400.0)

    first = compute_signal(snapshot)
    second = compute_signal(snapshot)

    assert first is not None and second is not None
    assert first.signal is second.signal
    assert first.score == second.score


def test_partial_indicator_coverage_is_reported() -> None:
    result = compute_signal(_snapshot(rsi_14=50.0))

    assert result is not None
    assert result.coverage < 0.75
    assert "of 8 indicators" in result.note


# ---------------------------------------------------------------------
# Groundedness
# ---------------------------------------------------------------------


def _bundle():
    builder = EvidenceBuilder(subject="ETH")
    builder.add(EvidenceKind.PRICE, "ETH price", 2500.0, unit="USD", provider="t", method="m")
    builder.add(EvidenceKind.INDICATOR, "RSI (14)", 49.4, provider="t", method="m")
    builder.add(EvidenceKind.INDICATOR, "SMA (20)", 2400.0, provider="t", method="m")
    builder.add(EvidenceKind.MARKET_STAT, "24h volume", 1000.0, unit="USD", provider="t", method="m")
    return builder.build()


def _result(observations) -> AgentResult:
    now = datetime.now(timezone.utc)
    return AgentResult(
        agent="test_agent",
        status=AgentStatus.COMPLETED,
        started_at=now,
        ended_at=now,
        observations=list(observations),
    )


def test_fully_supported_claims_score_highly() -> None:
    result = _result(
        [
            Observation(text="ETH price is 2500 USD", evidence_ids=["ev_001", "ev_002"]),
            Observation(text="RSI (14) is 49.4", evidence_ids=["ev_002", "ev_003"]),
        ]
    )

    report = assess_groundedness(_bundle(), [result], {"test_agent": ValidationReport(valid=True)})

    assert report.claim_support == 1.0
    assert report.score > 0.6
    assert report.band in {"adequate", "strong"}


def test_no_claims_is_not_perfect_groundedness() -> None:
    """Zero claims means nothing to ground, not flawless grounding.

    Reporting 1.0 here would make a failed analysis look immaculate.
    """
    report = assess_groundedness(_bundle(), [_result([])], {})

    assert report.claim_support == 0.0
    assert report.total_claims == 0


def test_unresolvable_citation_lowers_the_score() -> None:
    result = _result([Observation(text="Something", evidence_ids=["ev_999"])])

    report = assess_groundedness(_bundle(), [result], {"test_agent": ValidationReport(valid=True)})

    assert report.claim_support == 0.0
    assert len(report.unsupported_claims) == 1
    assert "does not exist" in report.unsupported_claims[0].reason


def test_top_evidence_is_ranked_by_citation_count() -> None:
    """Shows which facts actually did the work."""
    result = _result(
        [
            Observation(text="ETH price is 2500 USD", evidence_ids=["ev_001"]),
            Observation(text="ETH price is 2500 USD again", evidence_ids=["ev_001"]),
            Observation(text="RSI (14) is 49.4", evidence_ids=["ev_002"]),
        ]
    )

    report = assess_groundedness(_bundle(), [result], {"test_agent": ValidationReport(valid=True)})

    assert report.top_evidence[0][0] == "ev_001"
    assert report.top_evidence[0][2] == 2


def test_unused_evidence_is_listed() -> None:
    """Evidence gathered but ignored is a real quality signal."""
    result = _result([Observation(text="ETH price is 2500 USD", evidence_ids=["ev_001"])])

    report = assess_groundedness(_bundle(), [result], {"test_agent": ValidationReport(valid=True)})

    assert report.evidence_use == 0.25  # 1 of 4
    assert len(report.unused_evidence) == 3


def test_more_evidence_per_claim_raises_anchoring() -> None:
    """A claim resting on three facts is better grounded than one on one."""
    thin = _result([Observation(text="ETH price is 2500 USD", evidence_ids=["ev_001"])])
    thick = _result(
        [Observation(text="ETH price is 2500 USD", evidence_ids=["ev_001", "ev_002", "ev_003"])]
    )

    thin_report = assess_groundedness(_bundle(), [thin], {"test_agent": ValidationReport(valid=True)})
    thick_report = assess_groundedness(
        _bundle(), [thick], {"test_agent": ValidationReport(valid=True)}
    )

    assert thick_report.anchoring > thin_report.anchoring


def test_stale_evidence_caps_groundedness() -> None:
    """A claim perfectly supported by an old price is not well grounded now."""
    builder = EvidenceBuilder(subject="ETH")
    builder.add(
        EvidenceKind.PRICE, "ETH price", 2500.0, unit="USD",
        provider="t", method="m", is_stale=True,
    )
    bundle = builder.build()

    result = _result([Observation(text="ETH price is 2500 USD", evidence_ids=["ev_001"])])
    report = assess_groundedness(bundle, [result], {"test_agent": ValidationReport(valid=True)})

    assert report.score <= 0.75
    assert report.freshness_ok is False
