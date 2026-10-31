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

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from eth_utils import is_address, to_checksum_address

from app.blockchain import jsonrpc
from app.blockchain.jsonrpc import clear_rpc_cache  # noqa: F401 - re-exported for tests
from app.blockchain.types import ChainConfig, ChainStatus, NativeBalance
from app.core.errors import (
    ChainNotConfiguredError,
    InvalidAddressError,
    RateLimitError,
    RpcError,
    preview,
)
from app.core.logging import get_logger
from app.tokens.types import TokenConfig

log = get_logger(__name__)

# First 4 bytes of keccak256("balanceOf(address)"). Part of the ERC-20
# standard, so it is the same for every compliant token.
ERC20_BALANCE_OF_SELECTOR = "0x70a08231"


@dataclass
class RawTokenBalance:
    """A token balance straight from the chain, before pricing.

    `raw` is None when the read failed. That is deliberately distinct from
    zero: "we could not find out" is not the same as "they hold none".
    """

    token: TokenConfig
    raw: int | None


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
                f"'{preview(candidate)}' is not a valid {self._config.name} address.",
                detail="EVM addresses must start with '0x'.",
            )

        if not is_address(candidate):
            raise InvalidAddressError(
                f"'{preview(candidate)}' is not a valid {self._config.name} address.",
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

    async def _rpc_call(self, method: str, params: list, *, use_cache: bool = True) -> str:
        """One JSON-RPC call, through the transport shared with every chain."""
        return await jsonrpc.call(
            self._require_rpc_url(),
            method,
            params,
            chain_name=self._config.name,
            namespace=self._config.id,
            use_cache=use_cache,
        )

    async def _rpc_batch(self, calls: list[tuple[str, list]]) -> list[str | None]:
        """Several calls in one HTTP request. A failed entry comes back as None."""
        # Checked before the URL, as it always was: an empty batch needs no
        # node, so it must not fail on a chain that has none configured.
        if not calls:
            return []
        return await jsonrpc.batch(
            self._require_rpc_url(),
            calls,
            chain_name=self._config.name,
            namespace=self._config.id,
        )

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

    async def get_token_balances(
        self, address: str, tokens: list[TokenConfig]
    ) -> list[RawTokenBalance]:
        """Read ERC-20 balances for several tokens in one request.

        HOW AN ERC-20 BALANCE IS READ
        -----------------------------
        There is no RPC method for "token balance". A token is a smart
        contract, so we call its `balanceOf(address)` function using
        `eth_call`, which executes contract code without sending a
        transaction (no gas, no signature, read-only).

        The call data is the ABI encoding of that function:

            0x70a08231                                   4-byte selector,
                                                         first 4 bytes of
                                                         keccak256("balanceOf(address)")
            000...000d8dA6BF2...96045                    the address, left-padded
                                                         to 32 bytes

        The result is a 32-byte integer: the balance in the token's smallest
        unit, which is why `decimals` from the registry matters.
        """
        checksummed = self.validate_address(address)
        erc20 = [t for t in tokens if not t.is_native and t.address]
        if not erc20:
            return []

        # 12 zero bytes then the 20-byte address, per the ABI encoding rules.
        padded_address = checksummed[2:].lower().rjust(64, "0")
        calldata = f"{ERC20_BALANCE_OF_SELECTOR}{padded_address}"

        calls = [
            ("eth_call", [{"to": token.address, "data": calldata}, "latest"])
            for token in erc20
        ]
        results = await self._rpc_batch(calls)

        balances: list[RawTokenBalance] = []
        for token, result in zip(erc20, results, strict=True):
            if result is None or result == "0x":
                # The call failed, or the contract returned nothing. We record
                # the failure rather than treating it as a zero balance --
                # "unknown" and "none" are different facts.
                log.warning("token_balance_unavailable", chain=self._config.id, token=token.symbol)
                balances.append(RawTokenBalance(token=token, raw=None))
                continue

            balances.append(RawTokenBalance(token=token, raw=int(result, 16)))

        return balances

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
