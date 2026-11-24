from __future__ import annotations

import asyncio
import pathlib
import uuid

MEDICAL_TEXT = (
    "Diabetes Management Guideline\n\n"
    "Diabetes mellitus is a chronic metabolic disease. Common symptoms include "
    "increased thirst, frequent urination, fatigue and unexplained weight loss. "
    "Diagnosis uses fasting plasma glucose and HbA1c. Treatment includes dietary "
    "changes, exercise and medication such as metformin or insulin. Patients with "
    "hypertension and diabetes require regular blood pressure and glucose monitoring."
)

CODE_TEXT = (
    "def reverse_list(items):\n"
    "    import os\n"
    "    class Node:\n"
    "        def __init__(self, value):\n"
    "            self.value = value\n"
    "    return items[::-1]\n"
    "const server = require('http');\n"
    "npm install react typescript docker kubernetes\n"
)


def _register_and_login(client):
    email = f"doc-{uuid.uuid4().hex[:8]}@example.com"
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "securepass123", "full_name": "Doc Owner"},
    )
    assert register.status_code == 201, register.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "securepass123"})
    return email, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _run_jobs(limit: int = 5) -> int:
    from app.services.jobs import process_pending_jobs_once

    return asyncio.run(process_pending_jobs_once(limit=limit))


def _upload(client, headers, filename: str, content: bytes):
    return client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files=[("files", (filename, content, "text/plain"))],
    )


def test_upload_index_and_query_flow(client):
    _, headers = _register_and_login(client)

    response = _upload(client, headers, "diabetes.txt", MEDICAL_TEXT.encode())
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["documents"]) == 1
    document_id = body["documents"][0]["id"]
    assert body["documents"][0]["status"] == "queued"

    processed = _run_jobs(1)
    assert processed == 1

    status_response = client.get(f"/api/v1/documents/{document_id}/status", headers=headers)
    document = status_response.json()
    assert document["status"] == "completed", document
    assert document["chunk_count"] >= 1
    assert document["progress"] == 100

    from app.database import SessionLocal
    from app.models.chunk import DocumentChunk

    with SessionLocal() as db:
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).all()
        assert chunks, "chunks should be indexed"
        assert all(chunk.user_id is not None for chunk in chunks)
        assert all(chunk.embedding for chunk in chunks)

    chat = client.post(
        "/api/v1/chat/query",
        headers=headers,
        json={"question": "What are the symptoms of diabetes?", "mode": "agentic"},
    )
    assert chat.status_code == 200, chat.text
    answer = chat.json()
    assert answer["answer"]
    assert answer["sources"], "grounded answers must include citations"
    assert answer["sources"][0]["kind"] == "document"
    assert answer["sources"][0]["filename"] == "diabetes.txt"
    assert answer["agent_metadata"]["latency_ms"]["total_ms"] >= 0

    history = client.get("/api/v1/chat/history", headers=headers).json()
    assert history["total"] >= 1

    cleared = client.delete("/api/v1/chat/history", headers=headers)
    assert cleared.status_code == 200
    assert client.get("/api/v1/chat/history", headers=headers).json()["total"] == 0


def test_non_medical_document_is_rejected_without_vectors(client):
    _, headers = _register_and_login(client)
    response = _upload(client, headers, "code.txt", CODE_TEXT.encode())
    assert response.status_code == 200
    document_id = response.json()["documents"][0]["id"]
    _run_jobs(1)

    document = client.get(f"/api/v1/documents/{document_id}/status", headers=headers).json()
    assert document["status"] == "rejected"
    assert document["rejection_reason"]
    assert document["chunk_count"] == 0

    from app.database import SessionLocal
    from app.models.chunk import DocumentChunk

    with SessionLocal() as db:
        assert db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).count() == 0


def test_non_medical_query_is_rejected_before_rag(client):
    _, headers = _register_and_login(client)
    response = client.post(
        "/api/v1/chat/query",
        headers=headers,
        json={"question": "Write a Python function that reverses a linked list."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["evidence_status"] == "rejected_domain"
    assert body["insufficient_evidence"] is True
    assert body["sources"] == []
    assert "medicine" in body["answer"].lower()


def test_reindex_creates_no_duplicate_chunks(client):
    _, headers = _register_and_login(client)
    response = _upload(client, headers, "guideline.txt", MEDICAL_TEXT.encode())
    document_id = response.json()["documents"][0]["id"]
    _run_jobs(1)

    from app.database import SessionLocal
    from app.models.chunk import DocumentChunk

    with SessionLocal() as db:
        first_count = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id
        ).count()

    reindex = client.post(f"/api/v1/documents/{document_id}/reindex", headers=headers)
    assert reindex.status_code == 200
    _run_jobs(1)

    with SessionLocal() as db:
        second_count = db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id
        ).count()
    assert first_count == second_count


def test_delete_removes_chunks_and_storage_object(client):
    _, headers = _register_and_login(client)
    response = _upload(client, headers, "to-delete.txt", MEDICAL_TEXT.encode())
    document_id = response.json()["documents"][0]["id"]
    _run_jobs(1)

    from app.config import get_settings
    from app.database import SessionLocal
    from app.models.chunk import DocumentChunk
    from app.models.document import Document

    with SessionLocal() as db:
        document = db.get(Document, document_id)
        storage_path = document.storage_path
    stored_file = pathlib.Path(get_settings().storage_local_dir) / storage_path
    assert stored_file.exists()

    deleted = client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    assert deleted.status_code == 200
    assert not stored_file.exists()

    with SessionLocal() as db:
        assert db.get(Document, document_id) is None
        assert db.query(DocumentChunk).filter(
            DocumentChunk.document_id == document_id
        ).count() == 0


def test_upload_rejects_unsupported_archive(client):
    _, headers = _register_and_login(client)
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files=[("files", ("payload.pdf", b"PK\x03\x04not-a-docx", "application/pdf"))],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["documents"] == []
    assert body["rejected"][0]["reason"]
