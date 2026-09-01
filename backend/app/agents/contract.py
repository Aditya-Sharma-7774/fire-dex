"""What every agent must return, and the validator that enforces it.

An agent's output is not free text. It is a structured object in which every
claim is separated into:

  observation     a fact restated from evidence      "RSI is 49.4"
  interpretation  what that fact might mean          "momentum is neutral"

Both must cite evidence ids. The split is the point: a reader can always
tell which parts are measured and which are the model's opinion, and we
never produce the merged form -- "RSI is 49.4, so buy" -- which disguises an
opinion as a measurement and edges into financial advice.
"""

import re
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.evidence.types import EvidenceBundle


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Observation(BaseModel):
    """A fact restated from evidence."""

    text: str
    evidence_ids: list[str] = Field(min_length=1)


class Interpretation(BaseModel):
    """What the evidence might mean.

    `confidence` is the model's own stated confidence. It is recorded, but
    the reviewer scores calibration separately -- a model asserting 0.95 is
    not evidence that it is right.
    """

    text: str
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    alternatives: list[str] = Field(default_factory=list)


class AgentResult(BaseModel):
    """The complete output of one agent run."""

    agent: str
    status: AgentStatus
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = None

    model: str | None = None
    provider: str | None = None
    mode: str | None = Field(default=None, description="'local' or 'online'")
    input_tokens: int | None = None
    output_tokens: int | None = None

    observations: list[Observation] = Field(default_factory=list)
    interpretations: list[Interpretation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def total_tokens(self) -> int | None:
        if self.input_tokens is None and self.output_tokens is None:
            return None
        return (self.input_tokens or 0) + (self.output_tokens or 0)

    def all_evidence_ids(self) -> set[str]:
        ids: set[str] = set()
        for item in self.observations:
            ids.update(item.evidence_ids)
        for item in self.interpretations:
            ids.update(item.evidence_ids)
        return ids


class ValidationIssue(BaseModel):
    """One reason an agent's output was rejected."""

    code: str
    message: str
    where: str | None = None


class ValidationReport(BaseModel):
    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)

    def summary(self) -> str:
        return "; ".join(f"{i.code}: {i.message}" for i in self.issues)


# Matches numbers an agent might state: 1234, 12.5, 1,234.56, -3.2, 45%
_NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")


def validate_agent_output(
    result: AgentResult,
    bundle: EvidenceBundle,
    *,
    numeric_tolerance: float = 0.02,
) -> ValidationReport:
    """Check an agent obeyed the contract.

    Four checks, in increasing strictness:

      1. Every cited evidence id exists in the bundle.
      2. Every interpretation cites at least one id.
      3. Every observation cites at least one id.
      4. Every number in an observation matches a cited evidence value,
         within a small relative tolerance for rounding.

    Check 4 is the one that actually catches hallucinated figures. An agent
    that writes "RSI is 72" when the evidence says 49.4 fails here, even
    though it cited a real id.

    The tolerance exists because agents legitimately round -- writing "2462"
    for 2462.7 is fine. It is deliberately tight; anything looser would let
    a materially wrong number through.
    """
    issues: list[ValidationIssue] = []
    known_ids = bundle.ids()

    for index, observation in enumerate(result.observations):
        where = f"observation[{index}]"

        if not observation.evidence_ids:
            issues.append(
                ValidationIssue(
                    code="observation_without_citation",
                    message="Observation cites no evidence.",
                    where=where,
                )
            )
            continue

        unknown = [i for i in observation.evidence_ids if i not in known_ids]
        if unknown:
            issues.append(
                ValidationIssue(
                    code="unknown_evidence_id",
                    message=f"Cites evidence that does not exist: {', '.join(unknown)}",
                    where=where,
                )
            )
            continue

        issues.extend(_check_numbers(observation, bundle, where, numeric_tolerance))

    for index, interpretation in enumerate(result.interpretations):
        where = f"interpretation[{index}]"

        if not interpretation.evidence_ids:
            issues.append(
                ValidationIssue(
                    code="interpretation_without_citation",
                    message="Interpretation cites no evidence.",
                    where=where,
                )
            )
            continue

        unknown = [i for i in interpretation.evidence_ids if i not in known_ids]
        if unknown:
            issues.append(
                ValidationIssue(
                    code="unknown_evidence_id",
                    message=f"Cites evidence that does not exist: {', '.join(unknown)}",
                    where=where,
                )
            )

    return ValidationReport(valid=not issues, issues=issues)


