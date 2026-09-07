"""Tests for automatic failover between AI providers.

The failover must do two things equally well: keep the analysis alive, and
never hide that it happened. A switch that is not recorded would make the
stored `model` field wrong, and this project's argument rests on the record
being trustworthy.
"""

import asyncio

import pytest

from app.core.errors import ProviderError, RateLimitError
from app.llm.fallback import FallbackLlmProvider
from app.llm.provider import LlmResponse


class _StubProvider:
    """A provider that can be told how to fail."""

    def __init__(
        self,
        name: str,
        mode: str,
        model: str,
        *,
        fail_with: Exception | None = None,
        available: bool = True,
        concurrency: int = 3,
    ) -> None:
        self._name = name
        self._mode = mode
        self._model = model
        self._fail_with = fail_with
        self._available = available
        self.max_concurrency = concurrency
        self.calls = 0
        self.concurrent_peak = 0
        self._in_flight = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def model(self) -> str:
        return self._model

    async def is_available(self) -> bool:
        return self._available

    async def complete(self, system: str, user: str, *, json_mode: bool = True) -> LlmResponse:
        self.calls += 1
        self._in_flight += 1
        self.concurrent_peak = max(self.concurrent_peak, self._in_flight)
        try:
            await asyncio.sleep(0.01)
            if self._fail_with is not None:
                raise self._fail_with
            return LlmResponse(
                text='{"ok": true}',
                model=self._model,
                provider=self._name,
                mode=self._mode,
                input_tokens=10,
                output_tokens=5,
            )
        finally:
            self._in_flight -= 1


def _online(concurrency: int = 5, **kwargs) -> _StubProvider:
    return _StubProvider("groq", "online", "gpt-oss-120b", concurrency=concurrency, **kwargs)


def _local(concurrency: int = 1, **kwargs) -> _StubProvider:
    return _StubProvider("ollama", "local", "llama3.1:8b", concurrency=concurrency, **kwargs)


# ---------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------


async def test_primary_is_used_when_healthy() -> None:
    primary, fallback = _online(), _local()
    provider = FallbackLlmProvider(primary, fallback)

    response = await provider.complete("s", "u")

    assert response.provider == "groq"
    assert fallback.calls == 0
    assert provider.has_switched is False


# ---------------------------------------------------------------------
# Failover
# ---------------------------------------------------------------------


async def test_rate_limit_triggers_failover_to_local() -> None:
    """The case we actually measured: the free tier refusing the 7th call."""
    primary = _online(fail_with=RateLimitError("quota exhausted"))
    fallback = _local()
    provider = FallbackLlmProvider(primary, fallback)

    response = await provider.complete("s", "u")

    assert response.provider == "ollama"
    assert response.mode == "local"
    assert provider.has_switched is True


async def test_provider_error_also_triggers_failover() -> None:
    primary = _online(fail_with=ProviderError("connection reset"))
    provider = FallbackLlmProvider(primary, _local())

    response = await provider.complete("s", "u")

    assert response.provider == "ollama"


async def test_failover_is_sticky() -> None:
    """Once switched, later calls must not retry the exhausted provider.

    Retrying it on every remaining call would add a backoff delay to each
    one, for an analysis that was going to fall back anyway.
    """
    primary = _online(fail_with=RateLimitError("quota"))
    fallback = _local()
    provider = FallbackLlmProvider(primary, fallback)

    for _ in range(4):
        await provider.complete("s", "u")

    assert primary.calls == 1  # tried once, never again
    assert fallback.calls == 4


async def test_failover_works_in_the_other_direction() -> None:
    """Choosing local must still survive Ollama being stopped mid-run."""
    primary = _local(fail_with=ProviderError("Ollama is not running"))
    provider = FallbackLlmProvider(primary, _online())

    response = await provider.complete("s", "u")

    assert response.provider == "groq"


# ---------------------------------------------------------------------
# The switch must never be hidden
# ---------------------------------------------------------------------


async def test_the_switch_is_recorded() -> None:
    provider = FallbackLlmProvider(_online(fail_with=RateLimitError("quota")), _local())

    await provider.complete("s", "u")

    assert len(provider.switches) == 1
    record = provider.switches[0]
    assert record.from_provider == "groq"
    assert record.to_provider == "ollama"
    assert "rate limit" in record.reason


async def test_active_model_reflects_the_provider_actually_in_use() -> None:
    """Otherwise the stored `model` field would be a lie."""
    provider = FallbackLlmProvider(_online(fail_with=RateLimitError("quota")), _local())

    assert provider.model == "gpt-oss-120b"
    assert provider.mode == "online"

    await provider.complete("s", "u")

    assert provider.model == "llama3.1:8b"
    assert provider.mode == "local"


async def test_describe_reports_both_providers_and_the_switch() -> None:
    provider = FallbackLlmProvider(_online(fail_with=RateLimitError("quota")), _local())
    await provider.complete("s", "u")

    described = provider.describe()

    assert described["switched"] is True
    assert described["primary"]["provider"] == "groq"
    assert described["fallback"]["provider"] == "ollama"
    assert described["active"]["provider"] == "ollama"
    assert len(described["switches"]) == 1


# ---------------------------------------------------------------------
# Concurrency must follow the active provider
# ---------------------------------------------------------------------


async def test_local_calls_are_serialised_after_failover() -> None:
    """The critical one.

    Ollama serves essentially one request at a time. If four agents are
    already in flight when the switch happens, they must not all pile onto
    the local model -- that is precisely the condition we measured causing
    every call to time out at 120 seconds.
    """
    primary = _online(fail_with=RateLimitError("quota"))
    fallback = _local(concurrency=1)
    provider = FallbackLlmProvider(primary, fallback)

    await asyncio.gather(*(provider.complete("s", "u") for _ in range(5)))

    assert fallback.calls == 5
    assert fallback.concurrent_peak == 1, (
        f"local provider saw {fallback.concurrent_peak} concurrent calls; "
        "it must be gated to 1"
    )


async def test_primary_concurrency_is_respected_before_any_switch() -> None:
    primary = _online(concurrency=2)
    provider = FallbackLlmProvider(primary, _local())

    await asyncio.gather(*(provider.complete("s", "u") for _ in range(6)))

    assert primary.concurrent_peak <= 2


async def test_max_concurrency_follows_the_active_provider() -> None:
    provider = FallbackLlmProvider(_online(fail_with=RateLimitError("q")), _local())

    assert provider.max_concurrency == 5
    await provider.complete("s", "u")
    assert provider.max_concurrency == 1


# ---------------------------------------------------------------------
# When there is nothing to fall back to
# ---------------------------------------------------------------------


async def test_original_error_is_raised_when_fallback_is_unavailable() -> None:
    """Substituting a vaguer error would hide the real cause."""
    primary = _online(fail_with=RateLimitError("quota exhausted"))
    fallback = _local(available=False)
    provider = FallbackLlmProvider(primary, fallback)

    with pytest.raises(RateLimitError, match="quota exhausted"):
        await provider.complete("s", "u")

    assert fallback.calls == 0
    assert provider.has_switched is False


async def test_a_failure_on_the_fallback_is_not_swallowed() -> None:
    """Both down means the analysis fails, honestly."""
    provider = FallbackLlmProvider(
        _online(fail_with=RateLimitError("quota")),
        _local(fail_with=ProviderError("Ollama is not running")),
    )

    with pytest.raises(ProviderError, match="Ollama is not running"):
        await provider.complete("s", "u")
