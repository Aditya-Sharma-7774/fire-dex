"""Portfolio assembly: chain balances joined with market prices.

This is the first place in the project where two independent data sources
are combined, so it is the first place the "never fabricate" rule needs
enforcing across a join.

The rule here: a balance we could not read, and a price we could not fetch,
are both reported as unknown. Neither is quietly replaced with zero. A
portfolio total is the sum of what we could actually price, and the response
says how many holdings that covers.

Only READING the holdings differs between chain families. EVM chains ask
each tracked token contract for a balance; Solana lists the owner's token
accounts directly; Bitcoin has only its native asset. Everything after that
-- pricing, valuing and totalling -- is shared, so the never-fabricate rule
is enforced once for every chain.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from app.blockchain.adapters.evm import format_units
from app.blockchain.registry import get_chain
from app.blockchain.types import ChainFamily
from app.core.logging import get_logger
from app.market.service import MarketDataService
from app.tokens.registry import list_tokens
from app.tokens.types import PortfolioSnapshot, TokenBalance, TokenConfig

log = get_logger(__name__)


async def build_portfolio(
    chain: str,
    address: str,
    adapter,
    market: MarketDataService,
    *,
    include_zero_balances: bool = False,
) -> PortfolioSnapshot:
    """Read every tracked token for an address and value it in USD."""
    tokens = list_tokens(chain)
    owner = adapter.validate_address(address)
    needed_ids = sorted({t.coingecko_id for t in tokens if t.coingecko_id})

    # The reads and the price lookup are independent. Awaiting them one after
    # another made a portfolio request take as long as all of them combined;
    # running them together cuts it to the slowest single one.
    (native_raw, token_rows, untracked), prices = await asyncio.gather(
        _read_holdings(get_chain(chain).family, adapter, owner, tokens),
        market.get_prices(needed_ids),
    )

    balances: list[TokenBalance] = []
    contains_stale = False

    # Native asset first -- it is the one the user is most likely to want.
    native_token = next((t for t in tokens if t.is_native), None)
    if native_token:
        price = prices.get(native_token.coingecko_id or "")
        contains_stale = contains_stale or bool(price and price.is_stale)
        balances.append(
            _to_token_balance(
                symbol=native_token.symbol,
                name=native_token.name,
                chain=chain,
                address=None,
                decimals=native_token.decimals,
                is_native=True,
                raw=native_raw,
                price_usd=price.usd if price else None,
                change_24h=price.change_24h if price else None,
                price_is_stale=bool(price and price.is_stale),
            )
        )

    for token, raw in token_rows:
        if raw is None:
            # Read failed. Surface it as an unknown holding rather than
            # dropping the token silently or calling it zero.
            balances.append(
                TokenBalance(
                    symbol=token.symbol,
                    name=token.name,
                    chain=chain,
                    address=token.address,
                    decimals=token.decimals,
                    is_native=False,
                    raw="unknown",
                    formatted="unavailable",
                )
            )
            continue

        if raw == 0 and not include_zero_balances:
            continue

        price = prices.get(token.coingecko_id or "")
        contains_stale = contains_stale or bool(price and price.is_stale)
        balances.append(
            _to_token_balance(
                symbol=token.symbol,
                name=token.name,
                chain=chain,
                address=token.address,
                decimals=token.decimals,
                is_native=False,
                raw=raw,
                price_usd=price.usd if price else None,
                change_24h=price.change_24h if price else None,
                price_is_stale=bool(price and price.is_stale),
            )
        )

    # --- totals ---------------------------------------------------
    priced = [b for b in balances if b.value_usd is not None]
    unpriced = [b for b in balances if b.value_usd is None]

    balances.sort(key=lambda b: (b.value_usd is None, -(b.value_usd or 0)))

    return PortfolioSnapshot(
        chain=chain,
        address=owner,
        balances=balances,
        # None, not 0.0, when nothing could be priced -- otherwise an empty
        # total is indistinguishable from a genuinely worthless portfolio.
        total_value_usd=round(sum(b.value_usd or 0 for b in priced), 2) if priced else None,
        priced_count=len(priced),
        unpriced_count=len(unpriced),
        fetched_at=datetime.now(timezone.utc),
        contains_stale_prices=contains_stale,
        untracked_tokens=untracked,
    )


async def _read_holdings(
    family: ChainFamily, adapter, owner: str, tokens: list[TokenConfig]
) -> tuple[int, list[tuple[TokenConfig, int | None]], int]:
    """(native balance, tracked token rows, count of untracked tokens held).

    A row's balance is None when it could not be read -- distinct from zero.
    """
    if family is ChainFamily.EVM:
        native, rows = await asyncio.gather(
            adapter.get_native_balance(owner), adapter.get_token_balances(owner, tokens)
        )
        return int(native.raw), [(row.token, row.raw) for row in rows], 0

    if family is ChainFamily.SOLANA:
        native, holdings = await asyncio.gather(
            adapter.get_native_balance(owner),
            # Named mints sort first, so every tracked token is within any
            # limit; the high one only stops a spam-heavy wallet truncating
            # the count of untracked tokens.
            adapter.get_token_balances(owner, limit=10_000),
        )
        held = {balance.mint: int(balance.raw) for balance in holdings.tokens}
        tracked = [token for token in tokens if token.address]
        # When a token program could not be read, a tracked mint that did not
        # appear is unknown rather than zero: it may live in the program that
        # failed.
        missing = None if holdings.incomplete else 0
        rows = [(token, held.get(token.address, missing)) for token in tracked]
        tracked_mints = {token.address for token in tracked}
        return int(native.raw), rows, sum(1 for mint in held if mint not in tracked_mints)

    # Bitcoin, and any family with only a native asset.
    native = await adapter.get_native_balance(owner)
    return int(native.raw), [], 0


def _to_token_balance(
    *,
    symbol: str,
    name: str,
    chain: str,
    address: str | None,
    decimals: int,
    is_native: bool,
    raw: int,
    price_usd: float | None,
    change_24h: float | None,
    price_is_stale: bool,
) -> TokenBalance:
    """Build one priced balance row.

    The USD value is computed with Decimal, not float. A token amount times
    a price is exactly the kind of arithmetic where binary floating point
    accumulates visible error.
    """
    value_usd: float | None = None
    if price_usd is not None:
        amount = Decimal(raw) / (Decimal(10) ** decimals)
        value_usd = float(round(amount * Decimal(str(price_usd)), 2))

    return TokenBalance(
        symbol=symbol,
        name=name,
        chain=chain,
        address=address,
        decimals=decimals,
        is_native=is_native,
        raw=str(raw),
        formatted=format_units(raw, decimals, precision=min(decimals, 8)),
        price_usd=price_usd,
        value_usd=value_usd,
        change_24h=change_24h,
        price_is_stale=price_is_stale,
    )
