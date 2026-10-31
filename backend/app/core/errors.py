"""Typed error hierarchy.

Project rule: never silently swallow an error, and never let an external
failure surface as a generic 500. Every failure we can anticipate gets a
type here, a clear message for the user, and an HTTP status code.

The point is that callers can react to a *category* of failure. The UI
treats "the provider is rate limited, try again shortly" very differently
from "that address is not valid for this chain".
"""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, redact

log = get_logger(__name__)


def preview(text: str) -> str:
    """Enough of rejected input to recognise it, never the whole value.

    Rejected input is exactly where a pasted secret turns up, so an error
    message quotes only its ends.
    """
    return text if len(text) <= 12 else f"{text[:6]}...{text[-4:]}"


class FireDexError(Exception):
    """Base class for every error this application raises deliberately."""

    status_code: int = 500
    error_code: str = "internal_error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


# --- input problems (the caller can fix these) -----------------------


class InvalidAddressError(FireDexError):
    """The address is not valid for the chain it was submitted against.

    Deliberately its own type: an address that is valid on Ethereum is
    meaningless on Solana, and confusing the two is a financial safety
    issue, not a formatting nicety.
    """

    status_code = 400
    error_code = "invalid_address"


class NotFoundError(FireDexError):
    """The requested record does not exist."""

    status_code = 404
    error_code = "not_found"


class ChainNotSupportedError(FireDexError):
    """No adapter exists for the requested chain."""

    status_code = 404
    error_code = "chain_not_supported"


# --- configuration problems (the operator can fix these) -------------


class ChainNotConfiguredError(FireDexError):
    """The chain is known but has no RPC endpoint configured."""

    status_code = 503
    error_code = "chain_not_configured"


# --- external failures (nobody can fix these right now) --------------


class ProviderError(FireDexError):
    """An external data provider failed."""

    status_code = 502
    error_code = "provider_error"


class RpcError(ProviderError):
    """A blockchain RPC node returned an error or unusable response."""

    error_code = "rpc_error"


class RateLimitError(ProviderError):
    """An external provider refused us for exceeding its quota."""

    status_code = 429
    error_code = "rate_limited"


async def firedex_error_handler(request: Request, exc: FireDexError) -> JSONResponse:
    """Turn a FireDexError into a consistent JSON response.

    Registered once in main.py so every route gets this behaviour without
    needing its own try/except.
    """
    # Every error reaches the client through here, so this is the one place
    # that guarantees no error echoes a pasted key or a key-bearing URL back.
    message = redact(exc.message)
    detail = redact(exc.detail) if exc.detail else exc.detail

    log.warning(
        "request_failed",
        path=request.url.path,
        error_code=exc.error_code,
        message=message,
        detail=detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error_code, "message": message, "detail": detail},
    )
