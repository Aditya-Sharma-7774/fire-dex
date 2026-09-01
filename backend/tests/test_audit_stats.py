"""Tests for the aggregate audit statistics endpoint.

This endpoint produces the numbers presented as the project's results, so a
silent failure here would be embarrassing at exactly the wrong moment. It
shipped broken: `func.cast(col, type_=None)` produced a NullType and a
CompileError, and nothing caught it until the endpoint was called by hand.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.analysis import audit_stats
from app.database.models import AgentExecution, Analysis, Base


@pytest.fixture
async def session() -> AsyncSession:
    """A throwaway in-memory database for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        yield db

    await engine.dispose()


async def test_stats_on_an_empty_database(session: AsyncSession) -> None:
    """No analyses yet must be a clean answer, not a crash or a fake zero."""
    stats = await audit_stats(session)

    assert stats["total_analyses"] == 0
    assert "note" in stats


async def _add_analysis(session: AsyncSession, **overrides) -> Analysis:
    from datetime import datetime, timezone

    defaults = dict(
        result_id=f"FIRE-2026-{overrides.pop('n', 1):06d}",
        query="Analyse ETH",
        subject="ETH",
        model="test-model",
        provider="test",
        mode="online",
        summary="…",
        evidence=[],
        agent_results=[],
        agent_count=2,
        agents_completed=2,
        agents_failed=0,
        evidence_count=10,
        evidence_coverage=0.5,
        citation_validity=1.0,
        reviewer_score=70.0,
        reviewer_verdict="APPROVED",
        input_tokens=100,
        output_tokens=200,
        duration_ms=8000,
        canonical_json="{}",
        result_hash="a" * 64,
        prev_hash="0" * 64,
    )
    defaults.update(overrides)
    analysis = Analysis(**defaults)
    session.add(analysis)
    await session.flush()

    session.add(
        AgentExecution(
            analysis_id=analysis.id,
            agent="market_intelligence",
            status="completed",
            started_at=datetime.now(timezone.utc),
            duration_ms=3000,
            validation_passed=True,
        )
    )
    await session.commit()
    return analysis


async def test_stats_aggregate_correctly(session: AsyncSession) -> None:
    await _add_analysis(session, n=1, reviewer_score=60.0)
    await _add_analysis(session, n=2, reviewer_score=80.0)

    stats = await audit_stats(session)

    assert stats["total_analyses"] == 2
    assert stats["average_reviewer_score"] == 70.0
    assert stats["total_input_tokens"] == 200
    assert stats["total_output_tokens"] == 400


async def test_per_agent_breakdown_is_returned(session: AsyncSession) -> None:
    """Regression: this is the query that raised CompileError."""
    await _add_analysis(session, n=1)

    stats = await audit_stats(session)
    agents = stats["per_agent"]

    assert len(agents) == 1
    assert agents[0]["agent"] == "market_intelligence"
    assert agents[0]["runs"] == 1
    assert agents[0]["completed"] == 1
    assert agents[0]["validation_passed"] == 1


async def test_accuracy_is_never_reported(session: AsyncSession) -> None:
    """The project must not claim prediction accuracy without ground truth.

    Asserted as a test so the claim cannot be reintroduced by accident.
    """
    await _add_analysis(session, n=1)

    stats = await audit_stats(session)

    assert "accuracy" not in {k.lower() for k in stats if k != "accuracy_note"}
    assert "ground truth" in stats["accuracy_note"].lower()
