"""Tests for Bitcoin, BNB Smart Chain and Solana support.

Real addresses throughout were taken from live mainnet data: the Bitcoin
ones are outputs from a recent block, one of every format. Secret-shaped
inputs are constructed here and belong to nobody.
"""

import hashlib
import os
from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.blockchain.adapters.bitcoin import MAINNET_GENESIS, BitcoinAdapter
from app.blockchain.adapters.solana import SplTokenBalance, SplTokenHoldings
from app.blockchain.encoding import (
    BASE58_ALPHABET,
    BECH32_CHARSET,
    BECH32_CONST,
    BECH32M_CONST,
    _hrp_expand,
    _polymod,
    b58check_decode,
    decode_segwit,
)
from app.blockchain.registry import get_chain
from app.blockchain.types import ChainStatus, NativeBalance
from app.core.errors import InvalidAddressError, RpcError
from app.evidence.collectors import collect_chain_evidence, collect_portfolio_evidence
from app.market.candles import PROXY_SYMBOLS, SYMBOL_TO_BINANCE_PAIR
from app.market.service import MarketDataService
from app.market.types import Price
from app.services.portfolio import build_portfolio
from app.tokens.registry import TOKENS_BY_CHAIN, find_asset, get_token

BITCOIN = {
    "p2pkh": "1JbMa6P5q9DjPJ7zYDP554WiMLTmTohu9Y",
    "p2sh": "35GYekpvL9YH5xxj3bneNuCXxzRMkt3Ye9",
    "p2wpkh": "bc1qdllzjxkykyk7mmm698lnsh4378xj62fthqex3q",
    "p2wsh": "bc1qwqdg6squsna38e46795at95yu9atm8azzmyvckulcc7kytlcckxswvvzej",
    "p2tr": "bc1p64gwv9c32f9ghl7p4dy5x4xurrrll3rs8ykg840pzt5tu83jgyestd2w8z",
}
SOLANA_WALLET = "8p4jRpgGUt1PFcgrbCbd11DAVXiRpwxiK47gPLbpomaq"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
API_A = "https://esplora-a.test/api"
API_B = "https://esplora-b.test/api"


# ---------------------------------------------------------------------
# Encoders, used only to construct inputs of an exact shape
# ---------------------------------------------------------------------


def b58encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    out = ""
    while number:
        number, remainder = divmod(number, 58)
        out = BASE58_ALPHABET[remainder] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\x00"))) + out


def b58check_encode(version: int, payload: bytes) -> str:
    body = bytes([version]) + payload
    return b58encode(body + hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4])


def segwit_encode(hrp: str, version: int, program: bytes, constant: int) -> str:
    accumulator, bits, data = 0, 0, []
    for byte in program:
        accumulator = (accumulator << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            data.append((accumulator >> bits) & 31)
    if bits:
        data.append((accumulator << (5 - bits)) & 31)
    values = [version] + data
    polymod = _polymod(_hrp_expand(hrp) + values + [0] * 6) ^ constant
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(BECH32_CHARSET[d] for d in values + checksum)


def bitcoin(api_urls=(API_A,)) -> BitcoinAdapter:
    return BitcoinAdapter(config=get_chain("bitcoin"), api_urls=list(api_urls))


# ---------------------------------------------------------------------
# Encodings
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "version", "length"),
    [("p2wpkh", 0, 20), ("p2wsh", 0, 32), ("p2tr", 1, 32)],
)
def test_real_segwit_addresses_decode_to_the_right_program(kind, version, length):
    hrp, got_version, program = decode_segwit(BITCOIN[kind])
    assert (hrp, got_version, len(program)) == ("bc", version, length)


def test_the_bip173_published_vector_decodes():
    _, version, program = decode_segwit("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4")
    assert (version, len(program)) == (0, 20)


def test_taproot_with_the_old_checksum_variant_is_rejected():
    """The exact flaw BIP-350 closed: version 1 must use bech32m."""
    program = os.urandom(32)
    assert decode_segwit(segwit_encode("bc", 1, program, BECH32M_CONST))[1] == 1
    with pytest.raises(ValueError, match="checksum variant"):
        decode_segwit(segwit_encode("bc", 1, program, BECH32_CONST))


def test_every_single_character_typo_is_caught():
    address = BITCOIN["p2wpkh"]
    for index in range(4, len(address)):
        swapped = next(c for c in BECH32_CHARSET if c != address[index])
        with pytest.raises(ValueError):
            decode_segwit(address[:index] + swapped + address[index + 1 :])


def test_base58check_detects_a_changed_character():
    address = BITCOIN["p2pkh"]
    assert b58check_decode(address)[0] == 0x00
    with pytest.raises(ValueError, match="checksum"):
        b58check_decode(address[:-1] + ("2" if address[-1] != "2" else "3"))


