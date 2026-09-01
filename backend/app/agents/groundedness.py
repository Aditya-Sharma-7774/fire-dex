"""Groundedness: how well supported the analysis actually is.

Groundedness is a standard idea in retrieval-augmented generation
evaluation -- what fraction of a model's claims are actually entailed by the
context it was given. Ours is computed rather than judged, because the whole
point is to check the model, and asking a model to check itself is circular.

FOUR DIMENSIONS
---------------
  claim support     of every claim made, how many are fully traceable
                    (all cited ids exist AND every number matches)
  evidence use      of the evidence gathered, how much was actually cited
  anchoring         average number of distinct evidence items per claim --
                    a claim resting on three facts is better grounded than
                    one resting on a single number
  freshness         whether any cited evidence came from expired cache

WHY THIS IS NOT THE SAME AS THE REVIEWER SCORE
----------------------------------------------
The reviewer scores overall QUALITY -- coverage, completion, agreement, plus
a bounded model critique. Groundedness asks a narrower and harder question:
is what was said actually supported by what was known?

An analysis can be well-reviewed and poorly grounded (thorough, but leaning
on one thin fact), or poorly reviewed and well grounded (two agents failed,
but everything the third said is airtight). Keeping them separate is what
makes each one mean something.
"""

from dataclasses import dataclass, field

from app.agents.contract import AgentResult, AgentStatus, ValidationReport
from app.evidence.types import EvidenceBundle


@dataclass
class ClaimAudit:
    """One claim and whether the evidence actually supports it."""

    agent: str
    kind: str  # "observation" | "interpretation"
    text: str
    evidence_ids: list[str]
    supported: bool
    reason: str


@dataclass
class GroundednessReport:
    """How well the analysis is anchored to its evidence."""

    #: 0-1 composite.
    score: float
    claim_support: float
    evidence_use: float
    anchoring: float
    freshness_ok: bool

    total_claims: int
    supported_claims: int
    unsupported_claims: list[ClaimAudit] = field(default_factory=list)

    #: The evidence that did most of the work, most-cited first.
    top_evidence: list[tuple[str, str, int]] = field(default_factory=list)
    #: Evidence gathered but never used by any agent.
    unused_evidence: list[str] = field(default_factory=list)

    @property
    def band(self) -> str:
        """A word for the score, so the UI does not have to invent one."""
        if self.score >= 0.85:
            return "strong"
        if self.score >= 0.65:
            return "adequate"
        if self.score >= 0.40:
            return "weak"
        return "poor"


# Weights, published here so the composite can be argued with.
WEIGHTS = {
    "claim_support": 0.50,
    "evidence_use": 0.25,
    "anchoring": 0.25,
}

#: Citing this many distinct evidence items counts as fully anchored.
ANCHOR_TARGET = 3.0


def assess_groundedness(
    bundle: EvidenceBundle,
    results: list[AgentResult],
    validations: dict[str, ValidationReport],
) -> GroundednessReport:
    """Measure how well the analysis is supported by its evidence."""
    completed = [r for r in results if r.status is AgentStatus.COMPLETED]

    known_ids = bundle.ids()
    audits: list[ClaimAudit] = []
    citation_counts: dict[str, int] = {}

    for result in completed:
        report = validations.get(result.agent)
        # Issues are recorded against "observation[3]" style locations, so
        # we can attribute a failure to the specific claim that caused it.
        failed_locations = {
            issue.where for issue in (report.issues if report else []) if issue.where
        }

        for index, observation in enumerate(result.observations):
            location = f"observation[{index}]"
            unknown = [i for i in observation.evidence_ids if i not in known_ids]
            supported = not unknown and location not in failed_locations

            reason = "traceable to cited evidence"
            if unknown:
                reason = f"cites evidence that does not exist: {', '.join(unknown)}"
            elif location in failed_locations:
                reason = "states a value not present in the cited evidence"

            audits.append(
                ClaimAudit(
                    agent=result.agent,
                    kind="observation",
                    text=observation.text,
                    evidence_ids=observation.evidence_ids,
                    supported=supported,
                    reason=reason,
                )
            )
            for evidence_id in observation.evidence_ids:
                citation_counts[evidence_id] = citation_counts.get(evidence_id, 0) + 1

        for index, interpretation in enumerate(result.interpretations):
            location = f"interpretation[{index}]"
            unknown = [i for i in interpretation.evidence_ids if i not in known_ids]
            supported = not unknown and location not in failed_locations

            reason = "anchored to cited evidence"
            if unknown:
                reason = f"cites evidence that does not exist: {', '.join(unknown)}"
            elif location in failed_locations:
                reason = "not supported by the cited evidence"

            audits.append(
                ClaimAudit(
                    agent=result.agent,
                    kind="interpretation",
                    text=interpretation.text,
                    evidence_ids=interpretation.evidence_ids,
                    supported=supported,
                    reason=reason,
                )
            )
            for evidence_id in interpretation.evidence_ids:
                citation_counts[evidence_id] = citation_counts.get(evidence_id, 0) + 1

    total = len(audits)
    supported_count = sum(1 for a in audits if a.supported)

    # No claims at all is not perfect groundedness -- it is nothing to
    # ground. Reporting 1.0 here would be actively misleading.
    claim_support = supported_count / total if total else 0.0

    cited = set(citation_counts)
    evidence_use = len(cited & known_ids) / len(known_ids) if known_ids else 0.0

    distinct_per_claim = (
        sum(len(set(a.evidence_ids)) for a in audits) / total if total else 0.0
    )
    anchoring = min(distinct_per_claim / ANCHOR_TARGET, 1.0)

    score = (
        claim_support * WEIGHTS["claim_support"]
        + evidence_use * WEIGHTS["evidence_use"]
        + anchoring * WEIGHTS["anchoring"]
    )

    # Stale evidence caps groundedness. A claim perfectly supported by a
    # fifteen-minute-old price is not well grounded in the present.
    if bundle.is_stale():
        score = min(score, 0.75)

    top_evidence = []
    for evidence_id, count in sorted(citation_counts.items(), key=lambda kv: -kv[1])[:6]:
        evidence = bundle.get(evidence_id)
        if evidence is not None:
            label = f"{evidence.label}: {evidence.value}"
            if evidence.unit:
                label += f" {evidence.unit}"
            top_evidence.append((evidence_id, label, count))

    unused = []
    for item in bundle.items:
        if item.evidence_id not in cited:
            unused.append(f"{item.evidence_id} · {item.label}")

    return GroundednessReport(
        score=round(score, 4),
        claim_support=round(claim_support, 4),
        evidence_use=round(evidence_use, 4),
        anchoring=round(anchoring, 4),
        freshness_ok=not bundle.is_stale(),
        total_claims=total,
        supported_claims=supported_count,
        unsupported_claims=[a for a in audits if not a.supported][:10],
        top_evidence=top_evidence,
        unused_evidence=unused[:12],
    )
