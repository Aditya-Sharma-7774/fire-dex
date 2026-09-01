"""The Suggestion Agent.

Runs last, after every specialist and after the reviewer. Unlike them it is
not analysing the market -- it is analysing THE ANALYSIS, and answering the
three questions a user actually has when they look at a result:

    1. On what basis did the agents conclude that?
    2. Why did the reviewer give it that rating?
    3. So what does this add up to, and how much should I trust it?

WHAT IT DOES AND DOES NOT DECIDE
--------------------------------
The directional signal (Buy / Sell / Neutral) is NOT chosen here. It is
computed by `app/signals/engine.py` from a deterministic vote across
indicators with published thresholds. Groundedness is likewise computed.

This agent EXPLAINS both in plain language, and must cite evidence like any
other agent -- its output goes through the same validator.

That division matters. If a model chose the signal, "why does it say Buy?"
would have no answer beyond "it decided to". Because the vote decides, the
answer is a list of indicators and the rule each one triggered.

ON GIVING A BUY/SELL SIGNAL AT ALL
-----------------------------------
The signal summarises what conventional technical indicators currently
AGREE ON. That is a statement about indicator readings, not a prediction
about price, and not a recommendation to act. Every surface that shows it
also shows the disclaimer, and the wording throughout is "signal", never
"advice" or "recommendation".
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.agents.contract import AgentResult, AgentStatus
from app.agents.groundedness import GroundednessReport
from app.agents.reviewer import ReviewerResult
from app.core.logging import get_logger
from app.evidence.types import EvidenceBundle
from app.llm.provider import LlmProvider, parse_json_response
from app.signals.engine import SignalResult, describe_signal

log = get_logger(__name__)

DISCLAIMER = (
    "This is an indicator-agreement signal, not financial advice. It "
    "summarises what conventional technical indicators currently agree on. "
    "It is not a prediction of future price and must not be treated as a "
    "recommendation to buy or sell."
)


class SuggestionResult(BaseModel):
    """The Suggestion Agent's output."""

    # --- computed, not model-chosen ---
    signal: str | None = Field(default=None, description="STRONG_BUY … STRONG_SELL")
    signal_score: float | None = Field(default=None, description="-1 (sell) .. +1 (buy)")
    signal_basis: list[str] = Field(
        default_factory=list, description="Each indicator vote and the rule it triggered"
    )
    buy_votes: int = 0
    sell_votes: int = 0
    neutral_votes: int = 0

    groundedness: float = Field(default=0.0, description="0-1, computed")
    groundedness_band: str = "poor"
    claim_support: float = 0.0
    evidence_use: float = 0.0
    anchoring: float = 0.0

    # --- explained by the model, citing evidence ---
    basis_summary: str = Field(default="", description="Why the agents concluded what they did")
    reviewer_explanation: str = Field(default="", description="Why the reviewer scored it so")
    trust_summary: str = Field(default="", description="How much weight this deserves")
    key_drivers: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)

    # --- always present ---
    disclaimer: str = DISCLAIMER
    model: str | None = None
    provider: str | None = None
    duration_ms: int | None = None


SUGGESTION_SYSTEM_PROMPT = """
You explain a completed financial analysis to the person who requested it.
You are not analysing the market -- other specialists already did that. You
are explaining THEIR work and a signal that has ALREADY BEEN CALCULATED.

You will be given:
  - the evidence that was collected
  - what each specialist observed and interpreted
  - a directional signal computed by a deterministic indicator vote
  - the reviewer's score and how it was arrived at
  - a computed groundedness measure

Answer three questions, in plain language a non-expert can follow:

1. BASIS -- on what basis did the specialists reach their conclusions?
   Name the specific evidence that did the work. Be concrete: say which
   indicator or figure drove which conclusion.

2. REVIEWER -- why did the reviewer give that particular score? Explain the
   components in plain words: how much of the evidence was used, whether
   claims were properly cited, how many agents completed, whether they
   agreed.

3. TRUST -- how much weight does this deserve? Be honest about weaknesses.
   If coverage was low, or one agent failed, or the signal is weakly
   supported, say so plainly.

RULES:
- You did NOT choose the signal. Never claim you did. Explain what drove it.
- Never say "you should buy" or "you should sell". Describe what the
  indicators agree on, not what the reader ought to do.
- Every claim must cite evidence ids, exactly like the other agents.
- Never state a number that is not in the evidence.
- If the analysis is weak, say so. A confident explanation of weak work is
  worse than an honest one.

Reply with ONE JSON object and nothing else:

{
  "basis_summary": "2-4 sentences on what the specialists based their conclusions on",
  "reviewer_explanation": "2-3 sentences on why the reviewer scored it that way",
  "trust_summary": "2-3 sentences on how much weight this deserves and why",
  "key_drivers": ["the specific facts that mattered most, each citing an evidence id"],
  "caveats": ["genuine limitations of this analysis"],
  "observations": [{"text": "...", "evidence_ids": ["ev_001"]}],
  "interpretations": [{"text": "...", "evidence_ids": ["ev_001"], "confidence": 0.0-1.0}]
}
""".strip()


