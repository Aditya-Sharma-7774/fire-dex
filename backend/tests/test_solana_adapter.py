"""Tests for the Solana adapter.

Response shapes are copied from real mainnet responses, and the addresses
are real: a fee payer that signed a mainnet transaction, and that wallet's
USDC associated token account. No test contacts the network.
"""

import json
import os
import time

import httpx
import pytest
import respx

from app.blockchain.adapters.solana import (
    MAINNET_GENESIS,
    TOKEN_PROGRAMS,
    SolanaAdapter,
    b58decode,
    is_on_curve,
)
from app.blockchain.factory import get_adapter
from app.blockchain.registry import get_chain
from app.config import get_settings
from app.core.errors import ChainNotConfiguredError, InvalidAddressError

RPC = "https://solana.test"
WALLET = "8p4jRpgGUt1PFcgrbCbd11DAVXiRpwxiK47gPLbpomaq"
USDC_TOKEN_ACCOUNT = "5VE4bjECZnNcNwZurVvrXEGUBwL4BtTSFoiPTrURjqYH"
SYSTEM_PROGRAM = "1" * 32
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
DEVNET_GENESIS = "EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG"

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw: bytes) -> str:
    """Test-only encoder, used to build inputs of an exact byte length."""
    number = int.from_bytes(raw, "big")
    out = ""
    while number:
        number, remainder = divmod(number, 58)
        out = ALPHABET[remainder] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\x00"))) + out


def adapter(rpc_url: str | None = RPC) -> SolanaAdapter:
    return SolanaAdapter(config=get_chain("solana"), rpc_url=rpc_url)


def token_account(mint: str, amount: int, decimals: int, owner: str = WALLET) -> dict:
    """One entry of getTokenAccountsByOwner, in jsonParsed form."""
    return {
        "pubkey": USDC_TOKEN_ACCOUNT,
        "account": {
            "data": {
                "parsed": {
                    "info": {
                        "mint": mint,
                        "owner": owner,
                        "state": "initialized",
                        "tokenAmount": {
                            "amount": str(amount),
                            "decimals": decimals,
                            "uiAmountString": str(amount / 10**decimals),
                        },
                    },
                    "type": "account",
                },
                "program": "spl-token",
            }
        },
    }


class Failure:
    """Marks a handler result that should come back as a JSON-RPC error."""


def fake_node(handlers: dict):
    """A Solana node that answers single and batched requests by method name."""

    def answer(call: dict) -> dict:
        handler = handlers.get(call["method"])
        result = handler(call["params"]) if callable(handler) else handler
        if handler is None or isinstance(result, Failure):
            return {"jsonrpc": "2.0", "id": call["id"], "error": {"code": -32602, "message": "Request blocked"}}
        return {"jsonrpc": "2.0", "id": call["id"], "result": result}

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if isinstance(body, list):
            return httpx.Response(200, json=[answer(call) for call in body])
        return httpx.Response(200, json=answer(body))

    return respond


def holdings_by_program(token: list, token_2022: list | Failure):
    def handler(params):
        program = params[1]["programId"]
        value = token if program == TOKEN_PROGRAMS["token"] else token_2022
        return value if isinstance(value, Failure) else {"context": {"slot": 1}, "value": value}

    return handler


# ---------------------------------------------------------------------
# base58 and the curve
# ---------------------------------------------------------------------


def test_base58_decodes_a_real_address_to_32_bytes():
    assert len(b58decode(WALLET)) == 32


def test_leading_ones_decode_to_leading_zero_bytes():
    assert b58decode(SYSTEM_PROGRAM) == b"\x00" * 32


@pytest.mark.parametrize("char", ["0", "O", "I", "l"])
def test_characters_outside_base58_are_rejected(char):
    with pytest.raises(ValueError):
        b58decode(f"abc{char}def")


def test_a_signing_wallet_is_on_the_ed25519_curve():
    assert is_on_curve(b58decode(WALLET)) is True


def test_a_program_derived_address_is_off_the_curve():
    """No private key can exist for it, which is the point of a PDA."""
    assert is_on_curve(b58decode(USDC_TOKEN_ACCOUNT)) is False


# ---------------------------------------------------------------------
# Address validation
# ---------------------------------------------------------------------


def test_a_real_address_is_accepted_unchanged():
    assert adapter().validate_address(f"  {WALLET}  ") == WALLET


