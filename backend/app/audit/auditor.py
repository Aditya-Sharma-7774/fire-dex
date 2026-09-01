"""Fire Auditor: measures, records and hashes every completed analysis.

WHAT WE MEASURE, AND WHY NOT ACCURACY
-------------------------------------
This semester we measure what is genuinely measurable:

    execution time · token usage · evidence coverage · citation validity
    reviewer score · agent agreement · data freshness · confidence

We deliberately do NOT report prediction accuracy. Accuracy requires ground
truth -- comparing a prediction against what actually happened -- and that
is what the 8th-semester Fire Trade extension is designed to establish,
using the archive this auditor builds. Quoting an accuracy figure now,
without an evaluation dataset, would be unsupported.

Every record is canonicalised, hashed with SHA-256 and chained to the
previous record's hash.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contract import AgentResult, AgentStatus, ValidationReport
from app.audit.hashing import GENESIS_HASH, compute_hash, format_result_id, verify_hash
from app.core.logging import get_logger
from app.database.models import AgentExecution, Analysis
from app.evidence.types import EvidenceBundle

log = get_logger(__name__)


class AuditMetrics(BaseModel):
    """Everything Fire Auditor measured about one analysis."""

    agent_count: int
    agents_completed: int
    agents_failed: int
    evidence_count: int
    evidence_coverage: float = Field(
        description="Fraction of collected evidence that at least one agent cited"
    )
    citation_validity: float = Field(
        description="Fraction of agent claims whose citations all resolved"
    )
    input_tokens: int | None
    output_tokens: int | None
    duration_ms: int
    data_stale: bool
    oldest_data_timestamp: datetime | None


def measure(
    bundle: EvidenceBundle,
    results: list[AgentResult],
    validations: dict[str, ValidationReport],
    duration_ms: int,
) -> AuditMetrics:
    """Compute the audit metrics for one analysis.

    Evidence coverage answers: of everything we gathered, how much did the
    agents actually use? Low coverage means the analysis ignored available
    information, which is a genuine quality signal.
    """
    completed = [r for r in results if r.status is AgentStatus.COMPLETED]
    failed = [r for r in results if r.status is AgentStatus.FAILED]

    cited: set[str] = set()
    for result in completed:
        cited.update(result.all_evidence_ids())

    available = bundle.ids()
    coverage = len(cited & available) / len(available) if available else 0.0

    total_claims = sum(len(r.observations) + len(r.interpretations) for r in completed)
    invalid_claims = sum(
        len([i for i in report.issues if i.code in {"unknown_evidence_id"}])
        for report in validations.values()
    )
    validity = 1.0 if total_claims == 0 else max(0.0, 1.0 - invalid_claims / total_claims)

    input_tokens = sum(r.input_tokens or 0 for r in results) or None
    output_tokens = sum(r.output_tokens or 0 for r in results) or None

    return AuditMetrics(
        agent_count=len(results),
        agents_completed=len(completed),
        agents_failed=len(failed),
        evidence_count=len(bundle.items),
        evidence_coverage=round(coverage, 4),
        citation_validity=round(validity, 4),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=duration_ms,
        data_stale=bundle.is_stale(),
        oldest_data_timestamp=bundle.oldest_data_timestamp(),
    )


async def _next_sequence(session: AsyncSession, year: int) -> int:
    """Next sequence number for a result id within a year."""
    prefix = f"FIRE-{year}-"
    count = await session.scalar(
        select(func.count()).select_from(Analysis).where(Analysis.result_id.like(f"{prefix}%"))
    )
    return (count or 0) + 1


async def _latest_hash(session: AsyncSession) -> str:
    """Hash of the most recent record, or the genesis value if none."""
    latest = await session.scalar(select(Analysis).order_by(Analysis.id.desc()).limit(1))
    return latest.result_hash if latest else GENESIS_HASH


async def record_analysis(
    session: AsyncSession,
    *,
    query: str,
    bundle: EvidenceBundle,
    results: list[AgentResult],
    validations: dict[str, ValidationReport],
    reviewer: dict | None,
    summary: str | None,
    metrics: AuditMetrics,
    model: str | None,
    provider: str | None,
    mode: str | None,
) -> Analysis:
    """Persist an analysis with its hash, chained to the previous record."""
    now = datetime.now(timezone.utc)
    sequence = await _next_sequence(session, now.year)
    result_id = format_result_id(now.year, sequence)
    prev_hash = await _latest_hash(session)

    evidence_payload = [item.model_dump(mode="json") for item in bundle.items]
    agent_payload = [r.model_dump(mode="json") for r in results]

    # The canonical payload is what actually gets hashed. It deliberately
    # contains the substance of the result -- query, evidence, agent output,
    # review -- and not volatile metadata like timings.
    payload = {
        "result_id": result_id,
        "query": query,
        "subject": bundle.subject,
        "chain": bundle.chain,
        "address": bundle.address,
        "model": model,
        "provider": provider,
        "mode": mode,
        "evidence": evidence_payload,
        "agent_results": agent_payload,
        "reviewer": reviewer,
        "summary": summary,
    }

    result_hash, canonical = compute_hash(payload, prev_hash)

    analysis = Analysis(
        result_id=result_id,
        query=query,
        subject=bundle.subject,
        chain=bundle.chain,
        address=bundle.address,
        model=model,
        provider=provider,
        mode=mode,
        summary=summary,
        evidence=evidence_payload,
        agent_results=agent_payload,
        reviewer_result=reviewer,
        agent_count=metrics.agent_count,
        agents_completed=metrics.agents_completed,
        agents_failed=metrics.agents_failed,
        evidence_count=metrics.evidence_count,
        evidence_coverage=metrics.evidence_coverage,
        citation_validity=metrics.citation_validity,
        reviewer_score=(reviewer or {}).get("score"),
        reviewer_verdict=(reviewer or {}).get("verdict"),
        confidence=(reviewer or {}).get("confidence"),
        input_tokens=metrics.input_tokens,
        output_tokens=metrics.output_tokens,
        duration_ms=metrics.duration_ms,
        data_stale=metrics.data_stale,
        canonical_json=canonical,
        result_hash=result_hash,
        prev_hash=prev_hash,
    )
    session.add(analysis)
    await session.flush()

    for result in results:
        report = validations.get(result.agent)
        session.add(
            AgentExecution(
                analysis_id=analysis.id,
                agent=result.agent,
                status=result.status.value,
                started_at=result.started_at,
                ended_at=result.ended_at,
                duration_ms=result.duration_ms,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                observation_count=len(result.observations),
                interpretation_count=len(result.interpretations),
                validation_passed=report.valid if report else True,
                validation_issues=(
                    [i.model_dump() for i in report.issues] if report else []
                ),
                error="; ".join(result.errors) if result.errors else None,
            )
        )

    await session.commit()
    log.info(
        "analysis_recorded",
        result_id=result_id,
        hash=result_hash[:16],
        coverage=metrics.evidence_coverage,
    )
    return analysis


class VerificationResult(BaseModel):
    """Outcome of re-checking a stored record's integrity."""

    result_id: str
    valid: bool
    stored_hash: str
    computed_hash: str
    chain_intact: bool
    message: str


