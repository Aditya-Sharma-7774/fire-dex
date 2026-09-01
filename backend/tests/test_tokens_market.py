"""Tests for the token registry, market data layer and portfolio assembly.

The theme running through these: unknown must never become zero. A balance
we could not read, and a price we could not fetch, are both reported as
unknown. Silently substituting zero would understate someone's holdings.
"""

import os

import httpx
import pytest
import respx

from app.blockchain.adapters.evm import EvmAdapter, RawTokenBalance
from app.blockchain.registry import get_chain
from app.market.cache import TtlCache
from app.market.providers import CoinGeckoProvider
from app.market.service import MarketDataService
from app.market.types import Price
from app.services.portfolio import build_portfolio
from app.tokens.registry import ETHEREUM_TOKENS, all_coingecko_ids, get_token, list_tokens

RPC_URL = "https://rpc.example.test"
SAMPLE_ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"


# ---------------------------------------------------------------------
# Token registry
# ---------------------------------------------------------------------


def test_every_erc20_has_an_address_and_native_does_not() -> None:
    for token in ETHEREUM_TOKENS:
        if token.is_native:
            assert token.address is None, f"{token.symbol} is native but has an address"
        else:
            assert token.address, f"{token.symbol} is an ERC-20 with no address"


def test_addresses_are_well_formed_and_unique() -> None:
    """A duplicated address would mean two rows reading the same contract."""
    addresses = [t.address.lower() for t in ETHEREUM_TOKENS if t.address]

    for address in addresses:
        assert address.startswith("0x") and len(address) == 42

    assert len(addresses) == len(set(addresses))


def test_stablecoin_decimals_are_six_not_eighteen() -> None:
    """USDT and USDC use 6 decimals.

    Assuming 18 for every ERC-20 is a common and severe bug: it would
    misreport these balances by a factor of 10^12. Verified on-chain.
    """
    assert get_token("ethereum", "USDT").decimals == 6
    assert get_token("ethereum", "USDC").decimals == 6
    assert get_token("ethereum", "WBTC").decimals == 8
    assert get_token("ethereum", "DAI").decimals == 18


def test_sepolia_does_not_reuse_mainnet_token_addresses() -> None:
    """The same address on a testnet is a different contract, or nothing."""
    mainnet = {t.address for t in list_tokens("ethereum") if t.address}
    sepolia = {t.address for t in list_tokens("sepolia") if t.address}

    assert not (mainnet & sepolia)


def test_coingecko_ids_are_deduplicated() -> None:
    """ETH appears on two chains but is one price lookup."""
    ids = all_coingecko_ids()
    assert len(ids) == len(set(ids))
    assert "ethereum" in ids


def test_unknown_token_returns_none() -> None:
    assert get_token("ethereum", "NOTATOKEN") is None


# ---------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------


def test_cache_returns_fresh_value_then_expires() -> None:
    cache: TtlCache[str] = TtlCache(default_ttl_seconds=0.05)
    cache.set("k", "v")

    assert cache.get_fresh("k") == "v"

    import time

    time.sleep(0.08)
    assert cache.get_fresh("k") is None


def test_expired_value_is_kept_for_stale_fallback() -> None:
    """The whole point of the cache: an old value beats a blank screen,
    but only when it can be labelled as old."""
    cache: TtlCache[str] = TtlCache(default_ttl_seconds=0.01)
    cache.set("k", "v")

    import time

    time.sleep(0.03)

    assert cache.get_fresh("k") is None
    stale = cache.get_stale("k")
    assert stale is not None
    value, age = stale
    assert value == "v" and age > 0


# ---------------------------------------------------------------------
# Market service: fallback and staleness
# ---------------------------------------------------------------------


class _StubProvider:
    def __init__(self, name: str, prices: dict[str, Price] | None = None, fail: bool = False):
        self._name = name
        self._prices = prices or {}
        self._fail = fail
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    async def get_prices(self, coingecko_ids):
        self.calls += 1
        if self._fail:
            raise RuntimeError(f"{self._name} is down")
        return {k: v for k, v in self._prices.items() if k in coingecko_ids}


def _price(coin_id: str, usd: float, source: str = "test") -> Price:
    from datetime import datetime, timezone

    return Price(
        coingecko_id=coin_id,
        symbol=coin_id,
        usd=usd,
        fetched_at=datetime.now(timezone.utc),
        source=source,
    )


