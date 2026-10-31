"""The Reviewer.

WHY THE SCORE IS MOSTLY COMPUTED
--------------------------------
Letting a language model grade its own output is circular reasoning: we
would be using the same class of system whose reliability we are trying to
establish as the judge of that reliability.

So the reviewer is a hybrid:

  computed by code          judged by the model
  ----------------          -------------------
  evidence coverage         unsupported claims
  citation validity         gaps in reasoning
  data freshness            overconfidence
  agent agreement           contradictions between agents
  failure rate

The deterministic checks produce the base score. The model may apply a
BOUNDED penalty on top and may request one re-analysis. It cannot invent a
high score for weak work, and it cannot veto a well-evidenced analysis on a
whim.
"""

from enum import Enum

from pydantic import BaseModel, Field

from app.agents.contract import AgentResult, AgentStatus, ValidationReport
from app.core.logging import get_logger
from app.evidence.types import EvidenceBundle
from app.llm.provider import LlmProvider, parse_json_response

log = get_logger(__name__)

#: Most the model may deduct from the computed score.
MAX_MODEL_PENALTY = 25.0

#: Below this, the analysis is not fit to present.
REJECTION_THRESHOLD = 40.0

#: Below this (but above rejection) the reviewer may ask for one re-run.
REANALYSIS_THRESHOLD = 55.0


class Verdict(str, Enum):
    APPROVED = "APPROVED"
    REANALYZE = "REANALYZE"
    REJECTED = "REJECTED"


class ReviewerResult(BaseModel):
    verdict: Verdict
    score: float = Field(ge=0.0, le=100.0)
    computed_score: float = Field(description="Deterministic component before any penalty")
    model_penalty: float = Field(description="Bounded deduction applied by the model")
    confidence: float = Field(ge=0.0, le=1.0)

    evidence_coverage: float
    citation_validity: float
    agent_agreement: float
    data_freshness_ok: bool

    concerns: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    reasoning: str = ""
    model: str | None = None
    provider: str | None = None


def compute_deterministic_score(
    bundle: EvidenceBundle,
    results: list[AgentResult],
    validations: dict[str, ValidationReport],
) -> tuple[float, dict]:
    """The part of the score that does not involve a model at all.

    Four components, each 0-100, combined with declared weights.
    """
    completed = [r for r in results if r.status is AgentStatus.COMPLETED]
    attempted = [r for r in results if r.status is not AgentStatus.SKIPPED]

    # --- evidence coverage ---
    cited: set[str] = set()
    for result in completed:
        cited.update(result.all_evidence_ids())
    available = bundle.ids()
    coverage = len(cited & available) / len(available) if available else 0.0

    # --- citation validity ---
    total_claims = sum(len(r.observations) + len(r.interpretations) for r in completed)
    bad_citations = sum(
        len([i for i in report.issues if i.code in {"unknown_evidence_id", "unsupported_number"}])
        for report in validations.values()
    )
    validity = 1.0 if total_claims == 0 else max(0.0, 1.0 - bad_citations / total_claims)

    # --- completion rate ---
    completion = len(completed) / len(attempted) if attempted else 0.0

    # --- agent agreement ---
    # A crude but honest proxy: agents that cite overlapping evidence and
    # produce interpretations are corroborating each other. With fewer than
    # two completed agents there is nothing to compare, so we neither
    # reward nor punish it.
    if len(completed) < 2:
        agreement = 0.5
    else:
        overlaps = []
        for i, first in enumerate(completed):
            for second in completed[i + 1 :]:
                a, b = first.all_evidence_ids(), second.all_evidence_ids()
                if a and b:
                    overlaps.append(len(a & b) / len(a | b))
        agreement = sum(overlaps) / len(overlaps) if overlaps else 0.5

    components = {
        "evidence_coverage": round(coverage, 4),
        "citation_validity": round(validity, 4),
        "completion_rate": round(completion, 4),
        "agent_agreement": round(agreement, 4),
    }

    score = (
        coverage * 30.0
        + validity * 35.0
        + completion * 25.0
        + agreement * 10.0
    )

    # Stale data caps the score: an analysis of old numbers cannot be
    # excellent regardless of how well it is argued.
    if bundle.is_stale():
        score = min(score, 75.0)

    return round(score, 2), components


REVIEWER_SYSTEM_PROMPT = """
You are a critical reviewer of financial analysis. You did not produce the
analysis; your job is to find what is wrong with it.

You are given the evidence that was available and what each specialist
concluded. Look specifically for:

  - claims that the evidence does not support
  - reasoning that does not follow from the cited facts
  - overconfidence relative to the strength of the evidence
  - contradictions between specialists
  - important available evidence that was ignored

Be sceptical but fair. Do not invent problems. If the analysis is well
supported, say so.

You do NOT assign the overall score -- it is computed separately. You may
recommend a penalty from 0 to 25 points for genuine problems you identify.

Reply with ONE JSON object and nothing else:

{
  "penalty": 0-25,
  "confidence": 0.0-1.0,
  "concerns": ["specific problems found"],
  "strengths": ["what was done well"],
  "unsupported_claims": ["quote any claim the evidence does not support"],
  "reasoning": "two or three sentences explaining your assessment"
}
""".strip()


