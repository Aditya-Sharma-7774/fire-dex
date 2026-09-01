"""Portfolio assembly: chain balances joined with market prices.

This is the first place in the project where two independent data sources
are combined, so it is the first place the "never fabricate" rule needs
enforcing across a join.

The rule here: a balance we could not read, and a price we could not fetch,
are both reported as unknown. Neither is quietly replaced with zero. A
portfolio total is the sum of what we could actually price, and the response
says how many holdings that covers.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

from app.blockchain.adapters.evm import EvmAdapter, format_units
from app.core.logging import get_logger
from app.market.service import MarketDataService
from app.tokens.registry import list_tokens
from app.tokens.types import PortfolioSnapshot, TokenBalance

log = get_logger(__name__)


async def build_portfolio(
    chain: str,
    address: str,
    adapter: EvmAdapter,
    market: MarketDataService,
    *,
    include_zero_balances: bool = False,
) -> PortfolioSnapshot:
    """Read every tracked token for an address and value it in USD."""
    tokens = list_tokens(chain)
    checksummed = adapter.validate_address(address)
    needed_ids = sorted({t.coingecko_id for t in tokens if t.coingecko_id})

    # These three fetches are independent -- the native balance, the token
    # balances and the prices do not depend on each other. Awaiting them one
    # after another made a portfolio request take as long as all three
    # combined. Running them concurrently cuts it to the slowest single one.
    native, token_balances, prices = await asyncio.gather(
        adapter.get_native_balance(checksummed),
        adapter.get_token_balances(checksummed, tokens),
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
                raw=int(native.raw),
                price_usd=price.usd if price else None,
                change_24h=price.change_24h if price else None,
                price_is_stale=bool(price and price.is_stale),
            )
        )

    for entry in token_balances:
        if entry.raw is None:
            # Read failed. Surface it as an unknown holding rather than
            # dropping the token silently or calling it zero.
            balances.append(
                TokenBalance(
                    symbol=entry.token.symbol,
                    name=entry.token.name,
                    chain=chain,
                    address=entry.token.address,
                    decimals=entry.token.decimals,
                    is_native=False,
                    raw="unknown",
                    formatted="unavailable",
                )
            )
            continue

        if entry.raw == 0 and not include_zero_balances:
            continue

        price = prices.get(entry.token.coingecko_id or "")
        contains_stale = contains_stale or bool(price and price.is_stale)
        balances.append(
            _to_token_balance(
                symbol=entry.token.symbol,
                name=entry.token.name,
                chain=chain,
                address=entry.token.address,
                decimals=entry.token.decimals,
                is_native=False,
                raw=entry.raw,
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
        address=checksummed,
        balances=balances,
        # None, not 0.0, when nothing could be priced -- otherwise an empty
        # total is indistinguishable from a genuinely worthless portfolio.
        total_value_usd=round(sum(b.value_usd or 0 for b in priced), 2) if priced else None,
        priced_count=len(priced),
        unpriced_count=len(unpriced),
        fetched_at=datetime.now(timezone.utc),
        contains_stale_prices=contains_stale,
    )


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
        formatted=format_units(raw, decimals),
        price_usd=price_usd,
        value_usd=value_usd,
        change_24h=change_24h,
        price_is_stale=price_is_stale,
    )
