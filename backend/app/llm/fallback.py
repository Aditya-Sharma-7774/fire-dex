"""Automatic failover between AI providers.

WHY THIS EXISTS
---------------
One analysis makes seven model calls in quick succession -- five
specialists, the reviewer, then the suggestion agent. We measured the free
tier rate-limiting the seventh: the specialists succeeded and only the last
agent failed. Retrying with backoff helps, but if the quota is genuinely
exhausted, waiting does not.

The local model is right there, costs nothing and has no quota. Losing an
analysis when a working alternative is available is a waste.

HOW IT BEHAVES
--------------
Tries the primary. On a rate limit or provider failure it switches to the
fallback and STAYS there for the rest of the analysis.

Sticky on purpose. If the quota is exhausted, every later call would hit the
same wall, and re-trying the primary seven times would add seven backoff
delays to an analysis that was already going to fall back anyway.

WHAT IT DOES NOT HIDE
---------------------
Every switch is recorded and surfaced. The interface shows which model
actually produced each agent's output, and the audit record stores it. An
analysis that silently changed models halfway through would make the stored
"model" field a lie, and this project's whole argument is that the record
can be trusted.

CONCURRENCY
-----------
Each provider enforces its own limit internally. This matters because the
limits differ sharply -- the hosted API handles five concurrent calls, while
Ollama serves essentially one at a time. Without a per-provider gate, a
mid-analysis switch would leave four already-running agents hammering a
local model that cannot take them, which is exactly the condition we
measured causing 120-second timeouts.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.errors import ProviderError, RateLimitError
from app.core.logging import get_logger
from app.llm.provider import LlmProvider, LlmResponse

log = get_logger(__name__)


@dataclass
class SwitchRecord:
    """One failover, kept so it can be reported rather than hidden."""

    at: datetime
    from_provider: str
    from_model: str
    to_provider: str
    to_model: str
    reason: str

    def as_dict(self) -> dict:
        return {
            "at": self.at.isoformat(),
            "from_provider": self.from_provider,
            "from_model": self.from_model,
            "to_provider": self.to_provider,
            "to_model": self.to_model,
            "reason": self.reason,
        }


class FallbackLlmProvider:
    """Wraps two providers and fails over from one to the other."""

    def __init__(self, primary: LlmProvider, fallback: LlmProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self._active: LlmProvider = primary
        self._switched = False

        #: Every switch that happened, for reporting.
        self.switches: list[SwitchRecord] = []

        # A gate per provider, sized to what that provider can actually
        # serve. The active gate is used for every call.
        self._gates = {
            id(primary): asyncio.Semaphore(getattr(primary, "max_concurrency", 3)),
            id(fallback): asyncio.Semaphore(getattr(fallback, "max_concurrency", 1)),
        }

    # --- LlmProvider protocol, reporting the ACTIVE provider -----------

    @property
    def name(self) -> str:
        return self._active.name

    @property
    def mode(self) -> str:
        return self._active.mode

    @property
    def model(self) -> str:
        return self._active.model

    @property
    def max_concurrency(self) -> int:
        return getattr(self._active, "max_concurrency", 1)

    @property
    def has_switched(self) -> bool:
        return self._switched

    async def is_available(self) -> bool:
        return await self._primary.is_available() or await self._fallback.is_available()

    # --- the failover itself -------------------------------------------

    async def complete(self, system: str, user: str, *, json_mode: bool = True) -> LlmResponse:
        # Already failed over: go straight to the fallback rather than
        # paying the primary's backoff again on every remaining call.
        if self._switched:
            async with self._gates[id(self._fallback)]:
                return await self._fallback.complete(system, user, json_mode=json_mode)

        try:
            async with self._gates[id(self._primary)]:
                return await self._primary.complete(system, user, json_mode=json_mode)
        except (RateLimitError, ProviderError) as exc:
            if not await self._fallback.is_available():
                # No usable alternative, so the original failure stands.
                # Substituting a vaguer error would hide the real cause.
                log.warning("no_fallback_available", error=str(exc))
                raise

            self._record_switch(exc)

            async with self._gates[id(self._fallback)]:
                return await self._fallback.complete(system, user, json_mode=json_mode)

    def _record_switch(self, exc: Exception) -> None:
        reason = (
            "rate limit reached"
            if isinstance(exc, RateLimitError)
            else f"provider failed: {exc}"
        )
        record = SwitchRecord(
            at=datetime.now(timezone.utc),
            from_provider=self._primary.name,
            from_model=self._primary.model,
            to_provider=self._fallback.name,
            to_model=self._fallback.model,
            reason=reason,
        )
        self.switches.append(record)
        self._switched = True
        self._active = self._fallback

        log.warning(
            "llm_failover",
            from_provider=record.from_provider,
            to_provider=record.to_provider,
            reason=reason,
        )

    def describe(self) -> dict:
        """Summary for the audit record and the interface."""
        return {
            "primary": {"provider": self._primary.name, "model": self._primary.model},
            "fallback": {"provider": self._fallback.name, "model": self._fallback.model},
            "active": {"provider": self._active.name, "model": self._active.model},
            "switched": self._switched,
            "switches": [s.as_dict() for s in self.switches],
        }