async def verify_analysis(session: AsyncSession, result_id: str) -> VerificationResult | None:
    """Recompute a record's hash and check it still matches.

    Two checks:
      1. Does the stored canonical form still hash to the stored hash?
         (Was this record altered?)
      2. Does the previous record still have the hash we recorded for it?
         (Was an EARLIER record altered?)

    The second is what the chain buys us: editing an old record is detected
    even when the edited record's own hash is updated to match.
    """
    analysis = await session.scalar(select(Analysis).where(Analysis.result_id == result_id))
    if analysis is None:
        return None

    import hashlib

    computed = hashlib.sha256(
        f"{analysis.prev_hash}:{analysis.canonical_json}".encode("utf-8")
    ).hexdigest()
    intact = verify_hash(analysis.canonical_json, analysis.prev_hash, analysis.result_hash)

    chain_intact = True
    if analysis.id > 1:
        previous = await session.scalar(
            select(Analysis).where(Analysis.id < analysis.id).order_by(Analysis.id.desc()).limit(1)
        )
        if previous is not None:
            chain_intact = previous.result_hash == analysis.prev_hash

    if intact and chain_intact:
        message = "Record is intact and correctly chained to the previous record."
    elif not intact:
        message = "RESULT INTEGRITY FAILURE: this record has been altered since it was written."
    else:
        message = "CHAIN BROKEN: an earlier record has been altered."

    return VerificationResult(
        result_id=result_id,
        valid=intact and chain_intact,
        stored_hash=analysis.result_hash,
        computed_hash=computed,
        chain_intact=chain_intact,
        message=message,
    )
