from __future__ import annotations

import asyncio
import uuid

MEDICAL_TEXT = (
    "Hypertension Guideline\n\n"
    "Hypertension is often asymptomatic in its early stages. Symptoms may include "
    "headache, dizziness and blurred vision. First-line treatment includes lifestyle "
    "change, thiazide diuretics, ACE inhibitors and calcium channel blockers. "
    "Blood pressure should be monitored regularly in patients with diabetes."
)


def _register(client, prefix: str = "conv"):
    email = f"{prefix}-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "securepass123", "full_name": "Conversation Owner"},
    )
    assert register.status_code == 201, register.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "securepass123"})
    assert login.status_code == 200, login.text
    return email, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _upload_and_index(client, headers) -> str:
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files=[("files", ("hypertension.txt", MEDICAL_TEXT.encode(), "text/plain"))],
    )
    assert response.status_code == 200, response.text
    document_id = response.json()["documents"][0]["id"]

    from app.services.jobs import process_pending_jobs_once

    asyncio.run(process_pending_jobs_once(limit=5))
    status_response = client.get(f"/api/v1/documents/{document_id}/status", headers=headers)
    assert status_response.json()["status"] == "completed", status_response.text
    return document_id


def _ask(client, headers, question: str, **extra):
    payload = {"question": question, "mode": "agentic", **extra}
    return client.post("/api/v1/chat/query", headers=headers, json=payload)


def test_first_question_creates_a_titled_conversation(client):
    _, headers = _register(client)
    _upload_and_index(client, headers)

    first_question = "What are the symptoms of hypertension?"
    first = _ask(client, headers, first_question)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["conversation_id"] is not None
    assert body["conversation_title"] == "Symptoms of hypertension"
    conversation_id = body["conversation_id"]

    second = _ask(
        client,
        headers,
        "What treatment is recommended?",
        conversation_id=conversation_id,
        mode="standard",
    )
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == conversation_id

    detail = client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert [message["question"] for message in payload["messages"]] == [
        first_question,
        "What treatment is recommended?",
    ]
    assert payload["messages"][0]["sources"], "citations must persist with the message"
    assert payload["messages"][1]["sources"]
    assert payload["message_count"] == 2
    assert payload["title"] == "Symptoms of hypertension"

    listing = client.get("/api/v1/chat/conversations", headers=headers).json()
    assert listing["total"] == 1
    assert listing["conversations"][0]["message_count"] == 2


def test_rename_pin_and_delete_are_persistent(client):
    _, headers = _register(client)
    _upload_and_index(client, headers)

    created = _ask(client, headers, "What are the symptoms of hypertension?").json()
    conversation_id = created["conversation_id"]

    renamed = client.patch(
        f"/api/v1/chat/conversations/{conversation_id}",
        headers=headers,
        json={"title": "  Hypertension   review  "},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Hypertension review"

    # A later message must not overwrite the manual title.
    _ask(client, headers, "What about dizziness?", conversation_id=conversation_id)
    detail = client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=headers).json()
    assert detail["title"] == "Hypertension review"

    # Blank titles are rejected, not silently saved.
    blank = client.patch(
        f"/api/v1/chat/conversations/{conversation_id}",
        headers=headers,
        json={"title": "   "},
    )
    assert blank.status_code == 422

    pinned = client.patch(
        f"/api/v1/chat/conversations/{conversation_id}",
        headers=headers,
        json={"is_pinned": True},
    )
    assert pinned.json()["is_pinned"] is True
    assert client.get("/api/v1/chat/conversations", headers=headers).json()["conversations"][0][
        "is_pinned"
    ] is True

    unpinned = client.patch(
        f"/api/v1/chat/conversations/{conversation_id}",
        headers=headers,
        json={"is_pinned": False},
    )
    assert unpinned.json()["is_pinned"] is False

    deleted = client.delete(
        f"/api/v1/chat/conversations/{conversation_id}", headers=headers
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["deleted_messages"] >= 2
    assert (
        client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=headers).status_code
        == 404
    )
    assert client.get("/api/v1/chat/conversations", headers=headers).json()["total"] == 0
    # Messages of the deleted conversation are gone from chat history too.
    assert client.get("/api/v1/chat/history", headers=headers).json()["total"] == 0


def test_conversations_are_isolated_between_users(client):
    _, owner = _register(client)
    _upload_and_index(client, owner)
    conversation_id = _ask(client, owner, "What are the symptoms of hypertension?").json()[
        "conversation_id"
    ]

    _, outsider = _register(client)
    assert (
        client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=outsider).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/chat/conversations/{conversation_id}",
            headers=outsider,
            json={"title": "Hijacked"},
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/api/v1/chat/conversations/{conversation_id}",
            headers=outsider,
            json={"is_pinned": True},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/chat/conversations/{conversation_id}", headers=outsider
        ).status_code
        == 404
    )
    assert client.get("/api/v1/chat/conversations", headers=outsider).json()["total"] == 0

    # Unknown ids and unauthenticated calls never expose another user's thread.
    assert (
        client.get("/api/v1/chat/conversations/999999", headers=outsider).status_code == 404
    )
    assert client.get(f"/api/v1/chat/conversations/{conversation_id}").status_code == 401

    # Posting to someone else's conversation id is rejected.
    assert (
        _ask(
            client,
            outsider,
            "What are the symptoms of hypertension?",
            conversation_id=conversation_id,
        ).status_code
        == 404
    )

    # The owner's thread is untouched.
    detail = client.get(f"/api/v1/chat/conversations/{conversation_id}", headers=owner).json()
    assert len(detail["messages"]) == 1
    assert detail["title"] != "Hijacked"


def test_generated_titles_are_short_and_meaningful():
    from app.services.conversation_titles import generate_conversation_title

    assert (
        generate_conversation_title("What are the symptoms of hypertension?")
        == "Symptoms of hypertension"
    )
    assert (
        generate_conversation_title("Explain the difference between type 1 and type 2 diabetes.")
        == "Type 1 vs type 2 diabetes"
    )
    assert generate_conversation_title("Summarise my uploaded medical guidelines.") == (
        "Uploaded medical guidelines"
    )
    long_title = generate_conversation_title(
        "Please compare the recommendations for managing resistant hypertension in adults "
        "with chronic kidney disease across my uploaded cardiology and nephrology documents?"
    )
    assert len(long_title.split()) <= 7
    assert len(long_title) <= 64
    assert '"' not in long_title
    assert generate_conversation_title("   ??  ") == "New chat"
