"""Tests for the evidence contract, the validator, the risk model and hashing.

The validator tests are the ones that matter most. They are what makes
"the AI cannot state an unsupported number" a checked property rather than
a claim.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.contract import (
    AgentResult,
    AgentStatus,
    Interpretation,
    Observation,
    validate_agent_output,
)
from app.agents.reviewer import compute_deterministic_score
from app.audit.hashing import (
    GENESIS_HASH,
    canonical_json,
    compute_hash,
    format_result_id,
    verify_hash,
)
from app.evidence.types import EvidenceBuilder, EvidenceKind
from app.indicators.service import IndicatorSnapshot
from app.market.types import Price
from app.risk.scoring import WEIGHTS, compute_risk_score


def _bundle():
    builder = EvidenceBuilder("ETH")
    builder.add(
        EvidenceKind.PRICE, "ETH price", 2462.7, provider="coingecko", method="simple/price"
    )
    builder.add(
        EvidenceKind.INDICATOR, "RSI (14)", 49.39, provider="engine", method="computed"
    )
    builder.add(
        EvidenceKind.MARKET_STAT, "24h price change", 0.23, unit="%",
        provider="coingecko", method="simple/price",
    )
    return builder.build()


def _result(observations=None, interpretations=None) -> AgentResult:
    return AgentResult(
        agent="test",
        status=AgentStatus.COMPLETED,
        started_at=datetime.now(timezone.utc),
        observations=observations or [],
        interpretations=interpretations or [],
    )


# ---------------------------------------------------------------------
# Evidence bundle
# ---------------------------------------------------------------------


def test_builder_allocates_sequential_ids() -> None:
    bundle = _bundle()
    assert [i.evidence_id for i in bundle.items] == ["ev_001", "ev_002", "ev_003"]


def test_none_values_are_not_recorded_as_evidence() -> None:
    """An absent fact must not become citable evidence."""
    builder = EvidenceBuilder("ETH")
    builder.add(EvidenceKind.PRICE, "missing", None, provider="p", method="m")
    assert builder.build().items == []


def test_prompt_rendering_includes_evidence_ids() -> None:
    """The agent cannot cite ids it was never shown."""
    text = _bundle().render_for_prompt()
    assert "[ev_001]" in text and "[ev_002]" in text


def test_by_kind_filters_what_an_agent_sees() -> None:
    bundle = _bundle()
    assert len(bundle.by_kind(EvidenceKind.INDICATOR)) == 1
    assert len(bundle.by_kind(EvidenceKind.PRICE, EvidenceKind.MARKET_STAT)) == 2


def test_merging_bundles_renumbers_ids_to_stay_unique() -> None:
    from app.evidence.collectors import merge_bundles

    merged = merge_bundles("combined", _bundle(), _bundle())
    ids = [i.evidence_id for i in merged.items]

    assert len(ids) == 6
    assert len(set(ids)) == 6, "merging must renumber, or citations become ambiguous"


# ---------------------------------------------------------------------
# The validator -- the heart of the project
# ---------------------------------------------------------------------


def test_accurate_observation_passes() -> None:
    result = _result([Observation(text="ETH price is 2462.7", evidence_ids=["ev_001"])])
    assert validate_agent_output(result, _bundle()).valid


def test_hallucinated_number_is_rejected() -> None:
    """THE test. An agent stating a figure the evidence does not contain
    must be rejected even though it cited a real evidence id."""
    result = _result([Observation(text="ETH price is 9999.99", evidence_ids=["ev_001"])])

    report = validate_agent_output(result, _bundle())

    assert not report.valid
    assert any(i.code == "unsupported_number" for i in report.issues)


def test_citing_a_nonexistent_evidence_id_is_rejected() -> None:
    result = _result([Observation(text="Something", evidence_ids=["ev_999"])])

    report = validate_agent_output(result, _bundle())

    assert not report.valid
    assert any(i.code == "unknown_evidence_id" for i in report.issues)


def test_interpretation_without_a_citation_is_rejected() -> None:
    """Every opinion must be anchored to a fact."""
    with pytest.raises(Exception):
        # min_length=1 on the field means this cannot even be constructed,
        # which is the strongest possible enforcement.
        Interpretation(text="Momentum is strong", evidence_ids=[], confidence=0.8)


def test_rounded_restatement_is_accepted() -> None:
    """Agents legitimately round: 2462 for 2462.7 is fine."""
    result = _result([Observation(text="ETH is about 2462", evidence_ids=["ev_001"])])
    assert validate_agent_output(result, _bundle()).valid


def test_number_from_an_evidence_label_is_accepted() -> None:
    """'RSI (14) is 49.39' quotes both the label and the value.

    An earlier version rejected the 14 as unsupported, failing three of four
    agents on correct output. The validator was wrong, not the agents.
    """
    result = _result([Observation(text="RSI (14) is 49.39", evidence_ids=["ev_002"])])
    assert validate_agent_output(result, _bundle()).valid


def test_window_in_a_label_is_accepted() -> None:
    """'24h price change is 0.23%' -- the 24 comes from the label."""
    result = _result(
        [Observation(text="24h price change is 0.23%", evidence_ids=["ev_003"])]
    )
    assert validate_agent_output(result, _bundle()).valid


def test_label_numbers_do_not_excuse_a_genuine_hallucination() -> None:
    """Loosening the check must not make it toothless."""
    result = _result([Observation(text="RSI (14) is 88.2", evidence_ids=["ev_002"])])

    report = validate_agent_output(result, _bundle())

    assert not report.valid
    assert any(i.code == "unsupported_number" for i in report.issues)


def test_textual_observation_citing_textual_evidence_passes() -> None:
    builder = EvidenceBuilder("ETH")
    builder.add(EvidenceKind.TREND, "Trend", "uptrend", provider="engine", method="rules")
    bundle = builder.build()

    result = _result([Observation(text="The trend is classified as uptrend", evidence_ids=["ev_001"])])

    assert validate_agent_output(result, bundle).valid


# ---------------------------------------------------------------------
# Hashing and the chain
# ---------------------------------------------------------------------


def test_key_order_does_not_change_the_hash() -> None:
    assert compute_hash({"a": 1, "b": 2})[0] == compute_hash({"b": 2, "a": 1})[0]


def test_integral_floats_and_ints_hash_the_same() -> None:
    assert compute_hash({"v": 2.0})[0] == compute_hash({"v": 2})[0]


def test_identical_input_always_produces_the_identical_hash() -> None:
    """Determinism. Without it, verification could never succeed."""
    a, _ = compute_hash({"summary": "Price is rising"})
    b, _ = compute_hash({"summary": "Price is rising"})
    assert a == b


def test_changing_one_character_changes_the_hash() -> None:
    """Sensitivity. Without it, tampering could go undetected."""
    a, _ = compute_hash({"summary": "Price is rising"})
    b, _ = compute_hash({"summary": "Price is fising"})
    assert a != b


def test_volatile_fields_are_excluded_from_the_hash() -> None:
    """Timings must not make two identical results hash differently."""
    a, _ = compute_hash({"result": "x", "duration_ms": 100})
    b, _ = compute_hash({"result": "x", "duration_ms": 5000})
    assert a == b


def test_the_previous_hash_is_mixed_in() -> None:
    """This is what makes it a chain rather than independent hashes."""
    a, _ = compute_hash({"v": 1}, prev_hash="aaa")
    b, _ = compute_hash({"v": 1}, prev_hash="bbb")
    assert a != b


def test_verification_detects_tampering() -> None:
    payload = {"summary": "Original conclusion"}
    digest, canonical = compute_hash(payload, GENESIS_HASH)

    assert verify_hash(canonical, GENESIS_HASH, digest)

    tampered = canonical.replace("Original", "Altered")
    assert not verify_hash(tampered, GENESIS_HASH, digest)


def test_canonical_json_has_no_insignificant_whitespace() -> None:
    assert canonical_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'


def test_result_id_format() -> None:
    assert format_result_id(2026, 42) == "FIRE-2026-000042"


# ---------------------------------------------------------------------
# Risk model
# ---------------------------------------------------------------------


def _snapshot(**overrides) -> IndicatorSnapshot:
    defaults = dict(
        symbol="ETH",
        interval="1h",
        candle_count=300,
        last_close=2462.7,
        last_candle_time=datetime.now(timezone.utc),
        rsi_14=50.0,
        realised_volatility=0.6,
        resistance=2600.0,
    )
    defaults.update(overrides)
    return IndicatorSnapshot(**defaults)


def _price(**overrides) -> Price:
    defaults = dict(
        coingecko_id="ethereum",
        symbol="ETH",
        usd=2462.7,
        market_cap=3.0e11,
        volume_24h=1.1e10,
        fetched_at=datetime.now(timezone.utc),
        source="test",
    )
    defaults.update(overrides)
    return Price(**defaults)


def test_risk_score_is_computed_from_declared_weights() -> None:
    """The score must be defensible: a formula, not a model's opinion."""
    result = compute_risk_score(snapshot=_snapshot(), price=_price())

    assert result is not None
    assert 0 <= result.score <= 100
    assert {f.name for f in result.factors} <= set(WEIGHTS)


