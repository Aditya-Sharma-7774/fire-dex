"""Shared pytest fixtures."""

import os

import pytest
import respx

from app.blockchain.adapters.evm import clear_rpc_cache


@pytest.fixture(autouse=True)
def _isolate_rpc_cache():
    """Empty the RPC cache before and after every test.

    The cache is module-level so it is shared across the whole process. Left
    alone, one test's mocked RPC response would be served to the next test,
    making results depend on execution order -- which is exactly the kind of
    flakiness that erodes trust in a test suite.
    """
    clear_rpc_cache()
    yield
    clear_rpc_cache()


@pytest.fixture(autouse=True)
def _no_network():
    """Fail any test that reaches the real network.

    A test that silently made a live call to Solana mainnet was caught only
    because its status code happened to change. Live calls make a suite slow
    and its results depend on someone else's server, so every external
    request must be mocked.

    Set FIREDEX_LIVE_TESTS=1 to run the deliberate live checks instead.
    """
    if os.environ.get("FIREDEX_LIVE_TESTS") == "1":
        yield
        return
    # The default router, not a new one: tests register routes with the
    # module-level respx.get/post, which add to the default router. A
    # separate guard router would answer every request with "not mocked".
    # It rolls its routes back on exit, so each test still starts clean.
    with respx.mock:
        yield
