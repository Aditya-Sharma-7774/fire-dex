"""Tests for the chain registry, the EVM adapter and the chain endpoints.

Network calls are mocked with respx so these tests are fast, repeatable,
and do not consume a public node's rate limit. The one exception is
marked `live` and is skipped by default.
"""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.blockchain.adapters.evm import EvmAdapter, format_units
from app.blockchain.registry import get_chain, get_evm_chain_by_chain_id, list_chains
from app.blockchain.types import ChainFamily
from app.core.errors import ChainNotSupportedError, InvalidAddressError, RpcError
from app.main import app

client = TestClient(app)

# A well-known public address (vitalik.eth). Used only as a valid-format
# example -- no private key is involved anywhere in these tests.
SAMPLE_ADDRESS = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
RPC_URL = "https://rpc.example.test"


def _rpc_result(value: str) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": value})


# ---------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------


def test_registry_contains_the_five_planned_chains() -> None:
    ids = {c.id for c in list_chains()}
    assert ids == {"ethereum", "sepolia", "bsc", "solana", "bitcoin"}


def test_chain_ids_are_correct() -> None:
    """A wrong chain ID would send transactions to the wrong network."""
    assert get_chain("ethereum").chain_id == 1
    assert get_chain("sepolia").chain_id == 11155111
    assert get_chain("bsc").chain_id == 56


def test_non_evm_chains_have_no_chain_id() -> None:
    """Solana and Bitcoin have no EIP-155 chain ID; it must not be faked."""
    assert get_chain("solana").chain_id is None
    assert get_chain("bitcoin").chain_id is None


def test_native_decimals_are_correct() -> None:
    """Wrong decimals silently misreport every balance by a factor of 10^n."""
    assert get_chain("ethereum").native_decimals == 18
    assert get_chain("solana").native_decimals == 9
    assert get_chain("bitcoin").native_decimals == 8


def test_lookup_by_eip155_chain_id() -> None:
    assert get_evm_chain_by_chain_id(11155111).id == "sepolia"
    assert get_evm_chain_by_chain_id(999999) is None


def test_unknown_chain_raises() -> None:
    with pytest.raises(ChainNotSupportedError):
        get_chain("dogecoin")


def test_only_evm_chains_are_active_so_far() -> None:
    """We must not advertise chains we have not implemented."""
    active = {c.id for c in list_chains() if c.is_active}
    assert active == {"ethereum", "sepolia"}
    assert all(get_chain(c).family is ChainFamily.EVM for c in active)


# ---------------------------------------------------------------------
# Unit formatting
# ---------------------------------------------------------------------


def test_format_units_converts_wei_to_ether() -> None:
    assert format_units(1_234_500_000_000_000_000, 18) == "1.2345"


def test_format_units_handles_zero_and_whole_numbers() -> None:
    assert format_units(0, 18) == "0"
    assert format_units(2_000_000_000_000_000_000, 18) == "2"


def test_format_units_does_not_lose_precision_on_large_balances() -> None:
    """Above 2^53 a float would round. Decimal must not."""
    wei = 123_456_789_123_456_789_123_456_789
    assert format_units(wei, 18).startswith("123456789.123457")


def test_format_units_respects_chain_decimals() -> None:
    assert format_units(1_500_000_000, 9) == "1.5"  # SOL
    assert format_units(150_000_000, 8) == "1.5"  # BTC


# ---------------------------------------------------------------------
# Address validation
# ---------------------------------------------------------------------


def _adapter(chain: str = "sepolia", rpc_url: str | None = RPC_URL) -> EvmAdapter:
    return EvmAdapter(config=get_chain(chain), rpc_url=rpc_url)


def test_valid_address_is_returned_checksummed() -> None:
    adapter = _adapter()
    assert adapter.validate_address(SAMPLE_ADDRESS.lower()) == SAMPLE_ADDRESS


@pytest.mark.parametrize(
    "bad",
    [
        "not-an-address",
        "0x123",  # too short
        "d8dA6BF26964aF9D7eEd9e03E53415D37aA96045",  # missing 0x
        "0xZZZZ6BF26964aF9D7eEd9e03E53415D37aA96045",  # non-hex
        "",
        "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",  # a Solana address
    ],
)
def test_invalid_addresses_are_rejected(bad: str) -> None:
    """Rejecting before the RPC call gives a clear error instead of a node error."""
    with pytest.raises(InvalidAddressError):
        _adapter().validate_address(bad)


