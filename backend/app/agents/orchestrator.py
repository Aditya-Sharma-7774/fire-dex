"""The Orchestrator.

Plans which agents are needed, runs them concurrently, reconciles their
output, sends it to the reviewer, and hands the result to Fire Auditor.

WHY NOT LANGGRAPH (YET)
-----------------------
The architecture document proposed LangGraph, justified specifically by the
reviewer's REANALYZE cycle. Having built the pipeline, that cycle is a
single bounded retry -- one conditional edge -- and expressing it directly
in Python is clearer to read and to explain than adding a graph framework
and its state model.

The seam is kept: `run_analysis` is a plain async function over typed
state, so moving to LangGraph when the graph genuinely branches (parallel
sub-analyses, multi-step tool use) is a contained change. Adding the
dependency now would be complexity we cannot yet justify, and the project's
own rules say to explain why a technology is needed before introducing it.

Progress is emitted through a callback so the interface can show agents
executing live, rather than freezing on a spinner for a minute.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from app.agents.contract import AgentResult, AgentStatus, ValidationReport
from app.agents.reviewer import ReviewerResult, Verdict, build_summary, review
from app.agents.specialists import (
    MarketIntelligenceAgent,
    OnChainAgent,
    PortfolioAgent,
    RiskAgent,
    TechnicalAnalysisAgent,
)
from app.core.logging import get_logger
from app.evidence.types import EvidenceBundle
from app.llm.provider import LlmProvider

log = get_logger(__name__)

ProgressCallback = Callable[[dict], Awaitable[None]]

#: Order matters only for display; execution is concurrent.
DEFAULT_AGENTS = [
    MarketIntelligenceAgent,
    TechnicalAnalysisAgent,
    RiskAgent,
    PortfolioAgent,
    OnChainAgent,
]


class AnalysisOutcome:
    """Everything one analysis produced."""

    def __init__(
        self,
        bundle: EvidenceBundle,
        results: list[AgentResult],
        validations: dict[str, ValidationReport],
        reviewer: ReviewerResult,
        summary: str,
        duration_ms: int,
        attempts: int,
    ) -> None:
        self.bundle = bundle
        self.results = results
        self.validations = validations
        self.reviewer = reviewer
        self.summary = summary
        self.duration_ms = duration_ms
        self.attempts = attempts


def plan_agents(bundle: EvidenceBundle) -> list[type]:
    """Choose which agents to run.

    An agent with no relevant evidence would produce nothing useful, so it
    is left out of the plan entirely rather than run and reported as empty.
    `evidence_kinds` is a class attribute, so this needs no instantiation.
    """
    return [
        cls
        for cls in DEFAULT_AGENTS
        if cls.evidence_kinds and bundle.by_kind(*cls.evidence_kinds)
    ]


async def run_analysis(
    query: str,
    bundle: EvidenceBundle,
    llm: LlmProvider,
    *,
    on_progress: ProgressCallback | None = None,
    max_reanalysis: int = 1,
) -> AnalysisOutcome:
    """Run the full pipeline."""
    started = datetime.now(timezone.utc)

    async def emit(event: dict) -> None:
        if on_progress:
            await on_progress(event)

    agent_classes = plan_agents(bundle)

    await emit(
        {
            "type": "plan",
            "agents": [cls.name for cls in agent_classes],  # type: ignore[attr-defined]
            "evidence_count": len(bundle.items),
            "failures": bundle.failures,
        }
    )

    if not agent_classes:
        ended = datetime.now(timezone.utc)
        empty_reviewer = await review(llm, bundle, [], {})
        return AnalysisOutcome(
            bundle=bundle,
            results=[],
            validations={},
            reviewer=empty_reviewer,
            summary="No evidence was available, so no analysis could be performed.",
            duration_ms=int((ended - started).total_seconds() * 1000),
            attempts=1,
        )

    results: list[AgentResult] = []
    validations: dict[str, ValidationReport] = {}
    attempts = 0

    while attempts <= max_reanalysis:
        attempts += 1
        results, validations = await _run_agents(agent_classes, bundle, llm, emit)

        await emit({"type": "agents_complete", "completed": len(results)})
        await emit({"type": "agent_status", "agent": "reviewer", "status": "running"})

        reviewer = await review(llm, bundle, results, validations)

        await emit(
            {
                "type": "agent_status",
                "agent": "reviewer",
                "status": "completed",
                "verdict": reviewer.verdict.value,
                "score": reviewer.score,
            }
        )

        # The one cycle in the pipeline. Bounded, so a persistent
        # disagreement between reviewer and agents cannot loop forever.
        if reviewer.verdict is Verdict.REANALYZE and attempts <= max_reanalysis:
            log.info("reviewer_requested_reanalysis", score=reviewer.score, attempt=attempts)
            await emit({"type": "reanalysis", "reason": reviewer.reasoning, "attempt": attempts})
            continue

        break

    ended = datetime.now(timezone.utc)
    duration_ms = int((ended - started).total_seconds() * 1000)
    summary = build_summary(results, reviewer)

    await emit({"type": "agent_status", "agent": "fire_auditor", "status": "running"})

    return AnalysisOutcome(
        bundle=bundle,
        results=results,
        validations=validations,
        reviewer=reviewer,
        summary=summary,
        duration_ms=duration_ms,
        attempts=attempts,
    )


async def _run_agents(
    agent_classes: list[type],
    bundle: EvidenceBundle,
    llm: LlmProvider,
    emit: ProgressCallback,
) -> tuple[list[AgentResult], dict[str, ValidationReport]]:
    """Run every planned agent concurrently.

    Concurrency is the whole reason this is bearable: five agents at roughly
    eight seconds each would be forty seconds sequentially, and is closer to
    the slowest single agent when run together.
    """

    # Concurrency is capped by what the PROVIDER can actually serve.
    #
    # Measured: firing four agents at a local Ollama instance simultaneously
    # made all four time out at 120 seconds, even though a single warm
    # request answers in under two. Ollama loads one copy of the model and
    # serves largely serially, so parallel requests queue and thrash. A
    # hosted API has no such constraint.
    limit = asyncio.Semaphore(getattr(llm, "max_concurrency", 3))

    async def run_one(cls: type) -> tuple[AgentResult, ValidationReport]:
        agent = cls(llm)  # type: ignore[call-arg]
        await emit({"type": "agent_status", "agent": agent.name, "status": "running"})
        try:
            async with limit:
                result, report = await agent.run(bundle)
        except Exception as exc:  # noqa: BLE001 - one agent must not kill the run
            from app.agents.contract import failed_result

            log.warning("agent_crashed", agent=cls.name, error=str(exc))  # type: ignore[attr-defined]
            result = failed_result(cls.name, f"Agent crashed: {exc}")  # type: ignore[attr-defined]
            report = ValidationReport(valid=True)

        await emit(
            {
                "type": "agent_status",
                "agent": result.agent,
                "status": result.status.value,
                "duration_ms": result.duration_ms,
                "observations": len(result.observations),
                "interpretations": len(result.interpretations),
                "tokens": result.total_tokens,
                "errors": result.errors,
            }
        )
        return result, report

    pairs = await asyncio.gather(*(run_one(cls) for cls in agent_classes))

    results = [pair[0] for pair in pairs]
    validations = {pair[0].agent: pair[1] for pair in pairs}
    return results, validations


def detect_conflicts(results: list[AgentResult]) -> list[str]:
    """Flag agents whose interpretations point in opposite directions.

    Deliberately conservative keyword matching over interpretation text. It
    is a signal for the reviewer to examine, not an automated judgement --
    and a flagged conflict is surfaced to the user rather than resolved
    silently in favour of one agent.
    """
    bullish = {"upward", "bullish", "strength", "rising", "accumulation", "uptrend"}
    bearish = {"downward", "bearish", "weakness", "falling", "distribution", "downtrend"}

    leanings: dict[str, set[str]] = {}
    for result in results:
        if result.status is not AgentStatus.COMPLETED:
            continue
        text = " ".join(i.text.lower() for i in result.interpretations)
        found = set()
        if any(word in text for word in bullish):
            found.add("bullish")
        if any(word in text for word in bearish):
            found.add("bearish")
        if found:
            leanings[result.agent] = found

    conflicts: list[str] = []
    agents = list(leanings)
    for i, first in enumerate(agents):
        for second in agents[i + 1 :]:
            if leanings[first] and leanings[second] and leanings[first] != leanings[second]:
                if "bullish" in leanings[first] and "bearish" in leanings[second]:
                    conflicts.append(f"{first} leans bullish while {second} leans bearish")
                elif "bearish" in leanings[first] and "bullish" in leanings[second]:
                    conflicts.append(f"{first} leans bearish while {second} leans bullish")

    return conflicts
