"""JSON-RPC 2.0 transport, shared by every chain adapter.

Ethereum and Solana are different technologies, but both nodes speak the
same wire protocol: a JSON body with `jsonrpc`, `id`, `method` and `params`,
answered by a body carrying either `result` or `error`. So the transport
lives here once, and each adapter supplies only what is genuinely different
about its chain -- the methods it calls and how it reads the results.

Everything an adapter needs from the network goes through `call` or `batch`,
which means caching, timeouts, rate-limit detection and error mapping are
each implemented in exactly one place.
"""

import asyncio
import json
import ssl
import weakref
from typing import Any

import certifi
import httpx

from app.core.errors import RateLimitError, RpcError
from app.core.logging import get_logger
from app.market.cache import TtlCache

log = get_logger(__name__)

# A read should be fast. A node slower than this is effectively down, and
# waiting only makes the interface feel broken.
RPC_TIMEOUT_SECONDS = 12.0

# Chain reads are cached briefly.
#
# WHY: the dashboard polls balances, the block height and the portfolio on
# separate timers. Without this, every poll from every open tab becomes a
# request to a shared public node, which then rate limits us -- we measured
# a portfolio request degrading from 8 seconds to 48 seconds and failing.
#
# Ethereum produces a block roughly every 12 seconds, so a balance cannot
# meaningfully change faster than that, and 8 seconds is invisible to the
# user while collapsing repeated polls into one call.
RPC_CACHE_TTL_SECONDS = 8.0

# Values are stored as JSON text rather than as the decoded objects. That is
# a defensive copy: a caller that mutated a cached dict would otherwise
# silently corrupt the value every later caller receives.
_cache: TtlCache[str] = TtlCache(default_ttl_seconds=RPC_CACHE_TTL_SECONDS)


def clear_rpc_cache() -> None:
    """Empty the cache. Used by tests to keep them independent."""
    _cache.clear()


# One HTTP client per event loop, reused for every request.
#
# Creating a client costs about 0.23s here -- mostly loading the TLS
# certificate bundle -- and it runs synchronously, blocking the event loop.
# A client per request therefore added that to every call AND serialised
# requests that were meant to run concurrently, besides discarding the
# pooled connection each time. Clients are keyed by loop because an async
# client is bound to the loop it was created on.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient]" = (
    weakref.WeakKeyDictionary()
)


# The certificate bundle is loaded once and shared, so even a new client is
# cheap. It is the same bundle httpx uses by default, so trust is unchanged.
_TLS = ssl.create_default_context(cafile=certifi.where())


def _client() -> httpx.AsyncClient:
    loop = asyncio.get_running_loop()
    client = _clients.get(loop)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(timeout=RPC_TIMEOUT_SECONDS, verify=_TLS)
        _clients[loop] = client
    return client


async def aclose() -> None:
    """Close the current loop's client. Called on application shutdown."""
    client = _clients.pop(asyncio.get_running_loop(), None)
    if client is not None:
        await client.aclose()


def _key(namespace: str, method: str, params: Any) -> str:
    return f"{namespace}:{method}:{json.dumps(params, sort_keys=True)}"


async def call(
    url: str,
    method: str,
    params: list,
    *,
    chain_name: str,
    namespace: str,
    use_cache: bool = True,
) -> Any:
    """Make one JSON-RPC call and return its `result` field.

    `namespace` keeps two chains' caches apart; `chain_name` is used only to
    make error messages readable.
    """
    key = _key(namespace, method, params)
    if use_cache:
        cached = _cache.get_fresh(key)
        if cached is not None:
            return json.loads(cached)

    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    body = await _post(url, payload, chain_name=chain_name, describe=method)

    if not isinstance(body, dict):
        raise RpcError(
            f"{chain_name} node returned an unexpected response.",
            detail=str(body)[:200],
        )

    # A JSON-RPC error arrives with HTTP 200 and an "error" object, so the
    # status code alone is never enough to know a call succeeded.
    if "error" in body:
        error = body["error"]
        raise RpcError(
            f"{chain_name} node rejected the request.",
            detail=f"{error.get('code')}: {error.get('message')}",
        )

    if "result" not in body:
        raise RpcError(f"{chain_name} node returned no result.", detail=str(body)[:200])

    result = body["result"]
    if use_cache:
        _cache.set(key, json.dumps(result))
    return result