def _render_reviewer(reviewer: ReviewerResult) -> str:
    return (
        f"verdict {reviewer.verdict.value}, final score {reviewer.score:.1f}/100\n"
        f"  computed component: {reviewer.computed_score:.1f}\n"
        f"  model penalty applied: -{reviewer.model_penalty:.1f} (capped at 25)\n"
        f"  evidence coverage: {reviewer.evidence_coverage:.0%}\n"
        f"  citation validity: {reviewer.citation_validity:.0%}\n"
        f"  agent agreement: {reviewer.agent_agreement:.0%}\n"
        f"  data freshness ok: {reviewer.data_freshness_ok}\n"
        f"  reviewer reasoning: {reviewer.reasoning or '(none)'}"
    )


def _render_agents(results: list[AgentResult]) -> str:
    lines: list[str] = []
    for result in results:
        if result.status is not AgentStatus.COMPLETED:
            lines.append(f"\n{result.agent}: {result.status.value.upper()}")
            continue
        lines.append(f"\n{result.agent}:")
        for observation in result.observations:
            lines.append(f"  observed: {observation.text} [{', '.join(observation.evidence_ids)}]")
        for interpretation in result.interpretations:
            lines.append(
                f"  interpreted: {interpretation.text} "
                f"[{', '.join(interpretation.evidence_ids)}] "
                f"confidence {interpretation.confidence}"
            )
    return "\n".join(lines) or "(no completed agents)"


async def suggest(
    llm: LlmProvider,
    bundle: EvidenceBundle,
    results: list[AgentResult],
    reviewer: ReviewerResult,
    grounded: GroundednessReport,
    signal: SignalResult | None,
) -> SuggestionResult:
    """Explain the analysis, the reviewer's rating and the computed signal."""
    started = datetime.now(timezone.utc)

    out = SuggestionResult(
        signal=signal.signal.value if signal else None,
        signal_score=signal.score if signal else None,
        signal_basis=[f"{v.indicator}: {v.direction.value.upper()} — {v.rule}" for v in signal.votes]
        if signal
        else [],
        buy_votes=signal.buy_votes if signal else 0,
        sell_votes=signal.sell_votes if signal else 0,
        neutral_votes=signal.neutral_votes if signal else 0,
        groundedness=grounded.score,
        groundedness_band=grounded.band,
        claim_support=grounded.claim_support,
        evidence_use=grounded.evidence_use,
        anchoring=grounded.anchoring,
    )

    signal_block = (
        f"SIGNAL (already computed by deterministic indicator vote — you did not choose it):\n"
        f"  {describe_signal(signal)}\n"
        f"  score {signal.score:+.2f} on a -1 (sell) to +1 (buy) scale\n"
        + "\n".join(f"  · {b}" for b in out.signal_basis)
        if signal
        else "SIGNAL: could not be computed — not enough indicator data."
    )

    grounded_block = (
        f"GROUNDEDNESS (computed): {grounded.score:.2f} ({grounded.band})\n"
        f"  claims fully supported: {grounded.supported_claims}/{grounded.total_claims}\n"
        f"  evidence actually used: {grounded.evidence_use:.0%}\n"
        f"  average distinct evidence per claim: {grounded.anchoring * 3:.1f}"
    )

    user = (
        f"SUBJECT: {bundle.subject}\n\n"
        f"EVIDENCE COLLECTED:\n{bundle.render_for_prompt()}\n\n"
        f"WHAT THE SPECIALISTS CONCLUDED:{_render_agents(results)}\n\n"
        f"REVIEWER:\n{_render_reviewer(reviewer)}\n\n"
        f"{signal_block}\n\n"
        f"{grounded_block}\n\n"
        f"Explain the basis, the reviewer's rating, and how much this deserves to be trusted."
    )

    try:
        response = await llm.complete(SUGGESTION_SYSTEM_PROMPT, user, json_mode=True)
        payload = parse_json_response(response.text)

        out.basis_summary = str(payload.get("basis_summary", ""))[:1200]
        out.reviewer_explanation = str(payload.get("reviewer_explanation", ""))[:1200]
        out.trust_summary = str(payload.get("trust_summary", ""))[:1200]
        out.key_drivers = [str(d) for d in payload.get("key_drivers", [])][:6]
        out.caveats = [str(c) for c in payload.get("caveats", [])][:6]
        out.model = response.model
        out.provider = response.provider
    except Exception as exc:  # noqa: BLE001
        # The signal and groundedness are already computed, so a failed
        # explanation degrades the output rather than destroying it. We say
        # the explanation is missing instead of inventing one.
        log.warning("suggestion_agent_failed", error=str(exc))
        out.caveats = [f"Plain-language explanation unavailable: {exc}"]
        out.basis_summary = (
            "The explanation step did not run. The signal and groundedness figures "
            "above are still valid — they are computed, not model-generated."
        )

    ended = datetime.now(timezone.utc)
    out.duration_ms = int((ended - started).total_seconds() * 1000)
    return out
