"""Core blockchain types.

These models are the vocabulary the rest of the application uses to talk
about chains. Nothing above this layer should deal in raw dictionaries or
untyped strings.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ChainFamily(str, Enum):
    """The technical family a chain belongs to.

    This exists because Ethereum, Solana and Bitcoin are genuinely
    different technologies, not variations of one design:

      EVM      account model, secp256k1 keys, EIP-155 chain IDs
      SOLANA   account model, ed25519 keys, no chain ID, SPL tokens
      BITCOIN  UTXO model, no general-purpose smart contracts

    Code that needs to branch on chain behaviour branches on family, never
    on the chain's name.
    """

    EVM = "evm"
    SOLANA = "solana"
    BITCOIN = "bitcoin"


class ChainConfig(BaseModel):
    """Everything the application knows about one chain.

    A chain is a configuration entry, not a code path. Adding BNB Smart
    Chain means adding one of these, not writing new balance logic.
    """

    id: str = Field(description="Stable internal key, e.g. 'ethereum'")
    name: str = Field(description="Human-readable name")
    short_name: str = Field(description="Short label for compact UI")
    family: ChainFamily
    chain_id: int | None = Field(
        default=None,
        description="EIP-155 chain ID. EVM chains only; null for Solana and Bitcoin.",
    )
    native_symbol: str = Field(description="Ticker of the gas/native asset")
    native_decimals: int = Field(description="Decimal places of the native asset")
    is_testnet: bool
    explorer_url: str
    color: str = Field(description="Accent colour used by the UI")
    is_active: bool = Field(
        default=False,
        description=(
            "Whether Fire DEX supports this chain. Only EVM chains appear in the "
            "MetaMask network switcher; Solana and Bitcoin are read by address."
        ),
    )


class NativeBalance(BaseModel):
    """The native asset balance of one address on one chain.

    Note that `raw` is a STRING, not an int.

    A balance in wei routinely exceeds 2^53, which is the largest integer
    JavaScript can represent exactly. Sending it as a JSON number would
    silently corrupt it in the browser. We send the exact integer as a
    string and let the frontend parse it into a BigInt.
    """

    chain: str
    address: str
    symbol: str
    decimals: int
    raw: str = Field(description="Exact balance in the smallest unit (wei), as a string")
    formatted: str = Field(description="Human-readable balance, e.g. '1.2345'")
    fetched_at: datetime = Field(description="When we retrieved this from the node (UTC)")


class ChainStatus(BaseModel):
    """Liveness of one chain's RPC connection."""

    chain: str
    configured: bool
    reachable: bool
    chain_id: int | None = None
    block_number: int | None = None
    slot: int | None = Field(
        default=None,
        description=(
            "Solana only. Slots advance every ~400ms whether or not a block is "
            "produced, so the slot is always ahead of the block height."
        ),
    )
    error: str | None = None