async def test_primary_provider_is_used_when_healthy() -> None:
    primary = _StubProvider("primary", {"ethereum": _price("ethereum", 2000)})
    fallback = _StubProvider("fallback", {"ethereum": _price("ethereum", 1)})
    service = MarketDataService(primary=primary, fallback=fallback)

    prices = await service.get_prices(["ethereum"])

    assert prices["ethereum"].usd == 2000
    assert fallback.calls == 0


async def test_falls_back_when_primary_fails() -> None:
    primary = _StubProvider("primary", fail=True)
    fallback = _StubProvider("fallback", {"ethereum": _price("ethereum", 1999)})
    service = MarketDataService(primary=primary, fallback=fallback)

    prices = await service.get_prices(["ethereum"])

    assert prices["ethereum"].usd == 1999
    assert fallback.calls == 1


async def test_cache_prevents_a_second_provider_call() -> None:
    """Directly protects the rate limit we actually hit during development."""
    primary = _StubProvider("primary", {"ethereum": _price("ethereum", 2000)})
    service = MarketDataService(primary=primary, fallback=_StubProvider("fallback"))

    await service.get_prices(["ethereum"])
    await service.get_prices(["ethereum"])

    assert primary.calls == 1


async def test_stale_price_is_served_but_flagged() -> None:
    """When every provider fails we may show the last known price -- but it
    must be marked, never presented as current."""
    cache: TtlCache[Price] = TtlCache(default_ttl_seconds=0.01)
    primary = _StubProvider("primary", {"ethereum": _price("ethereum", 2000)})
    service = MarketDataService(primary=primary, fallback=_StubProvider("fallback"), cache=cache)

    await service.get_prices(["ethereum"])  # populate

    import time

    time.sleep(0.03)

    broken = MarketDataService(
        primary=_StubProvider("primary", fail=True),
        fallback=_StubProvider("fallback", fail=True),
        cache=cache,
    )
    prices = await broken.get_prices(["ethereum"])

    assert prices["ethereum"].usd == 2000
    assert prices["ethereum"].is_stale is True


async def test_unknown_asset_is_absent_not_zero() -> None:
    """An unpriceable asset must not come back priced at zero."""
    service = MarketDataService(
        primary=_StubProvider("primary"), fallback=_StubProvider("fallback")
    )

    prices = await service.get_prices(["nonexistent-coin"])

    assert "nonexistent-coin" not in prices


@respx.mock
async def test_coingecko_rate_limit_raises_rate_limit_error() -> None:
    from app.core.errors import RateLimitError

    respx.get(url__startswith=CoinGeckoProvider.BASE_URL).mock(
        return_value=httpx.Response(429, text="rate limited")
    )

    with pytest.raises(RateLimitError):
        await CoinGeckoProvider().get_prices(["ethereum"])


@respx.mock
async def test_coingecko_skips_entries_with_no_price() -> None:
    respx.get(url__startswith=CoinGeckoProvider.BASE_URL).mock(
        return_value=httpx.Response(
            200, json={"ethereum": {"usd": 2000.0}, "broken-coin": {"usd_market_cap": 5}}
        )
    )

    prices = await CoinGeckoProvider().get_prices(["ethereum", "broken-coin"])

    assert "ethereum" in prices
    assert "broken-coin" not in prices


# ---------------------------------------------------------------------
# ERC-20 balance reading
# ---------------------------------------------------------------------


def _adapter(chain: str = "ethereum") -> EvmAdapter:
    return EvmAdapter(config=get_chain(chain), rpc_url=RPC_URL)


@respx.mock
async def test_token_balances_are_read_in_one_batched_request() -> None:
    """Ten tokens must cost one HTTP request, not ten."""
    route = respx.post(RPC_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"jsonrpc": "2.0", "id": i, "result": hex(1_000_000)}
                for i in range(len([t for t in ETHEREUM_TOKENS if not t.is_native]))
            ],
        )
    )

    balances = await _adapter().get_token_balances(SAMPLE_ADDRESS, ETHEREUM_TOKENS)

    assert route.call_count == 1
    assert len(balances) == len([t for t in ETHEREUM_TOKENS if not t.is_native])


@respx.mock
async def test_one_failing_token_does_not_discard_the_others() -> None:
    """A single bad contract must not wipe out the whole portfolio read."""
    respx.post(RPC_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"jsonrpc": "2.0", "id": 0, "result": hex(5_000_000)},
                {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "reverted"}},
                *[
                    {"jsonrpc": "2.0", "id": i, "result": hex(0)}
                    for i in range(2, len([t for t in ETHEREUM_TOKENS if not t.is_native]))
                ],
            ],
        )
    )

    balances = await _adapter().get_token_balances(SAMPLE_ADDRESS, ETHEREUM_TOKENS)

    assert balances[0].raw == 5_000_000
    # The failed one is None -- unknown, explicitly not zero.
    assert balances[1].raw is None
    assert balances[2].raw == 0


