"""Adapter factory.

One place that decides which adapter class serves a given chain, and
supplies it with the right RPC endpoint from configuration.

Callers ask for an adapter by chain key and get something satisfying the
ChainAdapter protocol. When SolanaAdapter and BitcoinAdapter arrive, only
this file changes.
"""

from app.blockchain.adapters.base import ChainAdapter
from app.blockchain.adapters.evm import EvmAdapter
from app.blockchain.registry import get_chain
from app.blockchain.types import ChainFamily
from app.config import Settings
from app.core.errors import ChainNotSupportedError


def get_adapter(chain_key: str, settings: Settings) -> ChainAdapter:
    """Build the adapter for one chain.

    Raises:
        ChainNotSupportedError: unknown chain, or a family not implemented yet.
    """
    config = get_chain(chain_key)

    if config.family is ChainFamily.EVM:
        return EvmAdapter(config=config, rpc_url=settings.rpc_url_for(config.id))

    # Known chain, adapter not written yet. This is a deliberate,
    # informative failure rather than a crash.
    raise ChainNotSupportedError(
        f"{config.name} is not implemented yet.",
        detail=(
            f"The {config.family.value} adapter is planned for a later milestone. "
            "Ethereum, Sepolia and other EVM chains are available now."
        ),
    )
