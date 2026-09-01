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
from app.market.cache import TtlCache
from app.tokens.types import TokenConfig

log = get_logger(__name__)

# A balance query should be fast. If a node takes longer than this it is
# effectively down, and waiting only makes the user interface feel broken.
RPC_TIMEOUT_SECONDS = 12.0

# Chain reads are cached briefly.
#
# WHY: the dashboard polls balances, the block height and the portfolio on
# separate timers. Without this, every poll from every open tab becomes a
# request to a shared public node, which then rate limits us -- we measured
# a portfolio request degrading from 8 seconds to 48 seconds and failing.
#
# A block is produced roughly every 12 seconds on Ethereum, so a balance
# cannot meaningfully change faster than that. An 8-second TTL is therefore
# invisible to the user while collapsing repeated polls into one call.
RPC_CACHE_TTL_SECONDS = 8.0

_rpc_cache: TtlCache[str] = TtlCache(default_ttl_seconds=RPC_CACHE_TTL_SECONDS)


def clear_rpc_cache() -> None:
    """Empty the RPC cache. Used by tests to keep them independent."""
    _rpc_cache.clear()

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

    def _cache_key(self, method: str, params: list) -> str:
        return f"{self._config.id}:{method}:{params}"

    async def _rpc_call(self, method: str, params: list, *, use_cache: bool = True) -> str:
        """Make one JSON-RPC 2.0 call and return the raw `result` field.

        Every EVM read in this project goes through here, so caching, retry
        policy, error mapping and logging live in exactly one place.
        """
        key = self._cache_key(method, params)
        if use_cache:
            cached = _rpc_cache.get_fresh(key)
            if cached is not None:
                return cached

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

        result = body["result"]
        if use_cache:
            _rpc_cache.set(key, result)
        return result

    async def _rpc_batch(self, calls: list[tuple[str, list]]) -> list[str | None]:
        """Make several JSON-RPC calls in ONE HTTP request.

        Reading ten token balances as ten separate requests is ten times the
        latency and ten times the rate-limit consumption. JSON-RPC 2.0 allows
        an array of requests in a single POST, which public nodes support.

        Results come back in the same order as `calls`. An entry is None if
        that individual call failed -- one bad token must not discard the
        other nine.
        """
        if not calls:
            return []

        # The whole batch is cached as one unit, keyed by its contents. A
        # portfolio refresh repeats the identical batch, so this collapses
        # repeated polls into a single request to the node.
        batch_key = self._cache_key("batch", calls)
        cached_batch = _rpc_cache.get_fresh(batch_key)
        if cached_batch is not None:
            import json as _json

            return _json.loads(cached_batch)

        url = self._require_rpc_url()
        payload = [
            {"jsonrpc": "2.0", "id": index, "method": method, "params": params}
            for index, (method, params) in enumerate(calls)
        ]

        try:
            async with httpx.AsyncClient(timeout=RPC_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise RpcError(
                f"{self._config.name} node did not respond in time.",
                detail=f"batch of {len(calls)} calls timed out",
            ) from exc
        except httpx.HTTPError as exc:
            raise RpcError(
                f"Could not reach the {self._config.name} node.", detail=str(exc)
            ) from exc

        if response.status_code == 429:
            raise RateLimitError(f"The {self._config.name} RPC provider is rate limiting us.")
        if response.status_code >= 400:
            raise RpcError(
                f"{self._config.name} node returned HTTP {response.status_code}.",
                detail=response.text[:200],
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise RpcError(f"{self._config.name} node returned non-JSON.") from exc

        # Some nodes answer a batch with a single error object.
        if isinstance(body, dict):
            raise RpcError(
                f"{self._config.name} node rejected the batch.",
                detail=str(body.get("error", body))[:200],
            )

        # A batch response may arrive out of order, so map by id.
        by_id: dict[int, str | None] = {}
        for item in body:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if "error" in item:
                log.warning(
                    "batch_call_failed",
                    chain=self._config.id,
                    call_id=item_id,
                    error=str(item["error"])[:120],
                )
                by_id[item_id] = None
            else:
                by_id[item_id] = item.get("result")

        results = [by_id.get(index) for index in range(len(calls))]

        import json as _json

        _rpc_cache.set(batch_key, _json.dumps(results))
        return results

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
