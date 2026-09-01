"""Analysis, history and verification endpoints.

The analysis endpoint streams. A full multi-agent run takes 20-90 seconds,
and a request that returns nothing for a minute looks broken. Server-sent
events let the interface show each agent starting and finishing as it
happens, which also makes the architecture visible rather than hidden.

SSE is used rather than WebSockets because this is a one-directional stream
of progress updates -- exactly SSE's shape -- and it is plain HTTP with
automatic reconnection and no extra protocol.
"""

import asyncio
import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator import detect_conflicts, run_analysis
from app.audit.auditor import measure, record_analysis, verify_analysis
from app.blockchain.adapters.evm import EvmAdapter
from app.blockchain.factory import get_adapter
from app.config import Settings, get_settings
from app.core.errors import ChainNotSupportedError, FireDexError, NotFoundError
from app.core.logging import get_logger
from app.database.models import AgentExecution, Analysis
from app.database.session import get_db
from app.evidence.collectors import (
    collect_asset_evidence,
    collect_chain_evidence,
    collect_portfolio_evidence,
    merge_bundles,
)
from app.llm.service import LlmService, get_llm_service
from app.indicators.service import build_snapshot
from app.market.candles import get_candle_provider
from app.market.service import MarketDataService, get_market_service
from app.tokens.registry import get_token

log = get_logger(__name__)

