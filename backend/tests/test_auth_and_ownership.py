from __future__ import annotations

import uuid


def _register(client, email: str | None = None, password: str = "securepass123"):
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Test Clinician"},
    )
    assert response.status_code == 201, response.text
    return email, response.json()


def _token(client, email: str, password: str = "securepass123") -> str:
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def test_registration_has_no_role_field(client):
    email, body = _register(client)
    assert body["email"] == email
    assert "role" not in body

    # A role supplied by an old client is ignored, not required.
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"legacy-{uuid.uuid4().hex[:6]}@example.com",
            "password": "securepass123",
            "full_name": "Legacy Client",
            "role": "doctor",
        },
    )
    assert response.status_code == 201


def test_duplicate_email_rejected(client):
    email, _ = _register(client)
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "securepass123", "full_name": "Someone"},
    )
    assert response.status_code == 400


def test_login_profile_and_refresh(client):
    email, _ = _register(client)
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "securepass123"})
    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["full_name"] == "Test Clinician"
    assert "role" not in me.json()

    refreshed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


def test_protected_routes_require_authentication(client):
    assert client.get("/api/v1/documents").status_code == 401
    assert client.get("/api/v1/documents").status_code == 401


def test_documents_are_isolated_between_users(client):
    from app.database import SessionLocal
    from app.models.document import Document, DocumentStatus

    owner_email, _ = _register(client)
    owner_token = _token(client, owner_email)
    outsider_email, _ = _register(client)
    outsider_token = _token(client, outsider_email)

    with SessionLocal() as db:
        from app.models.user import User

        owner = db.query(User).filter(User.email == owner_email).first()
        document = Document(
            user_id=owner.id,
            filename="private.txt",
            storage_path="user-x/private.txt",
            file_size=10,
            status=DocumentStatus.COMPLETED.value,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        document_id = document.id

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    outsider_headers = {"Authorization": f"Bearer {outsider_token}"}

    assert client.get(
        f"/api/v1/documents/{document_id}/status", headers=owner_headers
    ).status_code == 200
    assert client.get(
        f"/api/v1/documents/{document_id}/status", headers=outsider_headers
    ).status_code == 404
    assert client.delete(
        f"/api/v1/documents/{document_id}", headers=outsider_headers
    ).status_code == 404
    assert client.get("/api/v1/documents", headers=outsider_headers).json()["total"] == 0
