"""Bitcoin chain adapter. Read-only.

Bitcoin is the third genuinely different design the adapter layer has to
absorb. There are no accounts and no balances on-chain -- only unspent
transaction outputs -- so "the balance of an address" is something a
service computes by summing the outputs that address received and has not
spent. There are also no tokens and no smart-contract state to read.

Data comes from the Esplora REST API, which two independent public services
run identically. They are tried in order, so either can be down.

ADDRESS FORMATS
---------------
    1...    legacy P2PKH      base58check, version 0x00
    3...    P2SH              base58check, version 0x05
    bc1q... native SegWit     bech32,  witness version 0
    bc1p... Taproot           bech32m, witness version 1

Every format carries a checksum, so unlike Solana a mistyped Bitcoin
address is caught rather than silently pointing somewhere else.

Everything below was checked against the live network first: both providers
reported the same genesis hash and tip height, and the test addresses of
every format were taken from a real recent block.
"""

import re
from datetime import datetime, timezone

from app.blockchain import jsonrpc
from app.blockchain.adapters.evm import format_units
from app.blockchain.encoding import b58check_decode, decode_segwit
from app.blockchain.types import ChainConfig, ChainStatus, NativeBalance
from app.core.errors import (
    ChainNotConfiguredError,
    InvalidAddressError,
    RateLimitError,
    RpcError,
    preview,
)
from app.core.logging import get_logger

log = get_logger(__name__)

# Bitcoin's genesis block. Every mainnet node agrees on it; a testnet or
# signet service does not, which is how a misconfigured endpoint is caught.
MAINNET_GENESIS = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"

P2PKH_VERSION = 0x00
P2SH_VERSION = 0x05
TESTNET_VERSIONS = {0x6F, 0xC4}
# A WIF private key is valid base58check with its own correct checksum, so a
# checksum test alone would accept one. Its version byte gives it away.
PRIVATE_KEY_VERSIONS = {0x80, 0xEF}

EXTENDED_PRIVATE_PREFIXES = ("xprv", "yprv", "zprv", "tprv", "uprv", "vprv")
EXTENDED_PUBLIC_PREFIXES = ("xpub", "ypub", "zpub", "tpub", "upub", "vpub")

# The longest real address, a bech32m Taproot one, is 62 characters. The cap
# also bounds the cost of base58 decoding, which grows with input length.
MAX_INPUT_LENGTH = 100
_HEX_64 = re.compile(r"(?:0x)?[0-9a-fA-F]{64}")

# The genesis hash never changes, so it is cached for an hour.
GENESIS_TTL_SECONDS = 3600.0

ADDRESS_TYPES = {
    (0, 20): "Native SegWit (P2WPKH)",
    (0, 32): "SegWit script (P2WSH)",
    (1, 32): "Taproot (P2TR)",
}


