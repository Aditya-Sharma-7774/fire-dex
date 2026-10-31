"""Selects and manages the active LLM provider."""

from app.config import Settings, get_settings
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.llm.fallback import FallbackLlmProvider
from app.llm.provider import GeminiProvider, GroqProvider, LlmProvider, OllamaProvider

log = get_logger(__name__)


class LlmService:
    """Chooses providers and wires up automatic failover.

    Every usable provider is placed in one chain, tried in order, and the
    caller gets a wrapper that moves down the chain on a rate limit or
    failure. An analysis is seven model calls, and losing it to a quota when
    another working provider is idle is pure waste.

    `prefer` only decides what is tried FIRST:

        online   Groq -> Gemini -> Ollama
        local    Ollama -> Groq -> Gemini

    Either way every other provider remains a fallback, so choosing "local"
    still survives Ollama being stopped mid-run.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _build_online(self) -> list[LlmProvider]:
        """Hosted providers with a key configured, in preference order."""
        providers: list[LlmProvider] = []
        if self._settings.groq_api_key:
            providers.append(GroqProvider(self._settings.groq_api_key, self._settings.groq_model))
        if self._settings.gemini_api_key:
            providers.append(
                GeminiProvider(self._settings.gemini_api_key, self._settings.gemini_model)
            )
        return providers

    def _build_local(self) -> LlmProvider:
        return OllamaProvider(self._settings.ollama_base_url, self._settings.ollama_model)

    async def get_provider(self, prefer: str | None = None) -> LlmProvider:
        """A provider that fails over through every usable alternative."""
        preference = prefer or self._settings.llm_preference

        local = self._build_local()
        online = self._build_online()
        local_up = await local.is_available()

        ordered = [local, *online] if preference == "local" else [*online, local]
        usable = [p for p in ordered if p is not local or local_up]

        if not usable:
            raise ProviderError(
                "No AI provider is available.",
                detail=(
                    "Set GROQ_API_KEY or GEMINI_API_KEY in backend/.env for an online "
                    "model, or run Ollama locally with the model named by OLLAMA_MODEL."
                ),
            )

        if usable[0] is not ordered[0]:
            log.warning("preferred_provider_unavailable", preferred=preference, using=usable[0].name)

        log.info("llm_chain", providers=[p.name for p in usable])
        return _chain(usable)

    async def describe_availability(self) -> dict:
        """What the UI shows in its AI status indicator."""
        local = self._build_local()
        online = self._build_online()
        local_up = await local.is_available()

        def entry(provider: LlmProvider | None, name: str, model: str) -> dict:
            # An unconfigured provider is still described, as unavailable, so
            # the interface always has a model name to show.
            if provider is None:
                return {"provider": name, "model": model, "available": False}
            return {"provider": provider.name, "model": provider.model, "available": True}

        groq = next((p for p in online if p.name == "groq"), None)
        gemini = next((p for p in online if p.name == "gemini"), None)
        usable_count = len(online) + (1 if local_up else 0)

        return {
            "preference": self._settings.llm_preference,
            "local": {
                "provider": "ollama",
                "model": self._settings.ollama_model,
                "available": local_up,
                "base_url": self._settings.ollama_base_url,
            },
            # Gemini stands in as the primary online provider when Groq has no key.
            "online": entry(groq or gemini, "groq", self._settings.groq_model),
            "online_backup": entry(
                gemini if groq else None, "gemini", self._settings.gemini_model
            ),
            "any_available": usable_count > 0,
            # True when a failure on one provider can be absorbed by another.
            "fallback_ready": usable_count > 1,
        }


def _chain(providers: list[LlmProvider]) -> LlmProvider:
    """Nest providers into one failover chain: first, then the rest in order."""
    if len(providers) == 1:
        return providers[0]
    return FallbackLlmProvider(providers[0], _chain(providers[1:]))


_service: LlmService | None = None


def get_llm_service() -> LlmService:
    global _service
    if _service is None:
        _service = LlmService()
    return _service
