"""Token, price and portfolio endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.blockchain.adapters.evm import EvmAdapter
from app.blockchain.factory import get_adapter
from app.config import Settings, get_settings
from app.core.errors import ChainNotSupportedError
from app.market.service import MarketDataService, get_market_service
from app.market.types import Price
from app.services.portfolio import build_portfolio
from app.tokens.registry import all_coingecko_ids, list_tokens
from app.tokens.types import PortfolioSnapshot, TokenConfig

router = APIRouter(tags=["market"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
MarketDep = Annotated[MarketDataService, Depends(get_market_service)]


@router.get("/tokens/{chain}", response_model=list[TokenConfig])
async def get_tokens(
    chain: Annotated[str, Path(description="Chain key, e.g. 'ethereum'")],
) -> list[TokenConfig]:
    """Every token we track on a chain, with verified contract metadata."""
    return list_tokens(chain)


@router.get("/market/prices", response_model=dict[str, Price])
async def get_prices(
    market: MarketDep,
    ids: Annotated[
        str | None,
        Query(description="Comma-separated CoinGecko ids. Omit for everything we track."),
    ] = None,
) -> dict[str, Price]:
    """Current USD prices.

    An asset we could not price is simply absent from the response rather
    than being returned with a zero or a guessed value. Each entry carries
    its source and an `is_stale` flag.
    """
    wanted = [i.strip() for i in ids.split(",") if i.strip()] if ids else all_coingecko_ids()
    return await market.get_prices(wanted)


@router.get("/portfolio/{chain}/{address}", response_model=PortfolioSnapshot)
async def get_portfolio(
    chain: Annotated[str, Path(description="Chain key")],
    address: Annotated[str, Path(description="Public address. Never a private key.")],
    settings: SettingsDep,
    market: MarketDep,
    include_zero: Annotated[
        bool, Query(description="Include tokens with a zero balance")
    ] = False,
) -> PortfolioSnapshot:
    """Every tracked token held by an address on a chain, valued in USD.

    Balances come from the chain; prices come from the market layer. Where
    either is unavailable the holding is reported as unpriced or unavailable
    -- never zero-filled.
    """
    adapter = get_adapter(chain, settings)

    # Token reading is ERC-20 specific. Rather than let a Solana or Bitcoin
    # request fail with a confusing type error later, we refuse it here.
    if not isinstance(adapter, EvmAdapter):
        raise ChainNotSupportedError(
            f"Portfolio reading is not implemented for {chain} yet.",
            detail="Currently available for EVM chains.",
        )

    return await build_portfolio(
        chain=chain,
        address=address,
        adapter=adapter,
        market=market,
        include_zero_balances=include_zero,
    )