class BitcoinAdapter:
    """Reads Bitcoin balances through Esplora-compatible REST services."""

    def __init__(self, config: ChainConfig, api_urls: list[str]) -> None:
        self._config = config
        self._api_urls = [url.rstrip("/") for url in api_urls if url]

    @property
    def config(self) -> ChainConfig:
        return self._config

    def validate_address(self, address: str) -> str:
        """Validate a mainnet address; return it canonical (bech32 lowercased)."""
        candidate = address.strip()

        # Secret shapes are checked FIRST, before the length cap. An extended
        # private key is 111 characters, so checking length first answered a
        # pasted wallet key with a bland "not an address" instead of the
        # warning it needs. These checks read at most the first few
        # characters, so they cost nothing however long the input is.
        prefix = candidate[:4].lower()
        if prefix in EXTENDED_PRIVATE_PREFIXES:
            raise InvalidAddressError(
                "That is an extended PRIVATE key, which controls a whole wallet.",
                detail="Never paste it anywhere. If it was shared, move the funds now.",
            )
        if prefix in EXTENDED_PUBLIC_PREFIXES:
            raise InvalidAddressError(
                "That is an extended public key, not a single address.",
                detail="Paste one receiving address from your wallet instead.",
            )
        if _HEX_64.fullmatch(candidate):
            raise InvalidAddressError(
                "That has the shape of a PRIVATE KEY, not an address.",
                detail="It is 64 hexadecimal characters. If it is a key, treat it as compromised.",
            )

        # The cap bounds the cost of base58 decoding below, which grows with
        # the length of the input.
        if not candidate or len(candidate) > MAX_INPUT_LENGTH:
            raise InvalidAddressError(
                "That is not a Bitcoin address.",
                detail="Bitcoin addresses are 26 to 62 characters.",
            )

        if candidate.startswith("0x"):
            raise InvalidAddressError(
                f"'{preview(candidate)}' is not a Bitcoin address.",
                detail="That looks like an Ethereum address.",
            )

        lowered = candidate.lower()

        if lowered.startswith(("bc1", "tb1", "bcrt1")):
            try:
                hrp, version, program = decode_segwit(candidate)
            except ValueError as exc:
                raise InvalidAddressError(
                    f"'{preview(candidate)}' is not a valid Bitcoin address.", detail=f"Rejected: {exc}."
                ) from exc
            if hrp != "bc":
                raise InvalidAddressError(
                    "That is a Bitcoin testnet address.",
                    detail="Fire DEX reads Bitcoin mainnet. Mainnet SegWit addresses start with bc1.",
                )
            return lowered

        try:
            version, payload = b58check_decode(candidate)
        except ValueError as exc:
            raise InvalidAddressError(
                f"'{preview(candidate)}' is not a valid Bitcoin address.", detail=f"Rejected: {exc}."
            ) from exc

        if version in PRIVATE_KEY_VERSIONS:
            raise InvalidAddressError(
                "That is a Bitcoin PRIVATE KEY (WIF format), not an address.",
                detail="Never paste it anywhere. If it was shared, move the funds now.",
            )
        if version in TESTNET_VERSIONS:
            raise InvalidAddressError(
                "That is a Bitcoin testnet address.",
                detail="Fire DEX reads Bitcoin mainnet, where addresses start with 1, 3 or bc1.",
            )
        if version not in (P2PKH_VERSION, P2SH_VERSION) or len(payload) != 20:
            raise InvalidAddressError(
                f"'{preview(candidate)}' is not a valid Bitcoin address.",
                detail="It decodes, but not to a known address type.",
            )
        return candidate

    def address_type(self, address: str) -> str:
        """A readable name for the address format, for display."""
        canonical = self.validate_address(address)
        if canonical.startswith("bc1"):
            _, version, program = decode_segwit(canonical)
            return ADDRESS_TYPES.get((version, len(program)), f"SegWit version {version}")
        version, _ = b58check_decode(canonical)
        return "Legacy (P2PKH)" if version == P2PKH_VERSION else "Script (P2SH)"

    async def _get(self, path: str, *, text: bool = False, ttl: float | None = None):
        """GET from the first provider that answers.

        Both services implement the same API, so a failure on one is retried
        on the next rather than reported straight away.
        """
        if not self._api_urls:
            raise ChainNotConfiguredError(
                "No Bitcoin API endpoint is configured.",
                detail="Set BITCOIN_API_URLS in backend/.env to an Esplora-compatible API.",
            )

        last_error: Exception | None = None
        for base in self._api_urls:
            try:
                return await jsonrpc.get_json(
                    f"{base}{path}",
                    chain_name=self._config.name,
                    namespace=self._config.id,
                    ttl_seconds=ttl,
                    text=text,
                )
            except (RpcError, RateLimitError) as exc:
                log.warning("bitcoin_provider_failed", provider=base, error=exc.message)
                last_error = exc
        assert last_error is not None
        raise last_error

    async def get_native_balance(self, address: str) -> NativeBalance:
        """Confirmed balance in satoshis: outputs received minus outputs spent.

        Unconfirmed transactions are excluded on purpose. A payment that has
        not been mined can still be replaced or dropped, so counting it would
        report money that is not yet reliably there.
        """
        owner = self.validate_address(address)
        info = await self._get(f"/address/{owner}")
        try:
            stats = info["chain_stats"]
            satoshis = int(stats["funded_txo_sum"]) - int(stats["spent_txo_sum"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RpcError(
                "The Bitcoin API returned an unexpected response.", detail=str(info)[:200]
            ) from exc
        if satoshis < 0:
            raise RpcError("The Bitcoin API reported more spent than received, which is impossible.")

        log.info("native_balance_fetched", chain=self._config.id, address=owner, satoshis=satoshis)

        return NativeBalance(
            chain=self._config.id,
            address=owner,
            symbol=self._config.native_symbol,
            decimals=self._config.native_decimals,
            raw=str(satoshis),
            formatted=format_units(satoshis, self._config.native_decimals, precision=8),
            fetched_at=datetime.now(timezone.utc),
        )

    async def get_status(self) -> ChainStatus:
        """Reachability, and proof the service is on Bitcoin mainnet."""
        if not self._api_urls:
            return ChainStatus(
                chain=self._config.id, configured=False, reachable=False,
                error="No Bitcoin API endpoint configured",
            )

        try:
            genesis = await self._get("/block-height/0", text=True, ttl=GENESIS_TTL_SECONDS)
            height = int(await self._get("/blocks/tip/height", text=True))
        except (RpcError, RateLimitError, ValueError) as exc:
            message = exc.message if isinstance(exc, (RpcError, RateLimitError)) else str(exc)
            return ChainStatus(chain=self._config.id, configured=True, reachable=False, error=message)

        if genesis != MAINNET_GENESIS:
            return ChainStatus(
                chain=self._config.id,
                configured=True,
                reachable=False,
                error="The Bitcoin API serves a different network than mainnet.",
            )

        return ChainStatus(chain=self._config.id, configured=True, reachable=True, block_number=height)
