"""Tests for the meta endpoints.

These are deliberately boring. Their job is to prove the app can be
imported and served at all -- which catches the single most common
beginner failure: a typo or bad import that only shows up at runtime.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, base_url="http://127.0.0.1")


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "Fire DEX"


def test_health_reports_a_known_mode() -> None:
    """The safety regime must always be one of the three defined modes.

    This matters more than it looks: a typo in APP_MODE should fail loudly,
    not silently leave the app in an undefined state.
    """
    body = client.get("/health").json()

    assert body["mode"] in {"development", "testnet", "production"}


def test_health_timestamp_is_utc() -> None:
    """Every timestamp in Fire DEX is UTC. Audit records depend on it."""
    body = client.get("/health").json()

    assert body["timestamp"].endswith("Z") or "+00:00" in body["timestamp"]


def test_root_points_at_docs() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["docs"] == "/docs"


def test_openapi_schema_is_generated() -> None:
    """The OpenAPI schema is how the frontend gets its types later."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/health" in response.json()["paths"]