def test_higher_volatility_raises_the_score() -> None:
    calm = compute_risk_score(snapshot=_snapshot(realised_volatility=0.2), price=_price())
    wild = compute_risk_score(snapshot=_snapshot(realised_volatility=1.4), price=_price())

    assert calm and wild
    assert wild.score > calm.score


def test_thinner_liquidity_raises_the_score() -> None:
    """Low turnover means harder to exit -- the factor is inverted."""
    liquid = compute_risk_score(snapshot=_snapshot(), price=_price(volume_24h=3.0e10))
    thin = compute_risk_score(snapshot=_snapshot(), price=_price(volume_24h=1.0e8))

    assert liquid and thin
    assert thin.score > liquid.score


def test_extreme_rsi_in_either_direction_raises_the_score() -> None:
    neutral = compute_risk_score(snapshot=_snapshot(rsi_14=50), price=_price())
    overbought = compute_risk_score(snapshot=_snapshot(rsi_14=95), price=_price())
    oversold = compute_risk_score(snapshot=_snapshot(rsi_14=5), price=_price())

    assert neutral and overbought and oversold
    assert overbought.score > neutral.score
    assert oversold.score > neutral.score


def test_missing_inputs_reduce_coverage_rather_than_the_score() -> None:
    """A missing factor must not silently contribute zero risk."""
    partial = compute_risk_score(snapshot=None, price=_price())

    assert partial is not None
    assert partial.coverage < 1.0
    assert "missing" in partial.note


