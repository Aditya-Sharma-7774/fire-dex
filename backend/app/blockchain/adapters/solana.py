"""Solana chain adapter.

Solana is the chain that tests whether the adapter design is real. It
differs from Ethereum in every respect the rest of the application must not
see:

    Ethereum                          Solana
    --------                          ------
    secp256k1 keys                    ed25519 keys
    address = hash of the public key  address = the public key itself
    hex, EIP-55 checksum              base58, NO checksum
    numeric chain ID                  genesis hash identifies the cluster
    token balance = an entry inside   token balance = a separate account,
      the token contract's mapping      one or more per holder per mint
    you must already know which       an owner's token accounts can be
      contracts to ask                  listed directly

The last row matters most. On Ethereum we can only read balances for tokens
we already have in a registry. On Solana the node can enumerate every token
an address holds, so this adapter needs no token registry to find holdings.

Every constant below was verified against a live mainnet node before being
written down, not copied from documentation.
"""

import asyncio
from datetime import datetime, timezone

from Crypto.Signature import eddsa
from pydantic import BaseModel, Field

from app.blockchain import jsonrpc
from app.blockchain.encoding import b58decode
from app.blockchain.adapters.evm import format_units
from app.blockchain.types import ChainConfig, ChainStatus, NativeBalance
from app.core.errors import (
    ChainNotConfiguredError,
    InvalidAddressError,
    RateLimitError,
    RpcError,
    preview,
)
from app.core.logging import get_logger
from app.tokens.registry import list_tokens

log = get_logger(__name__)

# The genesis hash is the identity of a Solana cluster, playing the role the
# chain ID plays on Ethereum. Both values were read from the clusters'
# public nodes; mainnet's was confirmed by two independent providers.
GENESIS_HASHES = {
    "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d": "Solana mainnet",
    "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG": "Solana devnet",
}
MAINNET_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"

# Both are executable accounts owned by the upgradeable BPF loader, checked
# on-chain. Token-2022 is not optional: one wallet we inspected held 11
# accounts under the original program and 61 under Token-2022, so reading
# only the first would have missed most of what it owned.
TOKEN_PROGRAMS = {
    "token": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "token-2022": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
}

# Mints we can name come from the token registry, which holds every verified
# Solana token once. Any other mint is still reported, by its address.
KNOWN_MINTS = {
    token.address: token.symbol for token in list_tokens("solana") if token.address
}

# A public key is 32 bytes, which base58-encodes to 32-44 characters. The
# cap exists for a security reason, not tidiness: base58 decoding is a
# big-integer conversion that grows quadratically with input length, so an
# unbounded string would let one request consume the CPU.
MAX_ADDRESS_LENGTH = 44
PUBLIC_KEY_BYTES = 32
SECRET_KEY_BYTES = 64


def is_on_curve(public_key: bytes) -> bool:
    """Whether 32 bytes are a valid ed25519 point.

    A wallet's address is its public key, so it is on the curve. A
    program-derived address -- such as an associated token account -- is
    deliberately chosen OFF the curve, so that no private key can ever exist
    for it. Checked against both: a fee payer that signed a mainnet
    transaction is on-curve, and its USDC token account is not.
    """
    try:
        eddsa.import_public_key(public_key)
    except ValueError:
        return False
    return True


class SplTokenBalance(BaseModel):
    """One mint's total holding, summed across every account that holds it."""

    mint: str
    symbol: str | None = Field(description="Set only for mints we can name with certainty")
    raw: str = Field(description="Exact amount in the token's smallest unit, as a string")
    decimals: int
    formatted: str = Field(description="Full precision, never rounded to zero")
    accounts: int = Field(description="Token accounts this mint is spread across")
    program: str = Field(description="'token' or 'token-2022'")


class SplTokenHoldings(BaseModel):
    """Every SPL token an address holds."""

    chain: str
    owner: str
    owner_is_wallet: bool = Field(
        description=(
            "True when the address is a point on the ed25519 curve, meaning a "
            "private key can exist for it. False for program-derived addresses."
        )
    )
    tokens: list[SplTokenBalance]
    total_mints: int
    total_accounts: int
    truncated: bool = Field(description="True when more mints exist than were returned")
    incomplete: bool = Field(description="True when one token program could not be read")
    failed_programs: list[str] = Field(default_factory=list)
    fetched_at: datetime


