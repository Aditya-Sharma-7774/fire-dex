"""Selects and manages the active LLM provider."""

from app.config import Settings, get_settings
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.llm.fallback import FallbackLlmProvider
from app.llm.provider import GroqProvider, LlmProvider, OllamaProvider

log = get_logger(__name__)


class LlmService:
    """Chooses providers and wires up automatic failover.

    When both an online and a local provider are usable, the caller does not
    get one of them -- it gets a wrapper that starts on the preferred one
    and fails over automatically. That is deliberate: an analysis is seven
    model calls, and losing it to a rate limit when a working local model is
    sitting idle is pure waste.

    `prefer` only decides which provider is tried FIRST. The other remains
    the fallback either way, so choosing "local" still survives Ollama being
    stopped mid-run.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _build_online(self) -> LlmProvider | None:
        if not self._settings.groq_api_key:
            return None
        return GroqProvider(self._settings.groq_api_key, self._settings.groq_model)

    def _build_local(self) -> LlmProvider:
        return OllamaProvider(self._settings.ollama_base_url, self._settings.ollama_model)

    async def get_provider(self, prefer: str | None = None) -> LlmProvider:
        """Return a usable provider, with failover when both are available.

        `prefer` may be "local" or "online" to force which is tried first,
        which is what the model-comparison feature uses to run the same
        analysis both ways.
        """
        preference = prefer or self._settings.llm_preference

        local = self._build_local()
        online = self._build_online()

        local_up = await local.is_available()
        online_up = online is not None

        if preference == "local":
            primary, secondary = local, online
            primary_up, secondary_up = local_up, online_up
        else:
            primary, secondary = online, local
            primary_up, secondary_up = online_up, local_up

        # Both usable: hand back a wrapper that fails over automatically.
        if primary_up and secondary_up and primary is not None and secondary is not None:
            log.info(
                "llm_with_fallback",
                primary=primary.name,
                fallback=secondary.name,
            )
            return FallbackLlmProvider(primary, secondary)

        if primary_up and primary is not None:
            return primary

        if secondary_up and secondary is not None:
            log.warning(
                "preferred_provider_unavailable",
                preferred=preference,
                using=secondary.name,
            )
            return secondary

        raise ProviderError(
            "No AI provider is available.",
            detail=(
                "Set GROQ_API_KEY in backend/.env for an online model, or run "
                "Ollama locally with the model named by OLLAMA_MODEL."
            ),
        )

    async def describe_availability(self) -> dict:
        """What the UI shows in its AI status indicator."""
        local = self._build_local()
        online = self._build_online()

        local_up = await local.is_available()
        online_up = online is not None

        return {
            "preference": self._settings.llm_preference,
            "local": {
                "provider": "ollama",
                "model": self._settings.ollama_model,
                "available": local_up,
                "base_url": self._settings.ollama_base_url,
            },
            "online": {
                "provider": "groq",
                "model": self._settings.groq_model,
                "available": online_up,
            },
            "any_available": local_up or online_up,
            # True when a failure on one can be absorbed by the other.
            "fallback_ready": local_up and online_up,
        }


_service: LlmService | None = None


def get_llm_service() -> LlmService:
    global _service
    if _service is None:
        _service = LlmService()
    return _service