def test_risk_is_none_when_nothing_is_computable() -> None:
    """Reported as 'could not assess', never as risk zero."""
    assert compute_risk_score(snapshot=None, price=None) is None


# ---------------------------------------------------------------------
# Reviewer scoring
# ---------------------------------------------------------------------


def test_reviewer_score_rewards_coverage_and_valid_citations() -> None:
    bundle = _bundle()
    good = _result(
        [
            Observation(text="ETH price is 2462.7", evidence_ids=["ev_001"]),
            Observation(text="RSI (14) is 49.39", evidence_ids=["ev_002"]),
            Observation(text="24h change is 0.23%", evidence_ids=["ev_003"]),
        ]
    )
    good.agent = "market"

    score, components = compute_deterministic_score(bundle, [good], {})

    assert components["evidence_coverage"] == 1.0
    assert score > 60


def test_reviewer_score_falls_when_agents_fail() -> None:
    bundle = _bundle()
    ok = _result([Observation(text="ETH price is 2462.7", evidence_ids=["ev_001"])])
    ok.agent = "market"

    failed = _result()
    failed.agent = "technical"
    failed.status = AgentStatus.FAILED

    with_failure, _ = compute_deterministic_score(bundle, [ok, failed], {})
    without_failure, _ = compute_deterministic_score(bundle, [ok], {})

    assert with_failure < without_failure


def test_stale_data_caps_the_reviewer_score() -> None:
    """An analysis of old numbers cannot be excellent, however well argued."""
    builder = EvidenceBuilder("ETH")
    builder.add(
        EvidenceKind.PRICE, "ETH price", 2462.7,
        provider="coingecko", method="simple/price", is_stale=True,
    )
    stale_bundle = builder.build()

    result = _result([Observation(text="ETH price is 2462.7", evidence_ids=["ev_001"])])
    result.agent = "market"

    score, _ = compute_deterministic_score(stale_bundle, [result], {})

    assert score <= 75.0


def test_skipped_agents_do_not_count_as_failures() -> None:
    bundle = _bundle()
    ok = _result([Observation(text="ETH price is 2462.7", evidence_ids=["ev_001"])])
    ok.agent = "market"

    skipped = _result()
    skipped.agent = "portfolio"
    skipped.status = AgentStatus.SKIPPED

    with_skip, _ = compute_deterministic_score(bundle, [ok, skipped], {})
    alone, _ = compute_deterministic_score(bundle, [ok], {})

    assert with_skip == alone
