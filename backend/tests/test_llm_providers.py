"""Tests for the hosted providers and for how the failover chain is built.

Groq and Gemini share one OpenAI-compatible implementation, so each test of
the shared behaviour runs against both.
"""

import httpx
import pytest
import respx

from app.config import Settings
from app.core.errors import ProviderError, RateLimitError
from app.llm import provider as provider_module
from app.llm.fallback import FallbackLlmProvider
from app.llm.provider import GeminiProvider, GroqProvider
from app.llm.service import LlmService

OLLAMA = "http://ollama.test"
HOSTED = [GroqProvider, GeminiProvider]


def completion(text: str = '{"ok": true}', prompt: int = 11, output: int = 7) -> dict:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": output},
    }


@pytest.fixture
def no_wait(monkeypatch):
    """Record backoff waits instead of sleeping through them."""
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(provider_module.asyncio, "sleep", fake_sleep)
    return waits


def settings(**overrides) -> Settings:
    """Settings that ignore the real .env, which holds real keys."""
    base = {
        "groq_api_key": "",
        "gemini_api_key": "",
        "ollama_base_url": OLLAMA,
        "llm_preference": "online",
    }
    return Settings(_env_file=None, **{**base, **overrides})


def ollama_up(up: bool = True) -> None:
    route = respx.get(f"{OLLAMA}/api/tags")
    if up:
        route.mock(return_value=httpx.Response(200, json={"models": []}))
    else:
        route.mock(side_effect=httpx.ConnectError("refused"))


# ---------------------------------------------------------------------
# The shared OpenAI-compatible client
# ---------------------------------------------------------------------


@pytest.mark.parametrize("cls", HOSTED)
async def test_a_completion_is_returned_with_its_token_counts(cls):
    route = respx.post(f"{cls.BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json=completion())
    )
    response = await cls("secret-key", "some-model").complete("system", "user")

    assert response.text == '{"ok": true}'
    assert (response.input_tokens, response.output_tokens) == (11, 7)
    assert response.provider == cls.NAME
    assert route.calls.last.request.headers["authorization"] == "Bearer secret-key"


@pytest.mark.parametrize("cls", HOSTED)
async def test_json_mode_is_requested_at_temperature_zero(cls):
    route = respx.post(f"{cls.BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(200, json=completion())
    )
    await cls("k", "m").complete("s", "u")

    import json

    sent = json.loads(route.calls.last.request.content)
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["temperature"] == 0


@pytest.mark.parametrize("cls", HOSTED)
async def test_a_rate_limit_is_waited_out_then_retried(cls, no_wait):
    respx.post(f"{cls.BASE_URL}/chat/completions").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}),
            httpx.Response(200, json=completion()),
        ]
    )
    response = await cls("k", "m").complete("s", "u")

    assert response.text == '{"ok": true}'
    assert no_wait == [3.0], "the server's Retry-After hint should be honoured"


@pytest.mark.parametrize("cls", HOSTED)
async def test_a_rate_limit_that_never_clears_names_the_provider(cls, no_wait):
    respx.post(f"{cls.BASE_URL}/chat/completions").mock(return_value=httpx.Response(429))

    with pytest.raises(RateLimitError) as caught:
        await cls("k", "m").complete("s", "u")

    assert cls.LABEL in caught.value.message


@pytest.mark.parametrize("cls", HOSTED)
async def test_a_server_error_names_the_provider(cls):
    respx.post(f"{cls.BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(ProviderError) as caught:
        await cls("k", "m").complete("s", "u")

    assert caught.value.message == f"{cls.LABEL} returned HTTP 500."


@pytest.mark.parametrize("cls", HOSTED)
async def test_no_key_means_unavailable(cls):
    assert await cls("", "m").is_available() is False


# ---------------------------------------------------------------------
# A three-provider chain, built by nesting
# ---------------------------------------------------------------------


async def test_a_chain_of_three_reports_both_switches_in_order(no_wait):
    """Groq rate limited, then Gemini down: both switches must be visible."""
    respx.post(f"{GroqProvider.BASE_URL}/chat/completions").mock(return_value=httpx.Response(429))
    respx.post(f"{GeminiProvider.BASE_URL}/chat/completions").mock(
        return_value=httpx.Response(503, text="unavailable")
    )
    ollama_up()
    respx.post(f"{OLLAMA}/api/chat").mock(
        return_value=httpx.Response(
            200,
            json={"message": {"content": '{"ok": true}'}, "prompt_eval_count": 3, "eval_count": 2},
        )
    )

    chain = await LlmService(
        settings(groq_api_key="g", gemini_api_key="m", ollama_model="llama3.1:8b")
    ).get_provider()
    response = await chain.complete("s", "u")

    assert response.provider == "ollama"
    assert chain.model == "llama3.1:8b", "the stored model must be the one that answered"
    assert [(s.from_provider, s.to_provider) for s in chain.switches] == [
        ("groq", "gemini"),
        ("gemini", "ollama"),
    ]


# ---------------------------------------------------------------------
# Building the chain
# ---------------------------------------------------------------------


def names(provider) -> list[str]:
    """Flatten a nested chain into its provider names, in order."""
    if isinstance(provider, FallbackLlmProvider):
        return [provider._primary.name, *names(provider._fallback)]
    return [provider.name]


async def test_online_preference_orders_groq_then_gemini_then_local():
    ollama_up()
    chain = await LlmService(settings(groq_api_key="g", gemini_api_key="m")).get_provider()
    assert names(chain) == ["groq", "gemini", "ollama"]


async def test_local_preference_puts_ollama_first_and_keeps_both_online_as_fallback():
    ollama_up()
    chain = await LlmService(settings(groq_api_key="g", gemini_api_key="m")).get_provider("local")
    assert names(chain) == ["ollama", "groq", "gemini"]


async def test_a_stopped_ollama_is_left_out_of_the_chain():
    ollama_up(False)
    chain = await LlmService(settings(groq_api_key="g", gemini_api_key="m")).get_provider()
    assert names(chain) == ["groq", "gemini"]


async def test_gemini_alone_is_enough():
    ollama_up(False)
    chain = await LlmService(settings(gemini_api_key="m")).get_provider()
    assert names(chain) == ["gemini"]


async def test_nothing_available_fails_clearly():
    ollama_up(False)
    with pytest.raises(ProviderError) as caught:
        await LlmService(settings()).get_provider()
    assert "GEMINI_API_KEY" in caught.value.detail


async def test_status_keeps_the_shape_the_interface_reads():
    ollama_up()
    status = await LlmService(settings(groq_api_key="g", gemini_api_key="m")).describe_availability()

    assert status["online"]["provider"] == "groq"
    assert status["online_backup"]["provider"] == "gemini"
    assert status["online_backup"]["available"] is True
    assert status["local"]["available"] is True
    assert status["fallback_ready"] is True


async def test_status_without_keys_still_names_a_model():
    """The interface shows a model name even when nothing is configured."""
    ollama_up(False)
    status = await LlmService(settings()).describe_availability()

    assert status["online"] == {
        "provider": "groq", "model": settings().groq_model, "available": False
    }
    assert status["any_available"] is False