@respx.mock
async def test_repeated_reads_are_served_from_cache() -> None:
    """A second identical read must not hit the node again.

    Without this, every poll from every open browser tab became a request to
    a shared public node. We measured a portfolio request degrading from 8
    seconds to 48 seconds and then failing outright under that load.
    """
    route = respx.post(RPC_URL).mock(return_value=httpx.Response(200, json={"result": "0x10"}))
    adapter = _adapter()

    await adapter.get_native_balance(SAMPLE_ADDRESS)
    await adapter.get_native_balance(SAMPLE_ADDRESS)
    await adapter.get_native_balance(SAMPLE_ADDRESS)

    assert route.call_count == 1


@respx.mock
async def test_batched_token_reads_are_cached_as_a_unit() -> None:
    payload = [
        {"jsonrpc": "2.0", "id": i, "result": hex(1000)}
        for i in range(len([t for t in ETHEREUM_TOKENS if not t.is_native]))
    ]
    route = respx.post(RPC_URL).mock(return_value=httpx.Response(200, json=payload))
    adapter = _adapter()

    first = await adapter.get_token_balances(SAMPLE_ADDRESS, ETHEREUM_TOKENS)
    second = await adapter.get_token_balances(SAMPLE_ADDRESS, ETHEREUM_TOKENS)

    assert route.call_count == 1
    assert [b.raw for b in first] == [b.raw for b in second]


@respx.mock
async def test_different_addresses_do_not_share_a_cache_entry() -> None:
    """Cache keys must include the address, or one user sees another's balance.

    This is the failure mode that makes naive caching dangerous in a wallet.
    """
    other = "0xAb5801a7D398351b8bE11C439e05C5B3259aec9B"
    route = respx.post(RPC_URL).mock(return_value=httpx.Response(200, json={"result": "0x10"}))
    adapter = _adapter()

    await adapter.get_native_balance(SAMPLE_ADDRESS)
    await adapter.get_native_balance(other)

    assert route.call_count == 2


async def test_native_only_chain_needs_no_rpc_call() -> None:
    """Sepolia tracks only the native asset, so there is nothing to batch."""
    balances = await _adapter("sepolia").get_token_balances(
        SAMPLE_ADDRESS, list_tokens("sepolia")
    )
    assert balances == []


# ---------------------------------------------------------------------
# Portfolio assembly
# ---------------------------------------------------------------------


class _StubAdapter:
    """Minimal adapter stand-in for portfolio tests."""

    def __init__(self, native_wei: int, token_raw: dict[str, int | None]):
        self._native_wei = native_wei
        self._token_raw = token_raw

    def validate_address(self, address: str) -> str:
        return address

    async def get_native_balance(self, address: str):
        from datetime import datetime, timezone

        from app.blockchain.types import NativeBalance

        return NativeBalance(
            chain="ethereum",
            address=address,
            symbol="ETH",
            decimals=18,
            raw=str(self._native_wei),
            formatted="1",
            fetched_at=datetime.now(timezone.utc),
        )

    async def get_token_balances(self, address, tokens):
        return [
            RawTokenBalance(token=t, raw=self._token_raw.get(t.symbol, 0))
            for t in tokens
            if not t.is_native
        ]


async def test_portfolio_values_holdings_in_usd() -> None:
    adapter = _StubAdapter(native_wei=2 * 10**18, token_raw={"USDT": 100_000_000})
    market = MarketDataService(
        primary=_StubProvider(
            "p", {"ethereum": _price("ethereum", 2000.0), "tether": _price("tether", 1.0)}
        ),
        fallback=_StubProvider("f"),
    )

    snapshot = await build_portfolio("ethereum", SAMPLE_ADDRESS, adapter, market)  # type: ignore[arg-type]

    eth = next(b for b in snapshot.balances if b.symbol == "ETH")
    usdt = next(b for b in snapshot.balances if b.symbol == "USDT")

    assert eth.value_usd == 4000.0
    # 100_000_000 raw at 6 decimals = 100 USDT, not 100_000_000.
    assert usdt.formatted == "100"
    assert usdt.value_usd == 100.0
    assert snapshot.total_value_usd == 4100.0


