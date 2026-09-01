"""Base class every agent inherits.

Each agent supplies three things:
  - a name
  - which kinds of evidence it should see
  - a system prompt describing its narrow role

Everything else -- calling the model, parsing JSON, validating the output,
retrying once on a validation failure, timing, token accounting -- happens
here, once. That means a new agent is a small, readable file, and a
teammate can write one without knowing how the orchestration works.

THE RETRY IS THE INTERESTING PART
---------------------------------
When validation fails, we do not discard the run and we do not accept the
output. We send the model its own violation and ask it to correct itself,
exactly once. If it fails again the agent is marked FAILED and the
orchestrator reports reduced coverage. We never repair the output ourselves,
because inventing a citation would defeat the entire purpose.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.agents.contract import (
    AgentResult,
    AgentStatus,
    Interpretation,
    Observation,
    ValidationReport,
    validate_agent_output,
)
from app.core.logging import get_logger
from app.evidence.types import EvidenceBundle, EvidenceKind
from app.llm.provider import LlmProvider, parse_json_response

log = get_logger(__name__)


# Applied to every agent. States the rules the validator will actually
# enforce, so the model is told the same thing the code checks.
SHARED_RULES = """
You are one specialist in a multi-agent financial analysis system.

ABSOLUTE RULES:
1. You may ONLY use the numbered evidence given to you. You have no other
   information and no ability to look anything up.
2. NEVER invent a number. Every figure you state must appear in the
   evidence, quoted accurately.
3. Separate what is measured from what it might mean:
     - "observations" restate facts from the evidence
     - "interpretations" say what those facts might indicate
4. Every observation and every interpretation MUST cite at least one
   evidence id, e.g. "ev_003".
5. Never give financial advice. Never say buy, sell or hold. You produce
   decision support, not recommendations.
6. If the evidence is insufficient, say so in a warning rather than
   guessing.
7. Be concise. At most 4 observations and 3 interpretations. Choose the
   most important ones. A long answer is not a better answer, and every
   extra sentence is another chance to state something unsupported.

Reply with ONE JSON object and nothing else:

{
  "observations": [
    {"text": "...", "evidence_ids": ["ev_001"]}
  ],
  "interpretations": [
    {"text": "...", "evidence_ids": ["ev_001"], "confidence": 0.0-1.0,
     "alternatives": ["a different reading of the same evidence"]}
  ],
  "warnings": ["anything limiting this analysis"]
}
""".strip()


class Agent(ABC):
    """One specialist analyst."""

    #: Name recorded in results and shown in the UI.
    name: str = "agent"

    #: Which evidence kinds this agent is shown. Keeping prompts narrow
    #: measurably improves reliability and stops agents straying.
    evidence_kinds: tuple[EvidenceKind, ...] = ()

    def __init__(self, llm: LlmProvider) -> None:
        self._llm = llm

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Describes this agent's specific role."""

    def build_user_prompt(self, bundle: EvidenceBundle) -> str:
        """The evidence block plus the question. Overridable if needed."""
        evidence = bundle.render_for_prompt(*self.evidence_kinds)
        return (
            f"SUBJECT: {bundle.subject}\n\n"
            f"EVIDENCE AVAILABLE TO YOU:\n{evidence}\n\n"
            f"Analyse the subject using only the evidence above."
        )

    def has_evidence(self, bundle: EvidenceBundle) -> bool:
        return bool(bundle.by_kind(*self.evidence_kinds))

    async def run(self, bundle: EvidenceBundle) -> tuple[AgentResult, ValidationReport]:
        """Execute this agent against an evidence bundle."""
        started = datetime.now(timezone.utc)

        if not self.has_evidence(bundle):
            # No relevant evidence: SKIPPED, not FAILED, and definitely not
            # an empty analysis presented as a real one.
            ended = datetime.now(timezone.utc)
            return (
                AgentResult(
                    agent=self.name,
                    status=AgentStatus.SKIPPED,
                    started_at=started,
                    ended_at=ended,
                    duration_ms=int((ended - started).total_seconds() * 1000),
                    warnings=["No relevant evidence was available for this agent."],
                ),
                ValidationReport(valid=True),
            )

        system = f"{self.system_prompt}\n\n{SHARED_RULES}"
        user = self.build_user_prompt(bundle)

        result, report = await self._attempt(bundle, system, user, started, attempt=1)

        if not report.valid:
            log.warning(
                "agent_output_invalid_retrying",
                agent=self.name,
                issues=report.summary()[:200],
            )
            # Feed the model its own violation. This is a genuine repair
            # attempt, not a blind retry.
            correction = (
                f"{user}\n\n"
                f"YOUR PREVIOUS REPLY WAS REJECTED for these reasons:\n"
                f"{report.summary()}\n\n"
                f"Correct them. Every number you state must appear in the evidence, "
                f"and every claim must cite a real evidence id."
            )
            result, report = await self._attempt(bundle, system, correction, started, attempt=2)

        if not report.valid:
            result.status = AgentStatus.FAILED
            result.errors.append(f"Output failed validation twice: {report.summary()}")
            log.warning("agent_failed_validation", agent=self.name)

        return result, report

    async def _attempt(
        self,
        bundle: EvidenceBundle,
        system: str,
        user: str,
        started: datetime,
        attempt: int,
    ) -> tuple[AgentResult, ValidationReport]:
        """One model call, parsed and validated."""
        try:
            response = await self._llm.complete(system, user, json_mode=True)
        except Exception as exc:  # noqa: BLE001 - provider failure must not crash the run
            ended = datetime.now(timezone.utc)
            return (
                AgentResult(
                    agent=self.name,
                    status=AgentStatus.FAILED,
                    started_at=started,
                    ended_at=ended,
                    duration_ms=int((ended - started).total_seconds() * 1000),
                    model=self._llm.model,
                    provider=self._llm.name,
                    mode=self._llm.mode,
                    errors=[f"Model call failed: {exc}"],
                ),
                ValidationReport(valid=True),
            )

        ended = datetime.now(timezone.utc)
        base = AgentResult(
            agent=self.name,
            status=AgentStatus.COMPLETED,
            started_at=started,
            ended_at=ended,
            duration_ms=int((ended - started).total_seconds() * 1000),
            model=response.model,
            provider=response.provider,
            mode=response.mode,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

        try:
            payload = parse_json_response(response.text)
        except ValueError as exc:
            base.status = AgentStatus.FAILED
            base.errors.append(f"Model did not return valid JSON (attempt {attempt}): {exc}")
            return base, ValidationReport(valid=True)

        try:
            base.observations = [
                Observation(**o) for o in payload.get("observations", []) if isinstance(o, dict)
            ]
            base.interpretations = [
                Interpretation(**i)
                for i in payload.get("interpretations", [])
                if isinstance(i, dict)
            ]
            warnings = payload.get("warnings", [])
            base.warnings = [str(w) for w in warnings] if isinstance(warnings, list) else []
        except Exception as exc:  # noqa: BLE001 - malformed shape from the model
            base.status = AgentStatus.FAILED
            base.errors.append(f"Model output did not match the required shape: {exc}")
            return base, ValidationReport(valid=True)

        if not base.observations and not base.interpretations:
            base.status = AgentStatus.FAILED
            base.errors.append("Model returned no observations or interpretations.")
            return base, ValidationReport(valid=True)

        report = validate_agent_output(base, bundle)
        return base, report
