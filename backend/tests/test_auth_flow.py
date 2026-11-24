"""Authentication flow: credentials, tokens, session endpoints and CORS.

The login regression reported in production was a blocked CORS preflight: the
browser never sent ``POST /api/v1/auth/login`` because the page was served from
an origin missing from ``CORS_ORIGINS``.  These tests pin both the credential
contract and the origin handling.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.services.auth import create_access_token


def _register(client, password: str = "securepass123") -> tuple[str, dict]:
    email = f"auth-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Auth Clinician"},
    )
    assert response.status_code == 201, response.text
    return email, response.json()


def _login(client, email: str, password: str):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


# --------------------------------------------------------------- credentials


def test_existing_user_can_sign_in_and_use_the_token(client):
    email, profile = _register(client)

    response = _login(client, email, "securepass123")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]

    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["id"] == profile["id"]
    assert me.json()["email"] == email


def test_password_is_not_trimmed_and_must_match_exactly(client):
    email, _ = _register(client, password=" paddedpass1 ")

    assert _login(client, email, "paddedpass1").status_code == 401
    assert _login(client, email, " paddedpass1 ").status_code == 200


def test_wrong_password_is_rejected_without_a_session(client):
    email, _ = _register(client)

    response = _login(client, email, "definitely-wrong")

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"
    assert "access_token" not in response.json()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_unknown_email_is_rejected_with_the_same_message(client):
    hidden = _login(client, f"missing-{uuid.uuid4().hex[:8]}@example.com", "securepass123")

    assert hidden.status_code == 401
    assert hidden.json()["detail"] == "Incorrect email or password"


def test_inactive_account_cannot_sign_in(client, db_session):
    from app.models.user import User

    email, _ = _register(client)
    user = db_session.query(User).filter(User.email == email).one()
    user.is_active = False
    db_session.commit()

    response = _login(client, email, "securepass123")

    assert response.status_code == 403
    assert "unavailable" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"email": "someone@example.com"},
        {"password": "securepass123"},
        {"email": "not-an-email", "password": "securepass123"},
    ],
)
def test_missing_or_invalid_fields_return_validation_errors(client, payload):
    response = client.post("/api/v1/auth/login", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid request."


# -------------------------------------------------------------------- tokens


def test_invalid_and_expired_tokens_are_rejected(client):
    _, profile = _register(client)

    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}).status_code
        == 401
    )

    expired = create_access_token({"sub": profile["id"]}, expires_delta=timedelta(seconds=-30))
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code
        == 401
    )


def test_refresh_token_is_not_accepted_as_an_access_token(client):
    email, _ = _register(client)
    tokens = _login(client, email, "securepass123").json()

    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )

    assert response.status_code == 401


def test_refresh_issues_a_usable_session(client):
    email, _ = _register(client)
    tokens = _login(client, email, "securepass123").json()

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200

    new_access = refreshed.json()["access_token"]
    assert (
        client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"}).status_code
        == 200
    )

    bad = client.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
    assert bad.status_code == 401


def test_logout_style_client_discards_tokens(client):
    """The client clears storage on logout; the API must then refuse calls."""
    email, _ = _register(client)
    tokens = _login(client, email, "securepass123").json()
    assert tokens["access_token"]

    # A request without the header (what a signed-out browser sends) is refused.
    assert client.get("/api/v1/documents").status_code == 401


# ---------------------------------------------------------------------- CORS


DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]


@pytest.mark.parametrize("origin", DEV_ORIGINS)
def test_preflight_from_local_dev_origin_is_allowed(client, origin):
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


def test_login_response_is_readable_by_a_local_dev_origin(client):
    email, _ = _register(client)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "securepass123"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_preflight_from_a_foreign_origin_is_refused(client):
    response = client.options(
        "/api/v1/auth/login",
        headers={
            "Origin": "https://evil.example.net",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_production_does_not_allow_arbitrary_origins():
    production = Settings(
        environment="production",
        cors_origins="https://app.mediquery.ai",
        jwt_secret="x" * 48,
    )

    assert production.cors_origin_regex == ""
    assert production.cors_allow_list == ["https://app.mediquery.ai"]


def test_development_enables_the_loopback_pattern():
    development = Settings(environment="development")

    assert development.cors_origin_regex
    assert "127" in development.cors_origin_regex


# --------------------------------------------------------- startup behaviour


def test_app_serves_health_without_authentication():
    from app.main import app

    with TestClient(app) as anonymous:
        assert anonymous.get("/health").status_code == 200