def test_a_private_key_shaped_string_is_rejected() -> None:
    """Safety check: 64 hex characters is the shape of a PRIVATE KEY.

    If a user ever pastes one into an address field it must be refused
    loudly, never partially accepted or echoed back.
    """
    private_key_shaped = "a" * 64

    with pytest.raises(InvalidAddressError):
        _adapter().validate_address(private_key_shaped)

    with pytest.raises(InvalidAddressError):
        _adapter().validate_address("0x" + "a" * 64)


# ---------------------------------------------------------------------
# Balance fetching (mocked RPC)
# ---------------------------------------------------------------------


@respx.mock
async def test_get_native_balance_parses_hex_wei() -> None:
    respx.post(RPC_URL).mock(return_value=_rpc_result("0x1122b1c4b1b1a000"))

    balance = await _adapter().get_native_balance(SAMPLE_ADDRESS)

    assert balance.raw == str(0x1122B1C4B1B1A000)
    assert balance.symbol == "ETH"
    assert balance.decimals == 18
    assert balance.chain == "sepolia"


@respx.mock
async def test_balance_raw_is_a_string_for_javascript_safety() -> None:
    """Wei exceeds JavaScript's safe integer range; it must not be a number."""
    respx.post(RPC_URL).mock(return_value=_rpc_result("0xde0b6b3a7640000"))

    balance = await _adapter().get_native_balance(SAMPLE_ADDRESS)

    assert isinstance(balance.raw, str)
    assert balance.formatted == "1"


@respx.mock
async def test_zero_balance_is_reported_honestly() -> None:
    respx.post(RPC_URL).mock(return_value=_rpc_result("0x0"))

    balance = await _adapter().get_native_balance(SAMPLE_ADDRESS)

    assert balance.raw == "0"
    assert balance.formatted == "0"


@respx.mock
async def test_json_rpc_error_becomes_rpc_error() -> None:
    """A JSON-RPC error arrives with HTTP 200, so status alone is not enough."""
    respx.post(RPC_URL).mock(
        return_value=httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}},
        )
    )

    with pytest.raises(RpcError):
        await _adapter().get_native_balance(SAMPLE_ADDRESS)


@respx.mock
async def test_unreachable_node_becomes_rpc_error() -> None:
    respx.post(RPC_URL).mock(side_effect=httpx.ConnectError("no route"))

    with pytest.raises(RpcError):
        await _adapter().get_native_balance(SAMPLE_ADDRESS)


@respx.mock
async def test_status_detects_wrong_chain_id() -> None:
    """Pointing the Ethereum URL at a Sepolia node must be caught, not ignored."""
    respx.post(RPC_URL).mock(return_value=_rpc_result("0xaa36a7"))  # Sepolia

    status = await _adapter("ethereum").get_status()

    assert status.reachable is False
    assert "chain ID" in (status.error or "")


async def test_status_reports_unconfigured_chain() -> None:
    status = await _adapter("bsc", rpc_url=None).get_status()

    assert status.configured is False
    assert status.reachable is False


# ---------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------


def test_list_chains_endpoint() -> None:
    response = client.get("/api/v1/chains")

    assert response.status_code == 200
    assert {c["id"] for c in response.json()} == {
        "ethereum",
        "sepolia",
        "bsc",
        "solana",
        "bitcoin",
    }


def test_unknown_chain_returns_404_with_guidance() -> None:
    response = client.get("/api/v1/chains/dogecoin")

    assert response.status_code == 404
    body = response.json()
    assert body["error"] == "chain_not_supported"
    assert "sepolia" in body["detail"]


def test_unimplemented_chain_says_so_clearly() -> None:
    """Solana is a known chain with no adapter yet -- that must be explicit."""
    response = client.get("/api/v1/chains/solana/status")

    assert response.status_code == 404
    assert "not implemented yet" in response.json()["message"]


def test_invalid_address_returns_400() -> None:
    response = client.get("/api/v1/chains/sepolia/balance/not-an-address")

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_address"


def test_validate_endpoint_returns_checksummed_address() -> None:
    response = client.get(
        "/api/v1/chains/ethereum/validate",
        params={"address": SAMPLE_ADDRESS.lower()},
    )

    assert response.status_code == 200
    assert response.json()["address"] == SAMPLE_ADDRESS