async def review(
    llm: LlmProvider,
    bundle: EvidenceBundle,
    results: list[AgentResult],
    validations: dict[str, ValidationReport],
) -> ReviewerResult:
    """Run the hybrid review."""
    computed, components = compute_deterministic_score(bundle, results, validations)

    completed = [r for r in results if r.status is AgentStatus.COMPLETED]
    summary_lines = []
    for result in completed:
        summary_lines.append(f"\n--- {result.agent} ---")
        for observation in result.observations:
            summary_lines.append(
                f"  OBSERVATION: {observation.text} [{', '.join(observation.evidence_ids)}]"
            )
        for interpretation in result.interpretations:
            summary_lines.append(
                f"  INTERPRETATION (confidence {interpretation.confidence}): "
                f"{interpretation.text} [{', '.join(interpretation.evidence_ids)}]"
            )

    user = (
        f"SUBJECT: {bundle.subject}\n\n"
        f"EVIDENCE THAT WAS AVAILABLE:\n{bundle.render_for_prompt()}\n\n"
        f"WHAT THE SPECIALISTS CONCLUDED:{''.join(summary_lines) or ' (nothing)'}\n\n"
        f"Review this analysis."
    )

    penalty = 0.0
    concerns: list[str] = []
    strengths: list[str] = []
    unsupported: list[str] = []
    reasoning = ""
    model_confidence = 0.5

    try:
        response = await llm.complete(REVIEWER_SYSTEM_PROMPT, user, json_mode=True)
        payload = parse_json_response(response.text)

        raw_penalty = float(payload.get("penalty", 0) or 0)
        penalty = max(0.0, min(MAX_MODEL_PENALTY, raw_penalty))
        model_confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.5) or 0.5)))
        concerns = [str(c) for c in payload.get("concerns", [])][:10]
        strengths = [str(s) for s in payload.get("strengths", [])][:10]
        unsupported = [str(u) for u in payload.get("unsupported_claims", [])][:10]
        reasoning = str(payload.get("reasoning", ""))
        model_name, provider_name = response.model, response.provider
    except Exception as exc:  # noqa: BLE001
        # A failed review must not fail the analysis. We keep the computed
        # score and say plainly that the qualitative half is missing.
        log.warning("reviewer_failed", error=str(exc))
        concerns = [f"Qualitative review unavailable: {exc}"]
        reasoning = "Score is from deterministic checks only; the model review did not run."
        model_name = provider_name = None

    final = max(0.0, computed - penalty)

    if final < REJECTION_THRESHOLD:
        verdict = Verdict.REJECTED
    elif final < REANALYSIS_THRESHOLD:
        verdict = Verdict.REANALYZE
    else:
        verdict = Verdict.APPROVED

    return ReviewerResult(
        verdict=verdict,
        score=round(final, 2),
        computed_score=computed,
        model_penalty=round(penalty, 2),
        # Calibrated: the model's stated confidence tempered by how much
        # evidence was actually used. High confidence on thin coverage is
        # not something we pass through unchanged.
        confidence=round(min(model_confidence, 0.5 + components["evidence_coverage"] / 2), 3),
        evidence_coverage=components["evidence_coverage"],
        citation_validity=components["citation_validity"],
        agent_agreement=components["agent_agreement"],
        data_freshness_ok=not bundle.is_stale(),
        concerns=concerns,
        strengths=strengths,
        unsupported_claims=unsupported,
        reasoning=reasoning,
        model=model_name,
        provider=provider_name,
    )


def build_summary(results: list[AgentResult], reviewer: ReviewerResult) -> str:
    """Assemble the final answer from what the agents actually said.

    Deliberately NOT another model call. The summary is a faithful
    assembly of validated agent output, so nothing can enter the final
    answer that did not survive validation.
    """
    completed = [r for r in results if r.status is AgentStatus.COMPLETED]
    if not completed:
        return "No agent produced a valid analysis. No conclusions can be offered."

    lines: list[str] = []
    for result in completed:
        title = result.agent.replace("_", " ").title()
        lines.append(f"**{title}**")
        for observation in result.observations[:4]:
            lines.append(f"- {observation.text}")
        for interpretation in result.interpretations[:3]:
            lines.append(f"- _{interpretation.text}_")
        lines.append("")

    if reviewer.concerns:
        lines.append("**Reviewer concerns**")
        lines.extend(f"- {c}" for c in reviewer.concerns[:4])

    return "\n".join(lines).strip()
