"""EVM chain adapter.

Serves every EVM-compatible chain -- Ethereum, Sepolia, BNB Smart Chain --
by being parameterised with a ChainConfig and an RPC URL. There is no
"EthereumAdapter" and "BscAdapter"; they are the same code with different
configuration, which is the whole point of the adapter design.

Communication is plain JSON-RPC 2.0 over HTTP. We call the standard
methods directly (eth_getBalance, eth_chainId, eth_blockNumber) rather
than going through a library, so the request/response cycle is visible
and easy to reason about.
"""

from datetime import datetime, timezone
from decimal import Decimal

import httpx
from eth_utils import is_address, to_checksum_address

from app.blockchain.types import ChainConfig, ChainStatus, NativeBalance
from app.core.errors import (
    ChainNotConfiguredError,
    InvalidAddressError,
    RateLimitError,
    RpcError,
)
from app.core.logging import get_logger

log = get_logger(__name__)

# A balance query should be fast. If a node takes longer than this it is
# effectively down, and waiting only makes the user interface feel broken.
RPC_TIMEOUT_SECONDS = 12.0


class EvmAdapter:
    """Reads state from any EVM-compatible chain."""

    def __init__(self, config: ChainConfig, rpc_url: str | None) -> None:
        self._config = config
        self._rpc_url = rpc_url

    @property
    def config(self) -> ChainConfig:
        return self._config

    # -----------------------------------------------------------------
    # Address handling
    # -----------------------------------------------------------------

    def validate_address(self, address: str) -> str:
        """Validate an EVM address and return it EIP-55 checksummed.

        Two levels of checking happen here:

        1. Format -- 0x followed by 40 hexadecimal characters.
        2. Checksum -- EIP-55 encodes a checksum in the capitalisation of
           the letters, which catches most typos. `to_checksum_address`
           recomputes it, so the value we return is always canonical.

        We deliberately accept an all-lowercase address (many tools emit
        one, and it carries no checksum to fail) but reject anything whose
        mixed case is inconsistent, because that indicates a corrupted
        address rather than a lowercase one.
        """
        candidate = address.strip()

        # eth_utils accepts a bare hex string without the 0x prefix. We do
        # not. Requiring the prefix is stricter on purpose: an unprefixed
        # run of hex characters could be almost anything, and a 64-character
        # one is the shape of a PRIVATE KEY. A wallet must reject ambiguous
        # input loudly rather than guess what the user meant.
        if not candidate.startswith("0x"):
            raise InvalidAddressError(
                f"'{address}' is not a valid {self._config.name} address.",
                detail="EVM addresses must start with '0x'.",
            )

        if not is_address(candidate):
            raise InvalidAddressError(
                f"'{address}' is not a valid {self._config.name} address.",
                detail="EVM addresses are '0x' followed by 40 hexadecimal characters.",
            )

        return to_checksum_address(candidate)

    # -----------------------------------------------------------------
    # RPC plumbing
    # -----------------------------------------------------------------

    def _require_rpc_url(self) -> str:
        if not self._rpc_url:
            raise ChainNotConfiguredError(
                f"No RPC endpoint is configured for {self._config.name}.",
                detail=(
                    f"Set {self._config.id.upper()}_RPC_URL in backend/.env "
                    "to a JSON-RPC endpoint for this chain."
                ),
            )
        return self._rpc_url

    async def _rpc_call(self, method: str, params: list) -> str:
        """Make one JSON-RPC 2.0 call and return the raw `result` field.

        Every EVM read in this project goes through here, so retry policy,
        error mapping and logging live in exactly one place.
        """
        url = self._require_rpc_url()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}

        try:
            async with httpx.AsyncClient(timeout=RPC_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise RpcError(
                f"{self._config.name} node did not respond in time.",
                detail=f"{method} timed out after {RPC_TIMEOUT_SECONDS}s",
            ) from exc
        except httpx.HTTPError as exc:
            raise RpcError(
                f"Could not reach the {self._config.name} node.",
                detail=str(exc),
            ) from exc

        if response.status_code == 429:
            raise RateLimitError(
                f"The {self._config.name} RPC provider is rate limiting us.",
                detail="Try again shortly, or configure your own RPC endpoint.",
            )

        if response.status_code >= 400:
            raise RpcError(
                f"{self._config.name} node returned HTTP {response.status_code}.",
                detail=response.text[:200],
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise RpcError(
                f"{self._config.name} node returned a non-JSON response.",
                detail=response.text[:200],
            ) from exc

        # A JSON-RPC error arrives with HTTP 200 and an "error" object,
        # so checking the status code alone is not enough.
        if "error" in body:
            error = body["error"]
            raise RpcError(
                f"{self._config.name} node rejected the request.",
                detail=f"{error.get('code')}: {error.get('message')}",
            )

        if "result" not in body:
            raise RpcError(
                f"{self._config.name} node returned no result.",
                detail=str(body)[:200],
            )

        return body["result"]

    # -----------------------------------------------------------------
    # Reads
    # -----------------------------------------------------------------

    async def get_native_balance(self, address: str) -> NativeBalance:
        """Fetch the native asset balance for an address.

        `eth_getBalance` returns a hex string in wei. We keep the exact
        integer as a string and compute a display value separately --
        never as a float, which would lose precision on large balances.
        """
        checksummed = self.validate_address(address)

        result = await self._rpc_call("eth_getBalance", [checksummed, "latest"])
        wei = int(result, 16)

        log.info(
            "native_balance_fetched",
            chain=self._config.id,
            address=checksummed,
            wei=str(wei),
        )

        return NativeBalance(
            chain=self._config.id,
            address=checksummed,
            symbol=self._config.native_symbol,
            decimals=self._config.native_decimals,
            raw=str(wei),
            formatted=format_units(wei, self._config.native_decimals),
            fetched_at=datetime.now(timezone.utc),
        )

    async def get_status(self) -> ChainStatus:
        """Check the node is configured, reachable, and on the right chain."""
        if not self._rpc_url:
            return ChainStatus(
                chain=self._config.id,
                configured=False,
                reachable=False,
                error="No RPC endpoint configured",
            )

        try:
            chain_id_hex = await self._rpc_call("eth_chainId", [])
            block_hex = await self._rpc_call("eth_blockNumber", [])
        except (RpcError, RateLimitError, ChainNotConfiguredError) as exc:
            return ChainStatus(
                chain=self._config.id,
                configured=True,
                reachable=False,
                error=exc.message,
            )

        reported_chain_id = int(chain_id_hex, 16)

        # Guard against a misconfigured endpoint: pointing ETHEREUM_RPC_URL
        # at a Sepolia node would otherwise silently show testnet balances
        # as if they were mainnet.
        if reported_chain_id != self._config.chain_id:
            return ChainStatus(
                chain=self._config.id,
                configured=True,
                reachable=False,
                chain_id=reported_chain_id,
                error=(
                    f"RPC endpoint reports chain ID {reported_chain_id}, "
                    f"but {self._config.name} is {self._config.chain_id}."
                ),
            )

        return ChainStatus(
            chain=self._config.id,
            configured=True,
            reachable=True,
            chain_id=reported_chain_id,
            block_number=int(block_hex, 16),
        )


def format_units(amount: int, decimals: int, *, precision: int = 6) -> str:
    """Convert a smallest-unit integer into a readable decimal string.

    Uses Decimal, never float. 0.1 cannot be represented exactly in binary
    floating point, and silently wrong balances are unacceptable in a
    wallet.

        format_units(1234500000000000000, 18) -> '1.2345'
        format_units(0, 18)                   -> '0'
    """
    if amount == 0:
        return "0"

    value = Decimal(amount) / (Decimal(10) ** decimals)
    quantised = round(value, precision)

    # Strip trailing zeros so '1.230000' reads as '1.23'.
    text = format(quantised, "f").rstrip("0").rstrip(".")
    return text or "0"
