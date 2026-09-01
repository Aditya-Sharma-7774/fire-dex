"""Tests for canonicalisation, hashing and the hash chain.

These back the auditability claim. Note especially the tests that assert
what the hash does NOT prove -- being precise about the limits is what makes
the claim defensible rather than marketing.
"""

from datetime import datetime, timezone

from app.audit.hashing import (
    GENESIS_HASH,
    canonical_json,
    canonicalise,
    compute_hash,
    format_result_id,
    verify_hash,
)


# ---------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------


def test_key_order_does_not_change_the_hash() -> None:
    """The whole reason canonicalisation exists.

    The same object serialised with different key order must not produce a
    different fingerprint, or verification would fail on identical data.
    """
    first, _ = compute_hash({"b": 2, "a": 1, "c": {"z": 1, "y": 2}})
    second, _ = compute_hash({"c": {"y": 2, "z": 1}, "a": 1, "b": 2})

    assert first == second


def test_integral_floats_and_ints_agree() -> None:
    """2.0 and 2 are the same number and must hash identically."""
    first, _ = compute_hash({"value": 2.0})
    second, _ = compute_hash({"value": 2})

    assert first == second


def test_list_order_is_preserved() -> None:
    """Order IS meaningful in our results, so it must affect the hash."""
    first, _ = compute_hash({"items": [1, 2, 3]})
    second, _ = compute_hash({"items": [3, 2, 1]})

    assert first != second


def test_volatile_metadata_is_excluded() -> None:
    """Timings differ between identical analyses and must not change the hash."""
    first, _ = compute_hash({"result": "x", "duration_ms": 100, "id": 1})
    second, _ = compute_hash({"result": "x", "duration_ms": 9999, "id": 2})

    assert first == second


def test_the_hash_field_itself_is_excluded() -> None:
    """Including it would be circular."""
    first, _ = compute_hash({"result": "x"})
    second, _ = compute_hash({"result": "x", "result_hash": "anything"})

    assert first == second


def test_canonical_json_has_no_insignificant_whitespace() -> None:
    assert canonical_json({"a": 1, "b": [1, 2]}) == '{"a":1,"b":[1,2]}'


def test_datetimes_are_normalised_to_iso() -> None:
    stamp = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)

    assert canonicalise({"at": stamp})["at"] == stamp.isoformat()


# ---------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------


def test_altering_one_character_changes_the_hash() -> None:
    original, canonical = compute_hash({"summary": "RSI is 49.39"})
    tampered = canonical.replace("49.39", "88.50")

    assert not verify_hash(tampered, GENESIS_HASH, original)


def test_an_untouched_record_verifies() -> None:
    digest, canonical = compute_hash({"summary": "RSI is 49.39"})

    assert verify_hash(canonical, GENESIS_HASH, digest)


# ---------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------


def test_the_same_payload_hashes_differently_in_a_different_position() -> None:
    """Chaining means position matters, which is what makes edits detectable."""
    first, _ = compute_hash({"x": 1}, prev_hash=GENESIS_HASH)
    second, _ = compute_hash({"x": 1}, prev_hash="a" * 64)

    assert first != second


def test_editing_an_early_record_breaks_every_later_link() -> None:
    """This is what the chain buys us.

    Someone who edits an old record can recompute that record's own hash.
    They cannot fix the chain without recomputing every record after it,
    because each one commits to its predecessor.
    """
    hash_1, _ = compute_hash({"n": 1}, GENESIS_HASH)
    hash_2, _ = compute_hash({"n": 2}, hash_1)
    hash_3, _ = compute_hash({"n": 3}, hash_2)

    # Record 1 is altered and its own hash is honestly recomputed.
    tampered_1, _ = compute_hash({"n": 999}, GENESIS_HASH)

    # Record 2 still commits to the ORIGINAL hash of record 1, so the
    # mismatch is detectable without re-reading record 1's contents.
    assert tampered_1 != hash_1
    recomputed_2, _ = compute_hash({"n": 2}, tampered_1)
    assert recomputed_2 != hash_2
    assert hash_3 == compute_hash({"n": 3}, hash_2)[0]


def test_hash_is_sha256_length() -> None:
    digest, _ = compute_hash({"x": 1})

    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


# ---------------------------------------------------------------------
# What hashing does NOT prove -- stated as an executable assertion
# ---------------------------------------------------------------------


def test_a_consistent_rewrite_still_verifies() -> None:
    """Documents the honest limit of the claim.

    Anyone who can rewrite BOTH the record and its hash produces something
    that verifies. That is why we say tamper-EVIDENT rather than immutable,
    and why the chain (and, later, an on-chain anchor) matters.
    """
    rewritten_hash, rewritten_canonical = compute_hash({"summary": "completely different"})

    assert verify_hash(rewritten_canonical, GENESIS_HASH, rewritten_hash)


# ---------------------------------------------------------------------
# Result ids
# ---------------------------------------------------------------------


def test_result_id_format() -> None:
    assert format_result_id(2026, 42) == "FIRE-2026-000042"
    assert format_result_id(2026, 1) == "FIRE-2026-000001"
