"""Database schema.

Design notes:

VARIABLE PAYLOADS ARE JSON. Agent outputs will change shape as prompts and
agents evolve. Storing them in rigid columns would force a migration for
every prompt change. The fields we actually query -- status, duration,
score, model -- are proper columns; the rest is JSON.

THE HASH CHAIN LIVES IN `analyses`. Each row stores the previous row's hash,
so the records form a chain. `canonical_json` is stored alongside so a
verifier can recompute the hash without reproducing our serialisation code.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Analysis(Base):
    """One completed analysis, with its audit record and hash."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Human-quotable identifier, e.g. FIRE-2026-000042
    result_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)

    query: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(String(64), index=True)
    chain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- AI configuration, recorded so a run can be reproduced ---
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # --- results ---
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    agent_results: Mapped[list] = mapped_column(JSON, default=list)
    reviewer_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # --- Fire Auditor metrics ---
    agent_count: Mapped[int] = mapped_column(Integer, default=0)
    agents_completed: Mapped[int] = mapped_column(Integer, default=0)
    agents_failed: Mapped[int] = mapped_column(Integer, default=0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    citation_validity: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewer_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewer_verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_stale: Mapped[bool] = mapped_column(default=False)

    # --- integrity ---
    canonical_json: Mapped[str] = mapped_column(Text)
    result_hash: Mapped[str] = mapped_column(String(64), index=True)
    prev_hash: Mapped[str] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    executions: Mapped[list["AgentExecution"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_analyses_created_at", "created_at"),)


class AgentExecution(Base):
    """Observability record for one agent run within an analysis.

    Separate from the JSON blob in `Analysis.agent_results` because these
    fields are queried for aggregate metrics -- average duration per agent,
    failure rates -- and querying inside JSON is awkward and slow.
    """

    __tablename__ = "agent_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))

    agent: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    observation_count: Mapped[int] = mapped_column(Integer, default=0)
    interpretation_count: Mapped[int] = mapped_column(Integer, default=0)
    validation_passed: Mapped[bool] = mapped_column(default=True)
    validation_issues: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    analysis: Mapped[Analysis] = relationship(back_populates="executions")
