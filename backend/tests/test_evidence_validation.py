"""Tests for the evidence contract and the output validator.

This is the mechanism the entire project rests on: it is what turns "the AI
must not invent numbers" from a request in a prompt into a property enforced
by code. If these tests are weak, the central claim of the project is weak.
"""

from datetime import datetime, timezone

import pytest

from app.agents.contract import (
    AgentResult,
    AgentStatus,
    Interpretation,
    Observation,
    validate_agent_output,
)
from app.evidence.types import EvidenceBuilder, EvidenceKind


def _bundle():
    """A small bundle resembling a real asset analysis."""
    builder = EvidenceBuilder(subject="ETH")
    builder.add(
        EvidenceKind.PRICE, "ETH price", 2462.7, unit="USD",
        provider="coingecko", method="simple/price",
    )
    builder.add(
        EvidenceKind.INDICATOR, "RSI (14)", 49.39,
        provider="fire-dex-indicator-engine", method="computed",
    )
    builder.add(
        EvidenceKind.INDICATOR, "SMA (20)", 2469.69, unit="USD",
        provider="fire-dex-indicator-engine", method="computed",
    )
    builder.add(
        EvidenceKind.TREND, "Trend classification", "sideways",
        provider="fire-dex-indicator-engine", method="classify_trend",
    )
    return builder.build()


def _result(observations=(), interpretations=()):
    now = datetime.now(timezone.utc)
    return AgentResult(
        agent="test_agent",
        status=AgentStatus.COMPLETED,
        started_at=now,
        ended_at=now,
        observations=list(observations),
        interpretations=list(interpretations),
    )


# ---------------------------------------------------------------------
# The core guarantee
# ---------------------------------------------------------------------


def test_accurate_observation_passes() -> None:
    result = _result([Observation(text="ETH price is 2462.7 USD", evidence_ids=["ev_001"])])

    assert validate_agent_output(result, _bundle()).valid


def test_hallucinated_number_is_rejected() -> None:
    """THE test. An agent stating a figure that is not in the evidence."""
    result = _result([Observation(text="ETH price is 9999.99 USD", evidence_ids=["ev_001"])])

    report = validate_agent_output(result, _bundle())

    assert not report.valid
    assert any(i.code == "unsupported_number" for i in report.issues)


def test_citing_a_nonexistent_evidence_id_is_rejected() -> None:
    result = _result([Observation(text="Something happened", evidence_ids=["ev_999"])])

    report = validate_agent_output(result, _bundle())

    assert not report.valid
    assert any(i.code == "unknown_evidence_id" for i in report.issues)


def test_interpretation_without_a_citation_is_rejected() -> None:
    """Every opinion must be anchored to a fact."""
    with pytest.raises(Exception):
        # The model itself enforces min_length=1, so an uncited
        # interpretation cannot even be constructed.
        Interpretation(text="Momentum is elevated", evidence_ids=[], confidence=0.8)


def test_rounding_is_allowed() -> None:
    """Agents legitimately round. 2462 for 2462.7 is not a hallucination."""
    result = _result([Observation(text="ETH is trading near 2462 USD", evidence_ids=["ev_001"])])

    assert validate_agent_output(result, _bundle()).valid


def test_materially_wrong_number_is_still_caught() -> None:
    """The rounding tolerance must not be a loophole."""
    result = _result([Observation(text="ETH price is 2800 USD", evidence_ids=["ev_001"])])

    assert not validate_agent_output(result, _bundle()).valid


# ---------------------------------------------------------------------
# The false positive found on a live run
# ---------------------------------------------------------------------


def test_indicator_period_in_the_label_is_not_a_hallucination() -> None:
    """Regression test for a real false positive.

    On the first live multi-agent run, three of four agents were rejected
    for "stating 20.0 with no supporting evidence" -- because they wrote
    "SMA (20)", quoting the indicator's own name. The agents were right and
    the validator was wrong.
    """
    result = _result(
        [Observation(text="SMA (20) is 2469.69 USD", evidence_ids=["ev_003"])]
    )

    report = validate_agent_output(result, _bundle())

    assert report.valid, f"False positive: {report.summary()}"


def test_rsi_period_is_not_a_hallucination() -> None:
    result = _result([Observation(text="RSI (14) is 49.39", evidence_ids=["ev_002"])])

    assert validate_agent_output(result, _bundle()).valid


def test_label_numbers_do_not_excuse_a_wrong_value() -> None:
    """Allowing label numbers must not weaken the value check."""
    result = _result([Observation(text="RSI (14) is 88.5", evidence_ids=["ev_002"])])

    assert not validate_agent_output(result, _bundle()).valid


# ---------------------------------------------------------------------
# Bundle behaviour
# ---------------------------------------------------------------------


def test_missing_values_are_not_recorded_as_evidence() -> None:
    """A None value must not become a citable fact.

    Otherwise an agent could cite the absence of information as though it
    were information.
    """
    builder = EvidenceBuilder(subject="ETH")
    added = builder.add(
        EvidenceKind.INDICATOR, "SMA (200)", None,
        provider="test", method="computed",
    )

    assert added is None
    assert len(builder.build().items) == 0


def test_evidence_ids_are_sequential_and_unique() -> None:
    bundle = _bundle()
    ids = [item.evidence_id for item in bundle.items]

    assert ids == ["ev_001", "ev_002", "ev_003", "ev_004"]
    assert len(set(ids)) == len(ids)


def test_agents_only_see_their_own_evidence_kinds() -> None:
    """Narrow prompts keep agents in their lane and improve reliability."""
    bundle = _bundle()

    indicators = bundle.by_kind(EvidenceKind.INDICATOR)
    labels = {item.label for item in indicators}

    assert labels == {"RSI (14)", "SMA (20)"}
    assert "ETH price" not in labels


def test_prompt_rendering_includes_every_id() -> None:
    """The agent cannot cite ids it was never shown."""
    rendered = _bundle().render_for_prompt()

    for item in _bundle().items:
        assert item.evidence_id in rendered


def test_failures_are_recorded_on_the_bundle() -> None:
    builder = EvidenceBuilder(subject="ETH")
    builder.record_failure("No candle data available")

    assert builder.build().failures == ["No candle data available"]


def test_staleness_propagates_to_the_bundle() -> None:
    builder = EvidenceBuilder(subject="ETH")
    builder.add(
        EvidenceKind.PRICE, "ETH price", 2462.7,
        provider="coingecko", method="simple/price", is_stale=True,
    )

    assert builder.build().is_stale()