def _check_numbers(
    observation: Observation,
    bundle: EvidenceBundle,
    where: str,
    tolerance: float,
) -> list[ValidationIssue]:
    """Every number stated must be traceable to cited evidence.

    "Traceable" covers two legitimate sources:

      the VALUE   "RSI (14) is 49.39"        -> 49.39 comes from the value
      the LABEL   "RSI (14) is 49.39"        -> 14 comes from the label

    The label case matters more than it sounds. Indicator names carry their
    period -- SMA (20), EMA (26), RSI (14) -- and statistics carry their
    window, like "24h price change". An agent quoting the name accurately is
    doing exactly what we asked, and an earlier version of this check
    rejected three of four agents for it. That was the validator being
    wrong, not the agents.
    """
    cited_values: list[float] = []
    for evidence_id in observation.evidence_ids:
        evidence = bundle.get(evidence_id)
        if evidence is None:
            continue

        numeric = evidence.numeric_value()
        if numeric is not None:
            cited_values.append(numeric)

        # Numbers embedded in the label are quotable too.
        for token in _NUMBER_PATTERN.findall(evidence.label):
            try:
                cited_values.append(float(token.replace(",", "")))
            except ValueError:
                continue

        # A non-numeric value may still contain figures worth quoting, e.g.
        # a formatted balance like "6.642178".
        if isinstance(evidence.value, str):
            for token in _NUMBER_PATTERN.findall(evidence.value):
                try:
                    cited_values.append(float(token.replace(",", "")))
                except ValueError:
                    continue

    # Nothing numeric was cited, so there is nothing to check against. A
    # textual observation citing a textual fact is legitimate.
    if not cited_values:
        return []

    issues: list[ValidationIssue] = []
    for match in _NUMBER_PATTERN.findall(observation.text):
        try:
            stated = float(match.replace(",", ""))
        except ValueError:
            continue

        # Small integers are almost always counts or list positions rather
        # than quoted measurements, and flagging them produces noise.
        if stated.is_integer() and abs(stated) <= 3:
            continue

        if not any(_close_enough(stated, value, tolerance) for value in cited_values):
            issues.append(
                ValidationIssue(
                    code="unsupported_number",
                    message=(
                        f"States {stated} but no cited evidence has that value "
                        f"(cited: {', '.join(str(round(v, 6)) for v in cited_values)})"
                    ),
                    where=where,
                )
            )

    return issues


def _close_enough(stated: float, actual: float, tolerance: float) -> bool:
    """Relative comparison, so it works for both 0.0000051 and 2462.7."""
    if actual == 0:
        return abs(stated) < 1e-9
    # Allow a rounded restatement, e.g. 2462 for 2462.7, or 49.4 for 49.3877.
    return abs(stated - actual) / abs(actual) <= tolerance


def failed_result(agent: str, error: str, started_at: datetime | None = None) -> AgentResult:
    """Build a FAILED result.

    Used wherever an agent cannot produce output. The orchestrator reports
    this as reduced coverage; it never substitutes invented content.
    """
    started = started_at or datetime.now(timezone.utc)
    ended = datetime.now(timezone.utc)
    return AgentResult(
        agent=agent,
        status=AgentStatus.FAILED,
        started_at=started,
        ended_at=ended,
        duration_ms=int((ended - started).total_seconds() * 1000),
        errors=[error],
    )
