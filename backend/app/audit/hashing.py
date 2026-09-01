"""Canonical serialisation and SHA-256 hashing of analysis results.

WHAT THIS PROVES, AND WHAT IT DOES NOT
--------------------------------------
A hash over a canonical representation proves that a stored record has not
been altered since it was written. That is TAMPER-EVIDENCE.

It does NOT make the record immutable. Anyone with database write access
could rewrite both the record and its hash. The hash chain below makes that
harder -- each record includes the previous record's hash, so quietly
editing one old record breaks every hash after it -- but it is still not
immutability.

We would only earn the word "immutable" by anchoring a chain root on a
blockchain, which is a documented future option and not a current claim.
Being precise about this is a strength; overclaiming is the fastest way to
lose credibility.

WHY CANONICALISATION IS NECESSARY
---------------------------------
Hashing raw JSON is useless, because the same data can serialise many ways:

    {"a":1,"b":2}   and   {"b": 2, "a": 1}

are the same object but hash differently. So before hashing we produce ONE
canonical form: keys sorted, no insignificant whitespace, UTF-8, and floats
normalised. Then the same result always produces the same hash, on any
machine, in any Python version.
"""

import hashlib
import json
from datetime import datetime
from typing import Any

# The genesis value for the first record in the chain. Fixed and public, so
# the chain can be verified from its very beginning.
GENESIS_HASH = "0" * 64

# Fields excluded from the canonical form because they are metadata ABOUT
# the record rather than part of the result being attested.
#
# The hash itself is the obvious one -- including it would be circular. The
# others vary between identical analyses (how long a network call took, the
# database row id) and would make the same result hash differently.
EXCLUDED_FIELDS = frozenset(
    {
        "result_hash",
        "prev_hash",
        "id",
        "created_at",
        "duration_ms",
        "latency_ms",
        "fetched_at",
    }
)


def canonicalise(value: Any) -> Any:
    """Reduce a value to a deterministic, comparable form.

    Rules:
      dict   keys sorted; excluded fields dropped; applied recursively
      list   order preserved (order is meaningful in our results)
      float  integral floats collapsed to int, so 2.0 and 2 agree
      datetime  ISO 8601 in UTC, so timezone representation cannot vary
    """
    if isinstance(value, dict):
        return {
            key: canonicalise(item)
            for key, item in sorted(value.items())
            if key not in EXCLUDED_FIELDS
        }

    if isinstance(value, (list, tuple)):
        return [canonicalise(item) for item in value]

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, float):
        # 2.0 and 2 must not hash differently. Also normalises -0.0 to 0.
        if value.is_integer():
            return int(value)
        return value

    return value


def canonical_json(payload: dict) -> str:
    """The exact string that gets hashed.

    Stored alongside the hash so anyone can recompute and check it without
    needing our code to reproduce the serialisation.
    """
    return json.dumps(
        canonicalise(payload),
        sort_keys=True,
        separators=(",", ":"),  # no insignificant whitespace
        ensure_ascii=False,
        default=str,  # anything unexpected becomes its string form
    )


def compute_hash(payload: dict, prev_hash: str = GENESIS_HASH) -> tuple[str, str]:
    """Hash a result, chained to the previous record.

    Returns (hash, canonical_json).

    The previous hash is mixed in, so the records form a chain: altering an
    old record changes its hash, which invalidates every later record.

    SHA-256 is used rather than MD5 or SHA-1 because both of those have
    practical collision attacks, which would destroy the integrity property
    entirely.
    """
    canonical = canonical_json(payload)
    digest = hashlib.sha256(f"{prev_hash}:{canonical}".encode("utf-8")).hexdigest()
    return digest, canonical


def verify_hash(canonical: str, prev_hash: str, expected_hash: str) -> bool:
    """Recompute a hash from a stored canonical form and compare it."""
    actual = hashlib.sha256(f"{prev_hash}:{canonical}".encode("utf-8")).hexdigest()
    return actual == expected_hash


def format_result_id(year: int, sequence: int) -> str:
    """Human-quotable identifier, e.g. FIRE-2026-000042."""
    return f"FIRE-{year}-{sequence:06d}"