def test_an_ethereum_address_is_rejected_with_a_useful_hint():
    with pytest.raises(InvalidAddressError) as caught:
        adapter().validate_address("0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045")
    assert "Ethereum" in caught.value.detail


def test_a_secret_key_is_refused_and_never_echoed_back():
    """64 bytes is an exported keypair. The message must say so, and must not
    repeat the secret in an error that may end up in a log."""
    secret = b58encode(os.urandom(64))

    with pytest.raises(InvalidAddressError) as caught:
        adapter().validate_address(secret)

    assert "PRIVATE KEY" in caught.value.message
    assert secret not in caught.value.message
    assert secret not in (caught.value.detail or "")


def test_a_keypair_file_is_refused():
    keypair_file = json.dumps(list(os.urandom(64)))
    with pytest.raises(InvalidAddressError) as caught:
        adapter().validate_address(keypair_file)
    assert "keypair" in caught.value.message.lower()


def test_the_wrong_number_of_bytes_is_rejected():
    with pytest.raises(InvalidAddressError):
        adapter().validate_address(b58encode(os.urandom(20)))


def test_huge_input_is_rejected_before_it_is_decoded():
    """Base58 decoding is quadratic in length, so length is checked first."""
    started = time.perf_counter()
    with pytest.raises(InvalidAddressError):
        adapter().validate_address("2" * 200_000)
    assert time.perf_counter() - started < 0.1


def test_is_wallet_address_distinguishes_wallets_from_program_accounts():
    assert adapter().is_wallet_address(WALLET) is True
    assert adapter().is_wallet_address(USDC_TOKEN_ACCOUNT) is False


# ---------------------------------------------------------------------
# Native balance
# ---------------------------------------------------------------------


async def test_native_balance_converts_lamports_to_sol():
    node = fake_node({"getBalance": {"context": {"slot": 1}, "value": 166_595_000}})
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        balance = await adapter().get_native_balance(WALLET)

    assert balance.raw == "166595000"
    assert balance.formatted == "0.166595"
    assert balance.symbol == "SOL"
    assert balance.decimals == 9


async def test_an_unconfigured_endpoint_fails_clearly():
    with pytest.raises(ChainNotConfiguredError):
        await adapter(rpc_url=None).get_native_balance(WALLET)


# ---------------------------------------------------------------------
# SPL tokens
# ---------------------------------------------------------------------


async def test_one_mint_spread_across_accounts_is_summed():
    """A real wallet held one mint across four accounts."""
    accounts = [token_account(USDC, 1_000_000, 6) for _ in range(4)]
    node = fake_node({"getTokenAccountsByOwner": holdings_by_program(accounts, [])})

    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        holdings = await adapter().get_token_balances(WALLET)

    [usdc] = holdings.tokens
    assert usdc.raw == "4000000"
    assert usdc.formatted == "4"
    assert usdc.accounts == 4
    assert usdc.symbol == "USDC"


async def test_token_2022_holdings_are_read_alongside_the_original_program():
    other = b58encode(os.urandom(32))
    node = fake_node(
        {
            "getTokenAccountsByOwner": holdings_by_program(
                [token_account(USDC, 100, 6)], [token_account(other, 5, 8)]
            )
        }
    )
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        holdings = await adapter().get_token_balances(WALLET)

    assert {t.program for t in holdings.tokens} == {"token", "token-2022"}
    assert holdings.total_accounts == 2


async def test_dust_is_shown_at_full_precision_not_rounded_to_zero():
    dust_mint = b58encode(os.urandom(32))
    node = fake_node(
        {"getTokenAccountsByOwner": holdings_by_program([token_account(dust_mint, 1, 12)], [])}
    )
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        holdings = await adapter().get_token_balances(WALLET)

    assert holdings.tokens[0].formatted == "0.000000000001"


async def test_empty_accounts_are_hidden_unless_asked_for():
    node = fake_node(
        {"getTokenAccountsByOwner": holdings_by_program([token_account(USDC, 0, 6)], [])}
    )
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        hidden = await adapter().get_token_balances(WALLET)
        shown = await adapter().get_token_balances(WALLET, include_zero=True)

    assert hidden.tokens == []
    assert len(shown.tokens) == 1


