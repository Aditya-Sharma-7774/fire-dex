"""Shared pytest fixtures."""

import pytest

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