router = APIRouter(tags=["analysis"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
MarketDep = Annotated[MarketDataService, Depends(get_market_service)]
LlmDep = Annotated[LlmService, Depends(get_llm_service)]
DbDep = Annotated[AsyncSession, Depends(get_db)]


class AnalysisRequest(BaseModel):
    """What to analyse."""

    symbol: str | None = Field(default=None, description="Asset symbol, e.g. 'ETH'")
    chain: str | None = Field(default=None, description="Chain key for portfolio analysis")
    address: str | None = Field(default=None, description="Wallet address to include")
    interval: str = Field(default="1h", description="Candle interval for indicators")
    prefer: str | None = Field(default=None, description="'local' or 'online' model")
    query: str | None = Field(default=None, description="The user's original question")


class AnalysisSummary(BaseModel):
    """One row in the history list."""

    result_id: str
    query: str
    subject: str
    chain: str | None
    model: str | None
    provider: str | None
    mode: str | None
    reviewer_score: float | None
    reviewer_verdict: str | None
    confidence: float | None
    signal: str | None = None
    signal_score: float | None = None
    groundedness: float | None = None
    evidence_count: int
    evidence_coverage: float | None
    agents_completed: int
    agents_failed: int
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    data_stale: bool
    result_hash: str
    created_at: datetime


class AnalysisDetail(AnalysisSummary):
    """Full drill-down for one analysis."""

    address: str | None
    summary: str | None
    evidence: list[dict]
    agent_results: list[dict]
    reviewer_result: dict | None
    suggestion_result: dict | None
    executions: list[dict]
    prev_hash: str
    canonical_json: str


def _to_summary(row: Analysis) -> AnalysisSummary:
    return AnalysisSummary(
        result_id=row.result_id,
        query=row.query,
        subject=row.subject,
        chain=row.chain,
        model=row.model,
        provider=row.provider,
        mode=row.mode,
        reviewer_score=row.reviewer_score,
        reviewer_verdict=row.reviewer_verdict,
        confidence=row.confidence,
        signal=row.signal,
        signal_score=row.signal_score,
        groundedness=row.groundedness,
        evidence_count=row.evidence_count,
        evidence_coverage=row.evidence_coverage,
        agents_completed=row.agents_completed,
        agents_failed=row.agents_failed,
        duration_ms=row.duration_ms,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        data_stale=row.data_stale,
        result_hash=row.result_hash,
        created_at=row.created_at,
    )


async def _build_bundle(
    request: AnalysisRequest, settings: Settings, market: MarketDataService
):
    """Collect all evidence for a request. Deterministic; no model involved."""
    bundles = []
    subject_parts = []
    snapshot = None

    if request.symbol:
        symbol = request.symbol.upper()
        subject_parts.append(symbol)
        bundles.append(
            await collect_asset_evidence(
                symbol, market=market, candles=get_candle_provider(), interval=request.interval
            )
        )
        # The signal engine votes over indicator values, so it needs the
        # snapshot rather than the evidence bundle. Fetched here because the
        # candle provider caches, so this costs nothing extra.
        try:
            candles = await get_candle_provider().get_candles(symbol, request.interval, 300)
            if candles:
                snapshot = build_snapshot(symbol, request.interval, candles)
        except Exception:  # noqa: BLE001 - no candles simply means no signal
            snapshot = None

    if request.chain and request.address:
        adapter = get_adapter(request.chain, settings)
        if not isinstance(adapter, EvmAdapter):
            raise ChainNotSupportedError(
                f"Analysis is not implemented for {request.chain} yet."
            )
        subject_parts.append(f"{request.chain} wallet")
        bundles.append(await collect_chain_evidence(request.chain, adapter))
        bundles.append(
            await collect_portfolio_evidence(
                request.chain, request.address, adapter=adapter, market=market
            )
        )

    if not bundles:
        raise FireDexError(
            "Nothing to analyse.",
            detail="Provide a symbol, or a chain and address, or both.",
        )

    merged = merge_bundles(" + ".join(subject_parts), *bundles)
    merged.chain = request.chain
    merged.address = request.address
    return merged, snapshot


@router.post("/analysis/stream")
async def stream_analysis(
    request: AnalysisRequest,
    settings: SettingsDep,
    market: MarketDep,
    llm_service: LlmDep,
    db: DbDep,
) -> StreamingResponse:
    """Run an analysis, streaming progress as server-sent events.

    Event types: evidence, plan, agent_status, agents_complete, reanalysis,
    audit, complete, error.
    """
    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def on_progress(event: dict) -> None:
        await queue.put(event)

    async def work() -> None:
        try:
            query = request.query or f"Analyse {request.symbol or request.address}"

            bundle, snapshot = await _build_bundle(request, settings, market)
            await queue.put(
                {
                    "type": "evidence",
                    "count": len(bundle.items),
                    "subject": bundle.subject,
                    "failures": bundle.failures,
                    "stale": bundle.is_stale(),
                }
            )

            llm = await llm_service.get_provider(request.prefer)
            await queue.put(
                {"type": "model", "model": llm.model, "provider": llm.name, "mode": llm.mode}
            )

            outcome = await run_analysis(
                query,
                bundle,
                llm,
                on_progress=on_progress,
                max_reanalysis=settings.max_reanalysis_attempts,
                snapshot=snapshot,
            )

            metrics = measure(
                outcome.bundle, outcome.results, outcome.validations, outcome.duration_ms
            )
            conflicts = detect_conflicts(outcome.results)

            analysis = await record_analysis(
                db,
                query=query,
                bundle=outcome.bundle,
                results=outcome.results,
                validations=outcome.validations,
                reviewer=outcome.reviewer.model_dump(mode="json"),
                suggestion=(
                    outcome.suggestion.model_dump(mode="json") if outcome.suggestion else None
                ),
                summary=outcome.summary,
                metrics=metrics,
                model=llm.model,
                provider=llm.name,
                mode=llm.mode,
            )

            await queue.put(
                {
                    "type": "audit",
                    "result_id": analysis.result_id,
                    "hash": analysis.result_hash,
                    "prev_hash": analysis.prev_hash,
                    "metrics": metrics.model_dump(mode="json"),
                }
            )
            await queue.put(
                {
                    "type": "complete",
                    "result_id": analysis.result_id,
                    "summary": outcome.summary,
                    "reviewer": outcome.reviewer.model_dump(mode="json"),
                    "suggestion": (
                        outcome.suggestion.model_dump(mode="json") if outcome.suggestion else None
                    ),
                    "conflicts": conflicts,
                    "attempts": outcome.attempts,
                    "duration_ms": outcome.duration_ms,
                    "hash": analysis.result_hash,
                }
            )
        except FireDexError as exc:
            await queue.put({"type": "error", "message": exc.message, "detail": exc.detail})
        except Exception as exc:  # noqa: BLE001
            log.warning("analysis_failed", error=str(exc))
            await queue.put({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)

    async def event_stream():
        task = asyncio.create_task(work())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Stops nginx and similar from buffering the stream, which would
            # defeat the point by delivering everything at the end.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/analysis/history", response_model=list[AnalysisSummary])
async def get_history(
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    subject: Annotated[str | None, Query(description="Filter by subject")] = None,
) -> list[AnalysisSummary]:
    """Past analyses, newest first."""
    statement = select(Analysis).order_by(Analysis.id.desc()).limit(limit)
    if subject:
        statement = statement.where(Analysis.subject.ilike(f"%{subject}%"))

    rows = (await db.scalars(statement)).all()
    return [_to_summary(row) for row in rows]


@router.get("/analysis/{result_id}", response_model=AnalysisDetail)
async def get_analysis(
    result_id: Annotated[str, Path(description="e.g. FIRE-2026-000042")],
    db: DbDep,
) -> AnalysisDetail:
    """Full drill-down: evidence, agents, reviewer, audit metrics, hash."""
    row = await db.scalar(select(Analysis).where(Analysis.result_id == result_id))
    if row is None:
        raise NotFoundError(f"No analysis with id {result_id}.")

    executions = (
        await db.scalars(
            select(AgentExecution)
            .where(AgentExecution.analysis_id == row.id)
            .order_by(AgentExecution.id)
        )
    ).all()

    summary = _to_summary(row)
    return AnalysisDetail(
        **summary.model_dump(),
        address=row.address,
        summary=row.summary,
        evidence=row.evidence,
        agent_results=row.agent_results,
        reviewer_result=row.reviewer_result,
        suggestion_result=row.suggestion_result,
        prev_hash=row.prev_hash,
        canonical_json=row.canonical_json,
        executions=[
            {
                "agent": e.agent,
                "status": e.status,
                "started_at": e.started_at,
                "ended_at": e.ended_at,
                "duration_ms": e.duration_ms,
                "model": e.model,
                "input_tokens": e.input_tokens,
                "output_tokens": e.output_tokens,
                "observation_count": e.observation_count,
                "interpretation_count": e.interpretation_count,
                "validation_passed": e.validation_passed,
                "validation_issues": e.validation_issues,
                "error": e.error,
            }
            for e in executions
        ],
    )


@router.get("/analysis/{result_id}/verify")
async def verify(
    result_id: Annotated[str, Path(description="e.g. FIRE-2026-000042")],
    db: DbDep,
) -> dict[str, Any]:
    """Recompute a stored record's hash and report whether it still matches.

    This is the integrity demonstration: alter a stored record and this
    endpoint reports RESULT INTEGRITY FAILURE.
    """
    result = await verify_analysis(db, result_id)
    if result is None:
        raise NotFoundError(f"No analysis with id {result_id}.")
    return result.model_dump()


@router.get("/audit/stats")
async def audit_stats(db: DbDep) -> dict[str, Any]:
    """Aggregate metrics across every recorded analysis.

    These are the numbers to present as results. Note what is absent:
    prediction accuracy, which needs ground truth we do not yet have.
    """
    total = await db.scalar(select(func.count()).select_from(Analysis)) or 0
    if total == 0:
        return {"total_analyses": 0, "note": "No analyses recorded yet."}

    averages = (
        await db.execute(
            select(
                func.avg(Analysis.reviewer_score),
                func.avg(Analysis.evidence_coverage),
                func.avg(Analysis.citation_validity),
                func.avg(Analysis.duration_ms),
                func.sum(Analysis.input_tokens),
                func.sum(Analysis.output_tokens),
                func.sum(Analysis.agents_failed),
            )
        )
    ).one()

    # Count validation passes with a CASE rather than casting a boolean.
    # `func.cast(col, type_=None)` produced NullType and a CompileError --
    # SQLAlchemy cannot generate DDL without an explicit type.
    by_agent = (
        await db.execute(
            select(
                AgentExecution.agent,
                func.count(),
                func.avg(AgentExecution.duration_ms),
                func.sum(case((AgentExecution.validation_passed.is_(True), 1), else_=0)),
                func.sum(case((AgentExecution.status == "completed", 1), else_=0)),
            ).group_by(AgentExecution.agent)
        )
    ).all()

    return {
        "total_analyses": total,
        "average_reviewer_score": round(averages[0], 2) if averages[0] else None,
        "average_evidence_coverage": round(averages[1], 4) if averages[1] else None,
        "average_citation_validity": round(averages[2], 4) if averages[2] else None,
        "average_duration_ms": int(averages[3]) if averages[3] else None,
        "total_input_tokens": averages[4],
        "total_output_tokens": averages[5],
        "total_agent_failures": averages[6],
        "per_agent": [
            {
                "agent": row[0],
                "runs": row[1],
                "avg_duration_ms": int(row[2] or 0),
                "validation_passed": row[3] or 0,
                "completed": row[4] or 0,
            }
            for row in by_agent
        ],
        "accuracy_note": (
            "Prediction accuracy is deliberately not reported. It requires ground "
            "truth -- comparing predictions against outcomes -- which the 8th-semester "
            "Fire Trade extension is designed to establish using this archive."
        ),
    }


@router.get("/ai/status")
async def ai_status(llm_service: LlmDep) -> dict[str, Any]:
    """Which AI providers are usable right now."""
    return await llm_service.describe_availability()