class SolanaAdapter:
    """Reads state from a Solana cluster."""

    def __init__(self, config: ChainConfig, rpc_url: str | None) -> None:
        self._config = config
        self._rpc_url = rpc_url

    @property
    def config(self) -> ChainConfig:
        return self._config

    def validate_address(self, address: str) -> str:
        """Validate a Solana address and return it unchanged.

        There is no checksum in a Solana address. A typo that still decodes
        to 32 bytes is indistinguishable from a real address, which is a
        property of the chain, not a gap in this check.

        Two things are refused loudly because they are what a user is most
        likely to paste by mistake, and both are secrets:

          * a 64-byte value, which is the shape of an exported keypair
          * a JSON array of numbers, which is a keypair file from solana-keygen

        A raw 32-byte private seed has exactly the shape of a public key and
        cannot be told apart by any format check. Wallets export the 64-byte
        form, so that is the case this guards against.
        """
        candidate = address.strip()

        if candidate.startswith("0x"):
            raise InvalidAddressError(
                f"'{preview(candidate)}' is not a Solana address.",
                detail="That looks like an Ethereum address. Solana addresses are base58.",
            )

        if candidate.startswith("["):
            raise InvalidAddressError(
                "That looks like a Solana keypair file, which contains a private key.",
                detail="Never paste a keypair anywhere. Use the public address only.",
            )

        if len(candidate) > MAX_ADDRESS_LENGTH * 2 + 4:
            raise InvalidAddressError(
                "That is far too long to be a Solana address.",
                detail=f"Solana addresses are 32 to {MAX_ADDRESS_LENGTH} characters.",
            )

        try:
            decoded = b58decode(candidate)
        except ValueError as exc:
            raise InvalidAddressError(
                f"'{preview(candidate)}' is not a valid Solana address.",
                detail=f"{exc}. Base58 excludes 0, O, I and l.",
            ) from exc

        if len(decoded) == SECRET_KEY_BYTES:
            raise InvalidAddressError(
                "That has the shape of a Solana PRIVATE KEY, not an address.",
                detail=(
                    "It decodes to 64 bytes, which is an exported keypair. If it is "
                    "your key, treat it as compromised and move your funds."
                ),
            )

        if len(decoded) != PUBLIC_KEY_BYTES:
            raise InvalidAddressError(
                f"'{preview(candidate)}' is not a valid Solana address.",
                detail=f"It decodes to {len(decoded)} bytes; a Solana address is 32.",
            )

        return candidate

    def is_wallet_address(self, address: str) -> bool:
        return is_on_curve(b58decode(self.validate_address(address)))

    def _require_rpc_url(self) -> str:
        if not self._rpc_url:
            raise ChainNotConfiguredError(
                f"No RPC endpoint is configured for {self._config.name}.",
                detail="Set SOLANA_RPC_URL in backend/.env to a Solana JSON-RPC endpoint.",
            )
        return self._rpc_url

    async def _rpc_call(self, method: str, params: list):
        return await jsonrpc.call(
            self._require_rpc_url(),
            method,
            params,
            chain_name=self._config.name,
            namespace=self._config.id,
        )

    async def _rpc_batch(self, calls: list[tuple[str, list]]) -> list:
        if not calls:
            return []
        return await jsonrpc.batch(
            self._require_rpc_url(),
            calls,
            chain_name=self._config.name,
            namespace=self._config.id,
        )

    async def get_native_balance(self, address: str) -> NativeBalance:
        """SOL balance. The node returns lamports; one SOL is 10^9 of them."""
        owner = self.validate_address(address)
        result = await self._rpc_call("getBalance", [owner])
        lamports = int(result["value"])

        log.info("native_balance_fetched", chain=self._config.id, address=owner, lamports=lamports)

        return NativeBalance(
            chain=self._config.id,
            address=owner,
            symbol=self._config.native_symbol,
            decimals=self._config.native_decimals,
            raw=str(lamports),
            formatted=format_units(lamports, self._config.native_decimals),
            fetched_at=datetime.now(timezone.utc),
        )

    async def get_token_balances(
        self, address: str, *, limit: int = 50, include_zero: bool = False
    ) -> SplTokenHoldings:
        """Every SPL token the address holds, summed per mint.

        Summing is required, not cosmetic. One mint can be spread across
        several token accounts owned by the same address -- a wallet we
        inspected held one mint in four -- so reading a single account would
        under-report the holding.

        Both token programs are queried concurrently, as two separate
        requests rather than one batch. The official endpoint allows this
        method ten times per window on its own but ZERO times inside a batch
        -- its rate-limit headers say so -- so batching it fails every time.

        If one program cannot be read, the other's results are still returned
        and the failure is named, because "we could not read Token-2022" is a
        different fact from "this wallet holds no Token-2022 tokens".
        """
        owner = self.validate_address(address)

        async def read(program_id: str):
            try:
                return await self._rpc_call(
                    "getTokenAccountsByOwner",
                    [owner, {"programId": program_id}, {"encoding": "jsonParsed"}],
                )
            except (RpcError, RateLimitError) as exc:
                log.warning("token_program_read_failed", chain=self._config.id, error=exc.message)
                return None

        programs = list(TOKEN_PROGRAMS.items())
        results = await asyncio.gather(*(read(program_id) for _, program_id in programs))

        totals: dict[str, dict] = {}
        failed: list[str] = []
        account_count = 0

        for (program_name, _), result in zip(programs, results, strict=True):
            if result is None:
                failed.append(program_name)
                continue

            for entry in result.get("value", []):
                parsed = _parse_token_account(entry)
                if parsed is None:
                    continue

                mint, account_owner, amount, decimals = parsed
                # The node is asked for this owner's accounts, but a faulty
                # or dishonest node could return someone else's. Checking
                # costs nothing and keeps another wallet's holdings out.
                if account_owner != owner:
                    log.warning("foreign_token_account_skipped", chain=self._config.id, mint=mint)
                    continue

                account_count += 1
                holding = totals.setdefault(
                    mint,
                    {"raw": 0, "decimals": decimals, "accounts": 0, "program": program_name},
                )
                holding["raw"] += amount
                holding["accounts"] += 1

        balances = [
            SplTokenBalance(
                mint=mint,
                symbol=KNOWN_MINTS.get(mint),
                raw=str(holding["raw"]),
                decimals=holding["decimals"],
                # Full precision on purpose. Dust is everywhere on Solana,
                # and rounding a 12-decimal balance to six places would show
                # a non-zero holding as "0".
                formatted=format_units(holding["raw"], holding["decimals"], precision=holding["decimals"]),
                accounts=holding["accounts"],
                program=holding["program"],
            )
            for mint, holding in totals.items()
            if include_zero or holding["raw"] > 0
        ]

        # Named mints first, then by mint address. Ordering unknown tokens by
        # amount would be meaningless: raw amounts with different decimals
        # are not comparable, and nothing here knows their price.
        balances.sort(key=lambda b: (b.symbol is None, b.symbol or "", b.mint))

        if failed:
            log.warning("token_programs_unavailable", chain=self._config.id, programs=failed)

        return SplTokenHoldings(
            chain=self._config.id,
            owner=owner,
            owner_is_wallet=is_on_curve(b58decode(owner)),
            tokens=balances[:limit],
            total_mints=len(balances),
            total_accounts=account_count,
            truncated=len(balances) > limit,
            incomplete=bool(failed),
            failed_programs=failed,
            fetched_at=datetime.now(timezone.utc),
        )

    async def get_status(self) -> ChainStatus:
        """Reachability, and proof the node serves the cluster we expect.

        Two checks guard against data that looks fine but is wrong:

          * the genesis hash must be mainnet's -- pointing SOLANA_RPC_URL at
            devnet would otherwise present test tokens as real holdings
          * block height may never exceed slot. One public provider we tested
            reported a block height above its own slot on every request, which
            is impossible, so an impossible height is withheld, not shown
        """
        if not self._rpc_url:
            return ChainStatus(
                chain=self._config.id,
                configured=False,
                reachable=False,
                error="No RPC endpoint configured",
            )

        try:
            genesis, slot, height = await self._rpc_batch(
                [("getGenesisHash", []), ("getSlot", []), ("getBlockHeight", [])]
            )
        except (RpcError, RateLimitError) as exc:
            return ChainStatus(
                chain=self._config.id, configured=True, reachable=False, error=exc.message
            )

        if genesis is None or slot is None:
            return ChainStatus(
                chain=self._config.id,
                configured=True,
                reachable=False,
                error="The node did not report its genesis hash or current slot.",
            )

        if genesis != MAINNET_GENESIS:
            cluster = GENESIS_HASHES.get(genesis, "an unknown Solana cluster")
            return ChainStatus(
                chain=self._config.id,
                configured=True,
                reachable=False,
                slot=slot,
                error=f"RPC endpoint serves {cluster}, but {self._config.name} is mainnet.",
            )

        note = None
        if height is not None and height > slot:
            note = (
                f"Provider reported block height {height:,} above slot {slot:,}, which is "
                "impossible; the block height has been withheld."
            )
            height = None

        return ChainStatus(
            chain=self._config.id,
            configured=True,
            reachable=True,
            block_number=height,
            slot=slot,
            error=note,
        )


def _parse_token_account(entry: dict) -> tuple[str, str, int, int] | None:
    """Pull (mint, owner, amount, decimals) out of a jsonParsed token account.

    Returns None for anything not in the expected shape. The node falls back
    to raw base64 when it cannot parse an account, and one such account must
    not stop the rest of the holdings being reported.
    """
    try:
        info = entry["account"]["data"]["parsed"]["info"]
        token_amount = info["tokenAmount"]
        return info["mint"], info["owner"], int(token_amount["amount"]), int(token_amount["decimals"])
    except (KeyError, TypeError, ValueError):
        return None