# ---------------------------------------------------------------------
# Bitcoin address validation
# ---------------------------------------------------------------------


@pytest.mark.parametrize("kind", list(BITCOIN))
def test_every_real_address_format_is_accepted(kind):
    address = BITCOIN[kind]
    expected = address.lower() if address.startswith("bc1") else address
    assert bitcoin().validate_address(address) == expected


def test_bech32_is_returned_in_canonical_lower_case():
    assert bitcoin().validate_address(BITCOIN["p2wpkh"].upper()) == BITCOIN["p2wpkh"]


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("p2pkh", "Legacy (P2PKH)"),
        ("p2sh", "Script (P2SH)"),
        ("p2wpkh", "Native SegWit (P2WPKH)"),
        ("p2wsh", "SegWit script (P2WSH)"),
        ("p2tr", "Taproot (P2TR)"),
    ],
)
def test_address_types_are_named(kind, expected):
    assert bitcoin().address_type(BITCOIN[kind]) == expected


def test_a_wif_private_key_is_refused_even_though_its_checksum_is_valid():
    """WIF is valid base58check. A checksum test alone would accept it."""
    wif = b58check_encode(0x80, os.urandom(32) + b"\x01")
    assert b58check_decode(wif)[0] == 0x80

    with pytest.raises(InvalidAddressError) as caught:
        bitcoin().validate_address(wif)
    assert "PRIVATE KEY" in caught.value.message
    assert wif not in caught.value.message + (caught.value.detail or "")


@pytest.mark.parametrize(
    ("value", "phrase"),
    [
        (os.urandom(32).hex(), "PRIVATE KEY"),
        ("xprv" + "9" * 107, "extended PRIVATE key"),
        ("xpub" + "6" * 107, "extended public key"),
        ("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045", "not a Bitcoin address"),
        ("1" * 500, "not a Bitcoin address"),
    ],
    ids=["hex-key", "xprv", "xpub", "ethereum", "oversized"],
)
def test_wrong_kinds_of_input_are_refused_with_a_reason(value, phrase):
    with pytest.raises(InvalidAddressError) as caught:
        bitcoin().validate_address(value)
    assert phrase in caught.value.message


def test_testnet_addresses_are_refused_as_the_wrong_network():
    legacy = b58check_encode(0x6F, os.urandom(20))
    segwit = segwit_encode("tb", 0, os.urandom(20), BECH32_CONST)
    for address in (legacy, segwit):
        with pytest.raises(InvalidAddressError, match="testnet"):
            bitcoin().validate_address(address)


def test_a_typo_is_caught_rather_than_read_as_another_address():
    address = BITCOIN["p2pkh"]
    typo = address[:-1] + ("2" if address[-1] != "2" else "3")
    with pytest.raises(InvalidAddressError) as caught:
        bitcoin().validate_address(typo)
    assert "checksum" in (caught.value.detail or "")


# ---------------------------------------------------------------------
# Bitcoin reads
# ---------------------------------------------------------------------


def esplora_address(funded: int, spent: int) -> dict:
    return {
        "address": BITCOIN["p2wpkh"],
        "chain_stats": {"funded_txo_sum": funded, "spent_txo_sum": spent, "tx_count": 3},
        "mempool_stats": {"funded_txo_sum": 999_999, "spent_txo_sum": 0},
    }


async def test_balance_is_received_minus_spent_and_ignores_unconfirmed():
    respx.get(f"{API_A}/address/{BITCOIN['p2wpkh']}").mock(
        return_value=httpx.Response(200, json=esplora_address(150_000_000, 25_000_001))
    )
    balance = await bitcoin().get_native_balance(BITCOIN["p2wpkh"])

    assert balance.raw == "124999999"
    assert balance.formatted == "1.24999999", "all eight decimal places must survive"
    assert balance.symbol == "BTC"


async def test_a_failed_provider_falls_back_to_the_second():
    respx.get(f"{API_A}/address/{BITCOIN['p2tr']}").mock(return_value=httpx.Response(503))
    respx.get(f"{API_B}/address/{BITCOIN['p2tr']}").mock(
        return_value=httpx.Response(200, json=esplora_address(5_000, 0))
    )
    balance = await bitcoin((API_A, API_B)).get_native_balance(BITCOIN["p2tr"])
    assert balance.raw == "5000"


async def test_an_impossible_balance_is_refused():
    respx.get(f"{API_A}/address/{BITCOIN['p2sh']}").mock(
        return_value=httpx.Response(200, json=esplora_address(100, 200))
    )
    with pytest.raises(RpcError, match="impossible"):
        await bitcoin().get_native_balance(BITCOIN["p2sh"])


