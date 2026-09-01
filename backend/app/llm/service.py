"""Selects and manages the active LLM provider."""

from app.config import Settings, get_settings
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.llm.provider import GroqProvider, LlmProvider, OllamaProvider

log = get_logger(__name__)


class LlmService:
    """Chooses a provider and reports which options are available.

    Preference order is configurable. The default prefers the online
    provider when a key exists, because structured-output reliability is
    materially better and the prototype demo depends on it -- then falls
    back to the local model.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._active: LlmProvider | None = None

    def _build_online(self) -> LlmProvider | None:
        if not self._settings.groq_api_key:
            return None
        return GroqProvider(self._settings.groq_api_key, self._settings.groq_model)

    def _build_local(self) -> LlmProvider:
        return OllamaProvider(self._settings.ollama_base_url, self._settings.ollama_model)

    async def get_provider(self, prefer: str | None = None) -> LlmProvider:
        """Return a usable provider.

        `prefer` may be "local" or "online" to force a choice, which is what
        the model-comparison feature uses to run the same analysis both ways.
        """
        preference = prefer or self._settings.llm_preference

        if preference == "local":
            local = self._build_local()
            if await local.is_available():
                return local
            online = self._build_online()
            if online is not None:
                log.warning("local_llm_unavailable", falling_back_to="online")
                return online
            raise ProviderError(
                "Ollama is not running and no online provider is configured.",
                detail=(
                    "Start Ollama, or set GROQ_API_KEY in backend/.env. "
                    "See the README for setup."
                ),
            )

        online = self._build_online()
        if online is not None:
            return online

        local = self._build_local()
        if await local.is_available():
            log.info("no_online_key", using="ollama")
            return local

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
                "available": online is not None,
            },
            "any_available": local_up or online is not None,
        }


_service: LlmService | None = None


def get_llm_service() -> LlmService:
    global _service
    if _service is None:
        _service = LlmService()
    return _service