async def test_accounts_owned_by_someone_else_are_never_counted():
    """Defends against a faulty or dishonest node."""
    stranger = b58encode(os.urandom(32))
    node = fake_node(
        {
            "getTokenAccountsByOwner": holdings_by_program(
                [token_account(USDC, 5, 6), token_account(USDC, 999_999, 6, owner=stranger)], []
            )
        }
    )
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        holdings = await adapter().get_token_balances(WALLET)

    assert holdings.tokens[0].raw == "5"


async def test_an_unparseable_account_does_not_stop_the_rest():
    broken = {"pubkey": "x", "account": {"data": ["AAAA", "base64"]}}
    node = fake_node(
        {"getTokenAccountsByOwner": holdings_by_program([broken, token_account(USDC, 7, 6)], [])}
    )
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        holdings = await adapter().get_token_balances(WALLET)

    assert [t.raw for t in holdings.tokens] == ["7"]


async def test_a_failed_program_is_reported_not_treated_as_empty():
    node = fake_node(
        {"getTokenAccountsByOwner": holdings_by_program([token_account(USDC, 3, 6)], Failure())}
    )
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        holdings = await adapter().get_token_balances(WALLET)

    assert holdings.incomplete is True
    assert holdings.failed_programs == ["token-2022"]
    assert holdings.tokens[0].raw == "3"


async def test_truncation_is_visible_in_the_result():
    many = [token_account(b58encode(os.urandom(32)), 1, 0) for _ in range(30)]
    node = fake_node({"getTokenAccountsByOwner": holdings_by_program(many, [])})
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        holdings = await adapter().get_token_balances(WALLET, limit=10)

    assert len(holdings.tokens) == 10
    assert holdings.total_mints == 30
    assert holdings.truncated is True


async def test_named_mints_are_listed_first():
    unnamed = b58encode(os.urandom(32))
    node = fake_node(
        {
            "getTokenAccountsByOwner": holdings_by_program(
                [token_account(unnamed, 1, 0), token_account(USDC, 1, 6)], []
            )
        }
    )
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        holdings = await adapter().get_token_balances(WALLET)

    assert holdings.tokens[0].symbol == "USDC"
    assert holdings.tokens[1].symbol is None


async def test_the_owner_is_classified_as_a_wallet_or_not():
    node = fake_node({"getTokenAccountsByOwner": holdings_by_program([], [])})
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        wallet = await adapter().get_token_balances(WALLET)
        pda = await adapter().get_token_balances(USDC_TOKEN_ACCOUNT)

    assert wallet.owner_is_wallet is True
    assert pda.owner_is_wallet is False


# ---------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------


async def test_mainnet_node_is_reachable_with_slot_and_block_height():
    node = fake_node(
        {"getGenesisHash": MAINNET_GENESIS, "getSlot": 455_751_647, "getBlockHeight": 433_788_779}
    )
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        status = await adapter().get_status()

    assert status.reachable is True
    assert status.slot == 455_751_647
    assert status.block_number == 433_788_779
    assert status.chain_id is None


async def test_a_devnet_endpoint_is_caught_and_named():
    node = fake_node({"getGenesisHash": DEVNET_GENESIS, "getSlot": 1, "getBlockHeight": 1})
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        status = await adapter().get_status()

    assert status.reachable is False
    assert "devnet" in status.error


async def test_an_impossible_block_height_is_withheld():
    """Measured on a real public provider: height above slot on every call."""
    node = fake_node(
        {"getGenesisHash": MAINNET_GENESIS, "getSlot": 455_748_068, "getBlockHeight": 455_748_106}
    )
    with respx.mock:
        respx.post(RPC).mock(side_effect=node)
        status = await adapter().get_status()

    assert status.reachable is True
    assert status.block_number is None
    assert status.slot == 455_748_068
    assert "impossible" in status.error


async def test_an_unreachable_node_is_reported_not_raised():
    with respx.mock:
        respx.post(RPC).mock(return_value=httpx.Response(503, text="down"))
        status = await adapter().get_status()

    assert status.reachable is False
    assert status.configured is True


async def test_no_endpoint_is_reported_as_unconfigured():
    status = await adapter(rpc_url=None).get_status()
    assert status.configured is False


# ---------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------


def test_the_factory_serves_solana():
    assert isinstance(get_adapter("solana", get_settings()), SolanaAdapter)

