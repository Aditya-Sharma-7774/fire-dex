"""The evidence contract.

THE CENTRAL IDEA OF THE PROJECT
------------------------------
Agents never fetch data, and agents never produce numbers.

Deterministic collectors gather facts into an EvidenceBundle. An agent
receives that bundle and may only emit observations and interpretations
that cite `evidence_id`s from it. A validator then checks every citation
exists and every number appearing in an observation matches an evidence
value.

That is what makes "the AI does not hallucinate figures" a property
enforced by code, rather than a request made politely in a prompt.

WHY TWO TIMESTAMPS
------------------
Every piece of evidence records both when the fact was true
(`data_timestamp`) and when we retrieved it (`fetched_at`). A price fetched
one second ago may describe a candle that closed an hour ago. Freshness
checks need both, and conflating them would let stale data pass as current.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EvidenceKind(str, Enum):
    """What sort of fact a piece of evidence is.

    Agents are given only the kinds relevant to their role, which keeps
    prompts focused and stops one agent reasoning about another's domain.
    """

    PRICE = "price"
    MARKET_STAT = "market_stat"
    INDICATOR = "indicator"
    TREND = "trend"
    CANDLE_SUMMARY = "candle_summary"
    BALANCE = "balance"
    PORTFOLIO_STAT = "portfolio_stat"
    CHAIN_STATE = "chain_state"
    RISK_FACTOR = "risk_factor"


class EvidenceSource(BaseModel):
    """Where a fact came from, precisely enough to be re-checked."""

    provider: str = Field(description="e.g. 'coingecko', 'binance', 'ethereum-rpc'")
    method: str = Field(description="Endpoint or computation, e.g. 'simple/price'")
    fetched_at: datetime = Field(description="When we retrieved it (UTC)")
    is_stale: bool = Field(default=False, description="Served from expired cache")


class Evidence(BaseModel):
    """One verifiable fact.

    `value` is deliberately typed loosely because evidence covers numbers,
    strings and small structures. What matters is that it came from a
    collector, carries a source, and can be cited.
    """

    evidence_id: str = Field(description="Stable within a bundle, e.g. 'ev_004'")
    kind: EvidenceKind
    label: str = Field(description="Human-readable name, e.g. 'RSI (14)'")
    value: Any
    unit: str | None = Field(default=None, description="e.g. 'USD', '%', 'ETH'")
    source: EvidenceSource
    data_timestamp: datetime | None = Field(
        default=None, description="When the fact was true, if known"
    )

    def as_prompt_line(self) -> str:
        """One line describing this fact, for inclusion in an agent prompt."""
        unit = f" {self.unit}" if self.unit else ""
        return f"[{self.evidence_id}] {self.label}: {self.value}{unit}"

    def numeric_value(self) -> float | None:
        """The value as a float, if it is numeric."""
        if isinstance(self.value, bool):
            return None
        if isinstance(self.value, (int, float)):
            return float(self.value)
        return None


class EvidenceBundle(BaseModel):
    """Everything known about one analysis request.

    This is the ONLY input an agent receives. If a fact is not in here, no
    agent can legitimately mention it.
    """

    subject: str = Field(description="What is being analysed, e.g. 'ETH'")
    chain: str | None = None
    address: str | None = None
    items: list[Evidence] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Collectors that failed. Recorded so the orchestrator can report
    # reduced coverage instead of silently analysing less than it claimed.
    failures: list[str] = Field(default_factory=list)

    def by_kind(self, *kinds: EvidenceKind) -> list[Evidence]:
        """Evidence of the given kinds, for building a focused prompt."""
        wanted = set(kinds)
        return [item for item in self.items if item.kind in wanted]

    def get(self, evidence_id: str) -> Evidence | None:
        return next((i for i in self.items if i.evidence_id == evidence_id), None)

    def ids(self) -> set[str]:
        return {item.evidence_id for item in self.items}

    def is_stale(self) -> bool:
        return any(item.source.is_stale for item in self.items)

    def oldest_data_timestamp(self) -> datetime | None:
        stamps = [i.data_timestamp for i in self.items if i.data_timestamp]
        return min(stamps) if stamps else None

    def render_for_prompt(self, *kinds: EvidenceKind) -> str:
        """The evidence block that goes into an agent prompt.

        Every line is prefixed with its evidence id, because the agent is
        required to cite those ids and cannot do so if it cannot see them.
        """
        items = self.by_kind(*kinds) if kinds else self.items
        if not items:
            return "(no evidence available)"
        return "\n".join(item.as_prompt_line() for item in items)


class EvidenceBuilder:
    """Assembles a bundle, allocating sequential ids.

    Using a builder rather than constructing Evidence by hand means ids are
    always unique within a bundle and always allocated the same way.
    """

    def __init__(self, subject: str, chain: str | None = None, address: str | None = None):
        self._bundle = EvidenceBundle(subject=subject, chain=chain, address=address)
        self._counter = 0

    def add(
        self,
        kind: EvidenceKind,
        label: str,
        value: Any,
        *,
        provider: str,
        method: str,
        unit: str | None = None,
        data_timestamp: datetime | None = None,
        fetched_at: datetime | None = None,
        is_stale: bool = False,
    ) -> Evidence | None:
        """Record one fact. Returns None if the value is None.

        A missing value is simply not recorded. Adding it as evidence with a
        null value would let an agent cite the absence of a fact as though
        it were one.
        """
        if value is None:
            return None

        self._counter += 1
        evidence = Evidence(
            evidence_id=f"ev_{self._counter:03d}",
            kind=kind,
            label=label,
            value=value,
            unit=unit,
            source=EvidenceSource(
                provider=provider,
                method=method,
                fetched_at=fetched_at or datetime.now(timezone.utc),
                is_stale=is_stale,
            ),
            data_timestamp=data_timestamp,
        )
        self._bundle.items.append(evidence)
        return evidence

    def record_failure(self, description: str) -> None:
        """Note that a collector failed, so coverage can be reported honestly."""
        self._bundle.failures.append(description)

    def build(self) -> EvidenceBundle:
        return self._bundle
