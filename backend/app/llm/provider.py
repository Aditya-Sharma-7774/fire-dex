"""LLM provider abstraction.

The application must not be tied to one model vendor. Everything above this
layer asks for "a JSON object matching this schema, given this prompt", and
does not care whether that came from a local Ollama model or a hosted API.

Two implementations:

  OllamaProvider  local. Private, free, no internet needed. Structured
                  output is less reliable on smaller models -- we treat
                  that as a finding to measure, not a bug to hide.
  GroqProvider    online. Fast and reliable for structured output.

A NOTE ON REPRODUCIBILITY
-------------------------
We request temperature 0 for every analytical call. That makes sampling
greedy, but it is NOT fully deterministic: floating-point non-determinism
on GPUs, batching, and provider-side model updates all cause variation. We
therefore claim *evidential* reproducibility -- the same evidence produces
the same cited facts -- rather than bit-identical output, and we store the
model, provider and parameters with every result so a run can be re-attempted.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.errors import ProviderError, RateLimitError
from app.core.logging import get_logger

log = get_logger(__name__)

LLM_TIMEOUT_SECONDS = 180.0

#: How many times to wait out a 429 before giving up.
RATE_LIMIT_RETRIES = 2
#: Never wait longer than this for one retry, however long the server asks.
MAX_RATE_LIMIT_WAIT = 30.0


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Seconds the server asked us to wait, if it said."""
    header = response.headers.get("retry-after") or response.headers.get(
        "x-ratelimit-reset-tokens"
    )
    if not header:
        return None
    try:
        # Values arrive either as plain seconds or with a unit suffix.
        return float(str(header).rstrip("s"))
    except ValueError:
        return None


@dataclass
class LlmResponse:
    """One completion, with the accounting the auditor needs."""

    text: str
    model: str
    provider: str
    mode: str  # "local" or "online"
    input_tokens: int | None = None
    output_tokens: int | None = None


class LlmProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def mode(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def max_concurrency(self) -> int:
        """How many requests this provider can serve at once.

        This is not a detail. A local Ollama instance serves requests
        essentially one at a time; firing five agents at it simultaneously
        made every one of them time out at 120 seconds, even though a single
        warm request answers in under two. A hosted API has no such limit.
        """
        ...

    async def complete(self, system: str, user: str, *, json_mode: bool = True) -> LlmResponse: ...

    async def is_available(self) -> bool: ...


class OllamaProvider:
    """Local models through Ollama's HTTP API."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def mode(self) -> str:
        return "local"

    @property
    def model(self) -> str:
        return self._model

    @property
    def max_concurrency(self) -> int:
        # ONE. Measured, not guessed.
        #
        # Four concurrent agents: all four timed out at 120s.
        # Two concurrent agents: two of four still timed out at 180s.
        # One at a time: each agent completes in roughly 30-60s.
        #
        # Ollama loads a single copy of the model and serves largely
        # serially, so overlapping requests do not run in parallel -- they
        # queue while competing for memory, which is worse than not
        # overlapping them at all.
        return 1

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self._base_url}/api/tags")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def complete(self, system: str, user: str, *, json_mode: bool = True) -> LlmResponse:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0},
        }
        if json_mode:
            # Ollama constrains generation to valid JSON when asked.
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            # Distinct from a connection failure on purpose: "Ollama is not
            # running" and "Ollama is running but too slow" need completely
            # different fixes, and reporting both as "could not reach" sent
            # us looking in the wrong place during development.
            raise ProviderError(
                f"{self._model} did not respond within {LLM_TIMEOUT_SECONDS:.0f}s.",
                detail=(
                    "The local model is too slow for this prompt on this machine. "
                    "Try a smaller model, or set GROQ_API_KEY to use the online provider."
                ),
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "Could not reach Ollama.",
                detail=f"Is it running at {self._base_url}? ({exc})",
            ) from exc

        if response.status_code >= 400:
            raise ProviderError(
                f"Ollama returned HTTP {response.status_code}.", detail=response.text[:200]
            )

        body = response.json()
        return LlmResponse(
            text=body.get("message", {}).get("content", ""),
            model=self._model,
            provider=self.name,
            mode=self.mode,
            input_tokens=body.get("prompt_eval_count"),
            output_tokens=body.get("eval_count"),
        )


class GroqProvider:
    """Hosted models through Groq's OpenAI-compatible chat completions API."""

    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    @property
    def name(self) -> str:
        return "groq"

    @property
    def mode(self) -> str:
        return "online"

    @property
    def model(self) -> str:
        return self._model

    @property
    def max_concurrency(self) -> int:
        return 5

    async def is_available(self) -> bool:
        return bool(self._api_key)

    async def complete(self, system: str, user: str, *, json_mode: bool = True) -> LlmResponse:
        payload: dict = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        # One analysis makes seven calls in quick succession -- five
        # specialists, the reviewer, then the suggestion agent -- which is
        # enough to trip a per-minute rate limit on a free tier. We measured
        # exactly that: the specialists succeeded and the seventh call got a
        # 429. Rate limits are a normal operating condition for this
        # workload, not an error, so we wait and retry rather than
        # discarding work that has already been paid for.
        response = None
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
                    response = await client.post(
                        f"{self.BASE_URL}/chat/completions",
                        json=payload,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                    )
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"{self._model} did not respond within {LLM_TIMEOUT_SECONDS:.0f}s.",
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError("Could not reach Groq.", detail=str(exc)) from exc

            if response.status_code != 429:
                break

            if attempt == RATE_LIMIT_RETRIES:
                raise RateLimitError(
                    "Groq rate limit reached and did not clear.",
                    detail=(
                        "The free tier allows a limited number of tokens per minute. "
                        "Wait a moment, or switch to the local model."
                    ),
                )

            # Honour the server's own hint when it gives one; it knows
            # better than a fixed backoff would.
            wait = _retry_after_seconds(response) or (2.0 * (attempt + 1))
            log.warning(
                "groq_rate_limited_retrying",
                attempt=attempt + 1,
                waiting_seconds=round(wait, 1),
            )
            await asyncio.sleep(min(wait, MAX_RATE_LIMIT_WAIT))

        assert response is not None
        if response.status_code >= 400:
            raise ProviderError(
                f"Groq returned HTTP {response.status_code}.", detail=response.text[:300]
            )

        body = response.json()
        usage = body.get("usage", {})
        return LlmResponse(
            text=body["choices"][0]["message"]["content"],
            model=self._model,
            provider=self.name,
            mode=self.mode,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )


def parse_json_response(text: str) -> dict:
    """Extract a JSON object from a model response.

    Models sometimes wrap JSON in prose or a markdown fence despite being
    asked not to. We strip the common wrappers before giving up, because
    failing on a recoverable formatting quirk wastes a whole agent run.

    Raises ValueError if no JSON object can be recovered -- which the agent
    turns into one repair retry, then a clean failure. We never guess at
    what the model meant.
    """
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # Fall back to the outermost braces.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No JSON object found in model response: {text[:200]}")