async def test_status_confirms_mainnet_by_its_genesis_block():
    respx.get(f"{API_A}/block-height/0").mock(return_value=httpx.Response(200, text=MAINNET_GENESIS))
    respx.get(f"{API_A}/blocks/tip/height").mock(return_value=httpx.Response(200, text="971047"))
    status = await bitcoin().get_status()
    assert (status.reachable, status.block_number) == (True, 971047)


async def test_a_testnet_service_is_caught():
    respx.get(f"{API_A}/block-height/0").mock(return_value=httpx.Response(200, text="00" * 32))
    respx.get(f"{API_A}/blocks/tip/height").mock(return_value=httpx.Response(200, text="5"))
    status = await bitcoin().get_status()
    assert status.reachable is False
    assert "different network" in status.error


# ---------------------------------------------------------------------
# Token registry
# ---------------------------------------------------------------------


def test_the_same_asset_has_different_decimals_on_different_chains():
    """The reason decimals are read from each chain, never reused."""
    assert get_token("ethereum", "USDT").decimals == 6
    assert get_token("bsc", "USDT").decimals == 18
    assert get_token("solana", "USDT").decimals == 6
    assert get_token("ethereum", "WBTC").decimals == 8
    assert get_token("bsc", "BTCB").decimals == 18
    assert get_token("solana", "BONK").decimals == 5


def test_every_chain_has_exactly_one_native_asset():
    for chain, tokens in TOKENS_BY_CHAIN.items():
        assert sum(1 for t in tokens if t.is_native) == 1, chain


def test_no_contract_address_appears_twice_on_one_chain():
    for chain, tokens in TOKENS_BY_CHAIN.items():
        addresses = [t.address for t in tokens if t.address]
        assert len(addresses) == len(set(addresses)), chain


def test_every_token_can_be_priced():
    for tokens in TOKENS_BY_CHAIN.values():
        assert all(t.coingecko_id for t in tokens)


@pytest.mark.parametrize(
    ("symbol", "chain", "price_id"),
    [
        ("ETH", "ethereum", "ethereum"),
        ("USDT", "ethereum", "tether"),
        ("BTC", "bitcoin", "bitcoin"),
        ("SOL", "solana", "solana"),
        ("BNB", "bsc", "binancecoin"),
        ("JUP", "solana", "jupiter-exchange-solana"),
        ("cake", "bsc", "pancakeswap-token"),
    ],
)
def test_asset_lookup_prefers_the_native_and_canonical_token(symbol, chain, price_id):
    """"ETH" is Ether, not the Binance-Peg copy; "USDT" is Tether, not the bridged one."""
    token = find_asset(symbol)
    assert (token.chain, token.coingecko_id) == (chain, price_id)


def test_an_unknown_symbol_is_not_guessed():
    assert find_asset("NOTACOIN") is None


def test_wrapped_assets_use_their_underlying_chart_as_a_labelled_proxy():
    for wrapped, underlying in (("BTCB", "BTC"), ("WBNB", "BNB"), ("WSOL", "SOL")):
        assert SYMBOL_TO_BINANCE_PAIR[wrapped] == SYMBOL_TO_BINANCE_PAIR[underlying]
        assert PROXY_SYMBOLS[wrapped] == underlying


def test_assets_with_no_live_pair_get_no_chart_rather_than_a_wrong_one():
    assert "MSOL" not in SYMBOL_TO_BINANCE_PAIR
    assert "DAI" not in SYMBOL_TO_BINANCE_PAIR


# ---------------------------------------------------------------------
# Portfolios on the new chains
# ---------------------------------------------------------------------


class _Prices:
    name = "stub"

    def __init__(self, prices: dict[str, float]):
        self._prices = prices

    async def get_prices(self, ids):
        now = datetime.now(timezone.utc)
        return {
            i: Price(coingecko_id=i, symbol=i, usd=self._prices[i], fetched_at=now, source="stub")
            for i in ids
            if i in self._prices
        }


def market(prices: dict[str, float]) -> MarketDataService:
    return MarketDataService(primary=_Prices(prices), fallback=_Prices({}))


def native(chain: str, raw: int) -> NativeBalance:
    config = get_chain(chain)
    return NativeBalance(
        chain=chain, address="x", symbol=config.native_symbol, decimals=config.native_decimals,
        raw=str(raw), formatted="", fetched_at=datetime.now(timezone.utc),
    )