async def batch(
    url: str,
    calls: list[tuple[str, list]],
    *,
    chain_name: str,
    namespace: str,
) -> list[Any | None]:
    """Make several calls in ONE HTTP request.

    Results come back in the order of `calls`. An entry is None when that
    individual call failed -- one bad request must not discard the others.

    Reading ten token balances as ten requests is ten times the latency and
    ten times the rate-limit consumption. JSON-RPC 2.0 allows an array of
    requests in one POST, and both the Ethereum and Solana nodes we use
    accept it (verified against each before relying on it).
    """
    if not calls:
        return []

    key = _key(namespace, "batch", calls)
    cached = _cache.get_fresh(key)
    if cached is not None:
        return json.loads(cached)

    payload = [
        {"jsonrpc": "2.0", "id": index, "method": method, "params": params}
        for index, (method, params) in enumerate(calls)
    ]
    body = await _post(url, payload, chain_name=chain_name, describe=f"batch of {len(calls)}")

    # Some nodes answer a whole batch with a single error object.
    if isinstance(body, dict):
        raise RpcError(
            f"{chain_name} node rejected the batch.",
            detail=str(body.get("error", body))[:200],
        )

    # A batch response may arrive out of order, so it is matched by id.
    by_id: dict[int, Any | None] = {}
    for item in body:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if "error" in item:
            log.warning(
                "batch_call_failed",
                chain=namespace,
                call_id=item_id,
                error=str(item["error"])[:120],
            )
            by_id[item_id] = None
        else:
            by_id[item_id] = item.get("result")

    results = [by_id.get(index) for index in range(len(calls))]
    _cache.set(key, json.dumps(results))
    return results


async def get_json(
    url: str,
    *,
    chain_name: str,
    namespace: str,
    ttl_seconds: float | None = None,
    text: bool = False,
) -> Any:
    """GET a document, for chains whose API is REST rather than JSON-RPC.

    Bitcoin's Esplora API is plain REST. It still goes through this module so
    that it shares the cache tests clear, the timeouts and the error mapping.
    `text=True` returns the body as a string: some Esplora endpoints answer
    in plain text, and a block hash is not valid JSON.
    """
    key = _key(namespace, "GET", url)
    cached = _cache.get_fresh(key)
    if cached is not None:
        return json.loads(cached)

    body = await _send(
        "GET", url, None, chain_name=chain_name, describe=f"GET {namespace}", text=text
    )
    _cache.set(key, json.dumps(body), ttl_seconds=ttl_seconds)
    return body


async def _post(url: str, payload: Any, *, chain_name: str, describe: str) -> Any:
    return await _send("POST", url, payload, chain_name=chain_name, describe=describe)


async def _send(
    method: str, url: str, payload: Any, *, chain_name: str, describe: str, text: bool = False
) -> Any:
    """Send the request and map transport failures to project errors."""
    client = _client()
    try:
        if method == "GET":
            response = await client.get(url)
        else:
            response = await client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        raise RpcError(
            f"{chain_name} node did not respond in time.",
            detail=f"{describe} timed out after {RPC_TIMEOUT_SECONDS}s",
        ) from exc
    except httpx.HTTPError as exc:
        raise RpcError(f"Could not reach the {chain_name} node.", detail=str(exc)) from exc

    if response.status_code == 429:
        raise RateLimitError(
            f"The {chain_name} RPC provider is rate limiting us.",
            detail="Try again shortly, or configure your own RPC endpoint.",
        )
    if response.status_code >= 400:
        raise RpcError(
            f"{chain_name} node returned HTTP {response.status_code}.",
            detail=response.text[:200],
        )

    if text:
        return response.text.strip()
    try:
        return response.json()
    except ValueError as exc:
        raise RpcError(
            f"{chain_name} node returned a non-JSON response.",
            detail=response.text[:200],
        ) from exc