async def test_unpriced_holding_is_counted_not_zeroed() -> None:
    """A token we cannot price must not silently contribute zero."""
    adapter = _StubAdapter(native_wei=10**18, token_raw={"PEPE": 10**20})
    market = MarketDataService(
        primary=_StubProvider("p", {"ethereum": _price("ethereum", 2000.0)}),
        fallback=_StubProvider("f"),
    )

    snapshot = await build_portfolio("ethereum", SAMPLE_ADDRESS, adapter, market)  # type: ignore[arg-type]

    pepe = next(b for b in snapshot.balances if b.symbol == "PEPE")
    assert pepe.value_usd is None
    assert pepe.price_usd is None
    assert snapshot.unpriced_count >= 1


async def test_unreadable_balance_is_reported_as_unavailable() -> None:
    adapter = _StubAdapter(native_wei=10**18, token_raw={"USDT": None})
    market = MarketDataService(
        primary=_StubProvider("p", {"ethereum": _price("ethereum", 2000.0)}),
        fallback=_StubProvider("f"),
    )

    snapshot = await build_portfolio("ethereum", SAMPLE_ADDRESS, adapter, market)  # type: ignore[arg-type]

    usdt = next(b for b in snapshot.balances if b.symbol == "USDT")
    assert usdt.raw == "unknown"
    assert usdt.formatted == "unavailable"


async def test_total_is_none_when_nothing_can_be_priced() -> None:
    """None and 0.0 mean different things: 'unknown' vs 'worthless'."""
    adapter = _StubAdapter(native_wei=10**18, token_raw={})
    market = MarketDataService(primary=_StubProvider("p"), fallback=_StubProvider("f"))

    snapshot = await build_portfolio("ethereum", SAMPLE_ADDRESS, adapter, market)  # type: ignore[arg-type]

    assert snapshot.total_value_usd is None
    assert snapshot.priced_count == 0


async def test_zero_balances_are_excluded_by_default() -> None:
    adapter = _StubAdapter(native_wei=10**18, token_raw={"USDT": 0, "LINK": 5 * 10**18})
    market = MarketDataService(
        primary=_StubProvider(
            "p", {"ethereum": _price("ethereum", 2000.0), "chainlink": _price("chainlink", 10.0)}
        ),
        fallback=_StubProvider("f"),
    )

    snapshot = await build_portfolio("ethereum", SAMPLE_ADDRESS, adapter, market)  # type: ignore[arg-type]
    symbols = {b.symbol for b in snapshot.balances}

    assert "USDT" not in symbols
    assert "LINK" in symbols


async def test_balances_are_sorted_by_value_with_unpriced_last() -> None:
    adapter = _StubAdapter(
        native_wei=10**18, token_raw={"LINK": 5 * 10**18, "PEPE": 10**20}
    )
    market = MarketDataService(
        primary=_StubProvider(
            "p", {"ethereum": _price("ethereum", 2000.0), "chainlink": _price("chainlink", 10.0)}
        ),
        fallback=_StubProvider("f"),
    )

    snapshot = await build_portfolio("ethereum", SAMPLE_ADDRESS, adapter, market)  # type: ignore[arg-type]

    values = [b.value_usd for b in snapshot.balances]
    priced = [v for v in values if v is not None]
    assert priced == sorted(priced, reverse=True)
    assert values[-1] is None  # unpriced sinks to the bottom


# ---------------------------------------------------------------------
# Live verification (opt-in)
# ---------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("FIREDEX_LIVE_TESTS") != "1",
    reason="Set FIREDEX_LIVE_TESTS=1 to verify token addresses against the real chain",
)
async def test_live_token_addresses_match_the_chain() -> None:
    """Re-verify every registry address by calling the contract itself.

    This is how the addresses were obtained in the first place: taken from
    CoinGecko, then confirmed on-chain. Opt-in because it needs network
    access and consumes public RPC quota.
    """
    from app.blockchain.adapters.evm import ERC20_BALANCE_OF_SELECTOR  # noqa: F401

    adapter = EvmAdapter(
        config=get_chain("ethereum"), rpc_url="https://ethereum-rpc.publicnode.com"
    )

    for token in ETHEREUM_TOKENS:
        if token.is_native or not token.address:
            continue

        decimals_hex = await adapter._rpc_call(
            "eth_call", [{"to": token.address, "data": "0x313ce567"}, "latest"]
        )
        assert int(decimals_hex, 16) == token.decimals, (
            f"{token.symbol}: registry says {token.decimals} decimals, "
            f"chain says {int(decimals_hex, 16)}"
        )