class _SolanaStub:
    def __init__(self, held: dict[str, int], untracked: int = 0, incomplete: bool = False):
        self._held, self._untracked, self._incomplete = held, untracked, incomplete

    def validate_address(self, address):
        return address

    async def get_native_balance(self, address):
        return native("solana", 2_000_000_000)

    async def get_token_balances(self, address, *, limit=50, include_zero=False):
        tokens = [
            SplTokenBalance(mint=mint, symbol=None, raw=str(raw), decimals=6, formatted="",
                            accounts=1, program="token")
            for mint, raw in self._held.items()
        ] + [
            SplTokenBalance(mint=f"spam{i}", symbol=None, raw="1", decimals=0, formatted="",
                            accounts=1, program="token-2022")
            for i in range(self._untracked)
        ]
        return SplTokenHoldings(
            chain="solana", owner=address, owner_is_wallet=True, tokens=tokens,
            total_mints=len(tokens), total_accounts=len(tokens), truncated=False,
            incomplete=self._incomplete, failed_programs=["token-2022"] if self._incomplete else [],
            fetched_at=datetime.now(timezone.utc),
        )


async def test_a_solana_portfolio_values_sol_and_tracked_tokens():
    adapter = _SolanaStub({USDC_MINT: 25_000_000})
    snapshot = await build_portfolio(
        "solana", SOLANA_WALLET, adapter, market({"solana": 100.0, "usd-coin": 1.0})
    )
    by_symbol = {b.symbol: b for b in snapshot.balances}
    assert by_symbol["SOL"].value_usd == 200.0
    assert by_symbol["USDC"].value_usd == 25.0
    assert snapshot.total_value_usd == 225.0


async def test_untracked_solana_tokens_are_counted_not_listed():
    """Most unrequested tokens on Solana are spam; they are reported, not shown."""
    snapshot = await build_portfolio(
        "solana", SOLANA_WALLET, _SolanaStub({}, untracked=37), market({"solana": 100.0})
    )
    assert snapshot.untracked_tokens == 37
    assert all(not b.symbol.startswith("spam") for b in snapshot.balances)


async def test_a_failed_token_program_makes_missing_tokens_unknown_not_zero():
    snapshot = await build_portfolio(
        "solana", SOLANA_WALLET, _SolanaStub({}, incomplete=True), market({"solana": 100.0}),
        include_zero_balances=True,
    )
    usdc = next(b for b in snapshot.balances if b.symbol == "USDC")
    assert usdc.formatted == "unavailable"


class _BitcoinStub:
    def validate_address(self, address):
        return address

    async def get_native_balance(self, address):
        return native("bitcoin", 1_234)


async def test_a_bitcoin_portfolio_keeps_every_satoshi_visible():
    """Six decimal places would round 1,234 satoshis to a misleading 0.000012."""
    snapshot = await build_portfolio("bitcoin", BITCOIN["p2tr"], _BitcoinStub(), market({"bitcoin": 80_000.0}))
    [btc] = snapshot.balances
    assert btc.formatted == "0.00001234"
    assert btc.value_usd == round(0.00001234 * 80_000, 2)


# ---------------------------------------------------------------------
# Evidence for the new chains
# ---------------------------------------------------------------------


class _StatusStub:
    def __init__(self, chain: str, status: ChainStatus):
        self.config = get_chain(chain)
        self._status = status

    async def get_status(self):
        return self._status


async def test_solana_evidence_has_no_chain_id_and_names_its_real_methods():
    """Recording "Chain ID: None" would hand an agent a non-fact."""
    adapter = _StatusStub("solana", ChainStatus(
        chain="solana", configured=True, reachable=True, block_number=433_000_000, slot=455_000_000
    ))
    bundle = await collect_chain_evidence("solana", adapter)
    by_label = {item.label: item for item in bundle.items}

    assert "Chain ID" not in by_label
    assert by_label["Current block height"].source.method == "getBlockHeight"
    assert by_label["Current slot"].value == 455_000_000


async def test_bitcoin_evidence_uses_its_own_method_name():
    adapter = _StatusStub("bitcoin", ChainStatus(chain="bitcoin", configured=True, reachable=True, block_number=971_047))
    bundle = await collect_chain_evidence("bitcoin", adapter)
    height = next(item for item in bundle.items if item.label == "Current block height")
    assert height.source.method == "esplora /blocks/tip/height"


async def test_wallet_evidence_builds_for_a_new_chain():
    """Regression: removing an import made every wallet analysis raise NameError."""
    bundle = await collect_portfolio_evidence(
        "solana", SOLANA_WALLET, adapter=_SolanaStub({USDC_MINT: 25_000_000}),
        market=market({"solana": 100.0, "usd-coin": 1.0}),
    )
    assert not bundle.failures, bundle.failures
    assert any("stablecoin" in item.label.lower() for item in bundle.items)
