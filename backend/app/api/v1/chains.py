"""Chain and balance endpoints.

Everything here is read-only. Fire DEX never constructs or submits a
transaction from the backend -- signing happens in the user's wallet, in
the browser. These routes exist to read public chain state.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.blockchain.factory import get_adapter
from app.blockchain.registry import get_chain, list_chains
from app.blockchain.types import ChainConfig, ChainStatus, NativeBalance
from app.config import Settings, get_settings

router = APIRouter(prefix="/chains", tags=["chains"])

SettingsDep = Annotated[Settings, Depends(get_settings)]

ChainPath = Annotated[
    str,
    Path(description="Chain key, e.g. 'ethereum' or 'sepolia'", examples=["sepolia"]),
]


@router.get("", response_model=list[ChainConfig])
async def get_chains() -> list[ChainConfig]:
    """Every chain the application knows about.

    The frontend uses this to render the network selector. Chains with
    `is_active` false are shown but not selectable, so the roadmap is
    visible without pretending unfinished chains work.
    """
    return list_chains()


@router.get("/{chain}", response_model=ChainConfig)
async def get_chain_detail(chain: ChainPath) -> ChainConfig:
    """Configuration for one chain."""
    return get_chain(chain)


@router.get("/{chain}/status", response_model=ChainStatus)
async def get_chain_status(chain: ChainPath, settings: SettingsDep) -> ChainStatus:
    """Whether this chain's RPC endpoint is configured and reachable.

    Also verifies the endpoint reports the chain ID we expect, which
    catches a misconfiguration that would otherwise show testnet balances
    as if they were mainnet.
    """
    adapter = get_adapter(chain, settings)
    return await adapter.get_status()


@router.get("/{chain}/balance/{address}", response_model=NativeBalance)
async def get_native_balance(
    chain: ChainPath,
    address: Annotated[
        str,
        Path(description="Public address to query. Never a private key or seed phrase."),
    ],
    settings: SettingsDep,
) -> NativeBalance:
    """Native asset balance (ETH, BNB, ...) for a public address.

    The address is validated against this specific chain's format before
    any network call is made -- an Ethereum address is meaningless on
    Solana, and passing one through would produce a confusing node error
    instead of a clear message.
    """
    adapter = get_adapter(chain, settings)
    return await adapter.get_native_balance(address)


@router.get("/{chain}/validate", response_model=dict)
async def validate_address(
    chain: ChainPath,
    address: Annotated[str, Query(description="Address to check")],
    settings: SettingsDep,
) -> dict:
    """Check an address is valid for this chain, and return it normalised.

    Returns the EIP-55 checksummed form for EVM chains. Raises 400 with a
    clear message if it is not valid.
    """
    adapter = get_adapter(chain, settings)
    return {"chain": chain, "address": adapter.validate_address(address), "valid": True}
