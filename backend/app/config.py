"""Application configuration.

Every setting comes from environment variables (or a local .env file).
Nothing secret is ever written into source code.

Read this file first when you want to know "what can this app be told to do?".
"""

from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppMode(str, Enum):
    """Which safety regime the application is running under.

    This is deliberately separate from "is the code in debug mode".
    It answers a different question: *can this process touch real money?*

    DEVELOPMENT - local work. Mock data allowed, clearly marked. No mainnet writes.
    TESTNET     - talks to real test networks (Sepolia). Real signing, worthless coins.
    PRODUCTION  - mainnet reads. Reserved for later; not used in the 7th-sem project.
    """

    DEVELOPMENT = "development"
    TESTNET = "testnet"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Application settings, loaded from the environment.

    Field names map to env vars case-insensitively:
        APP_MODE=testnet  ->  settings.app_mode
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Identity ---------------------------------------------------
    app_name: str = "Fire DEX"
    app_version: str = "0.1.0"

    # --- Safety regime ----------------------------------------------
    # Defaults to the safest option. You must opt *in* to anything riskier.
    app_mode: AppMode = AppMode.DEVELOPMENT

    # --- Logging ----------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = False  # True in production; human-readable locally

    # --- CORS -------------------------------------------------------
    # The Vite dev server origin. Comma-separated if you need more.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Host headers the server will answer. This is the defence against DNS
    # rebinding: a malicious page can make its own domain resolve to
    # 127.0.0.1, which makes its requests same-origin so CORS never applies,
    # but the browser still sends that domain in the Host header.
    allowed_hosts: str = "127.0.0.1,localhost"

    # --- Database ---------------------------------------------------
    # SQLite for the prototype: zero setup, no Docker needed.
    # Switching to PostgreSQL later is only a change to this one string,
    # because everything above it goes through SQLAlchemy.
    #   postgresql+psycopg://user:pass@localhost:5432/firedex
    database_url: str = "sqlite+aiosqlite:///./data/firedex.db"

    # --- Blockchain RPC endpoints -----------------------------------
    # These default to public, keyless endpoints so the project runs with
    # no signup. They are rate limited and are NOT suitable for heavy use
    # -- set your own (e.g. Alchemy) in .env when you have a key.
    ethereum_rpc_url: str = "https://ethereum-rpc.publicnode.com"
    sepolia_rpc_url: str = "https://ethereum-sepolia-rpc.publicnode.com"
    # Verified keyless: reports chain ID 56, advances, accepts batched calls.
    bsc_rpc_url: str = "https://bsc-rpc.publicnode.com"
    # The official endpoint, not publicnode. Publicnode's Solana service
    # blocks getTokenAccountsByOwner, which SPL balances need, and returned
    # a block height above its own slot on every request we made.
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    # Two independent services running the same Esplora API, tried in order.
    # Both were checked to report Bitcoin's genesis hash and the same tip.
    bitcoin_api_urls: str = "https://mempool.space/api,https://blockstream.info/api"

    # --- AI providers ------------------------------------------------
    # Which to prefer when both are usable: "online" or "local".
    llm_preference: str = "online"

    # Online provider. No key means online mode is simply unavailable --
    # the app falls back to Ollama rather than failing.
    groq_api_key: str = ""
    # Verified against Groq's /models endpoint. Provider model names are
    # rotated and retired -- an earlier default returned HTTP 404 because
    # the Llama models had been withdrawn. Check /api/v1/ai/status if
    # analyses start failing with 404.
    groq_model: str = "openai/gpt-oss-120b"

    # Second online provider, used when Groq is rate limited or down. A
    # fixed model version rather than a "-latest" alias, so the model stored
    # with each analysis means the same thing next month.
    #
    # Chosen by running full analyses, not by name. flash-lite completed in
    # 10.7s with a reviewer score of 84.3; gemini-3.5-flash scored the same
    # but took 40s and failed outright on two of three runs.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # Local provider.
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    # --- Analysis limits ---------------------------------------------
    # The reviewer may request one re-analysis. Bounded so a disagreement
    # between reviewer and orchestrator cannot loop forever.
    max_reanalysis_attempts: int = 1

    def rpc_url_for(self, chain_id: str) -> str | None:
        """RPC endpoint for a chain key, or None if not configured.

        Keeps the mapping from chain key to setting in one place, so an
        adapter never has to know how settings are named.
        """
        mapping = {
            "ethereum": self.ethereum_rpc_url,
            "sepolia": self.sepolia_rpc_url,
            "bsc": self.bsc_rpc_url,
            "solana": self.solana_rpc_url,
        }
        return mapping.get(chain_id) or None

    @property
    def bitcoin_api_url_list(self) -> list[str]:
        return [url.strip() for url in self.bitcoin_api_urls.split(",") if url.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        """CORS origins as a list, trimmed of whitespace and blanks."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_mode is AppMode.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton.

    Cached so the .env file is parsed once per process, and so tests can
    override it via dependency injection.
    """
    return Settings()
