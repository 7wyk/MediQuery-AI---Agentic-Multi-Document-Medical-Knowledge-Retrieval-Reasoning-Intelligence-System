# MediQuery AI — Cloud Medical RAG

MediQuery AI is a production-oriented, medical-domain RAG application. It ingests medical documents, stores them privately in Supabase Storage, indexes hybrid vectors + full-text search in Supabase PostgreSQL, and answers questions with a self-correcting (CRAG + Self-RAG) pipeline that grades evidence, verifies claims and abstains instead of guessing.

**Stack:** FastAPI · SQLAlchemy/Alembic · Supabase (PostgreSQL + pgvector + Storage) · React 18 + TypeScript + Vite · hosted AI APIs (Gemini embeddings/vision, Groq LLM, Jina/Cohere reranking).

> MediQuery AI supports medical professionals. It is **not** a medical device, does not diagnose or prescribe, and never replaces clinical judgement.

## Architecture

```
Vercel (React SPA)  ──HTTPS/Bearer JWT──▶  Render (FastAPI)
                                            │
                     ┌──────────────────────┼───────────────────────┐
                     ▼                      ▼                       ▼
             Supabase PostgreSQL      Supabase Storage        Hosted AI APIs
             users, documents,        private bucket,         embeddings (Gemini)
             chunks + pgvector,       signed URLs             LLM (Groq)
             jobs, graph, telemetry                           rerank (Jina/Cohere)
                                                              OCR/vision (Gemini/OCR.space)
                                                              web fallback (Europe PMC)
```

### Request pipeline

1. Medical-domain gatekeeper rejects non-medical questions before answering.
2. Query rewriting, multi-query generation and medical abbreviation expansion.
3. Hybrid retrieval: pgvector cosine search + PostgreSQL full-text search, fused with Reciprocal Rank Fusion, filtered by `user_id` and optional `document_id`.
4. Hosted reranker reorders candidates; evidence grader decides sufficiency (CRAG).
5. Corrective retry with a refined query (bounded by `AGENT_MAX_ATTEMPTS`).
6. Optional trusted web fallback (Europe PMC / PubMed) only when documents are insufficient; results are labelled external.
7. Grounded generation with numbered citations (document, page, table/chart, or external URL).
8. Claim-level verification; unsupported sentences are removed; if nothing verifiable remains the answer is `Sorry, I don't know.`
9. Full tracing: stage latencies, tokens, estimated cost, retries and errors are persisted.

### Ingestion pipeline

Upload → signature-based type detection → private Supabase Storage → durable DB job → medical validation → extraction (text, tables, charts, OCR/vision) → structure-aware chunking → hosted embeddings → pgvector + full-text index → knowledge-graph extraction → status/progress updated. Jobs retry and are safe across restarts.

## Features

- **One account type** — no doctor/student roles; every user sees only their own data.
- **Medical gatekeeper** — content-based screening for documents and questions, with LLM escalation for borderline material.
- **Multimodal ingestion** — PDF (text/scanned), DOCX, XLSX, CSV, TXT, JPG/JPEG/PNG; tables keep headers, charts are interpreted by a hosted vision model.
- **Hybrid search + RRF + reranking** — better recall for drug names, abbreviations and numbers.
- **Self-correcting RAG** — evidence grading, query refinement, bounded retries, abstention.
- **Evidence citations** — claim-level mapping to document/page/table or external URL.
- **Trusted web fallback** — Europe PMC (PubMed/MEDLINE), clearly marked as external and off by default.
- **Graph RAG** — entities/relations extracted from your own documents for multi-hop context.
- **Controlled tools / MCP-style endpoint** — allow-listed PubMed, openFDA drug labels and ICD-10 lookups with validation, timeouts and traces.
- **Observability** — request IDs, stage latencies, token usage, cost estimates, retry counts, processing status.
- **Evaluation** — reproducible dataset and metrics for retrieval, groundedness, citation correctness and hallucination rate.

## Local development

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in keys; SQLite + local storage work for dev
python -m uvicorn app.main:app --reload
```

- API docs: http://localhost:8000/api/docs
- Health: http://localhost:8000/health (shows which providers are configured, never keys)

Local development defaults to SQLite and `STORAGE_BACKEND=local`. Production validates and rejects both. Tables are created automatically **only** outside production; production uses Alembic.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env      # VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

## Tests

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q      # 27 tests, no external API calls
cd ../frontend
npm run build
```

Backend tests replace every hosted provider with deterministic fakes and use temporary SQLite + local storage.

### RAG evaluation

```bash
cd backend
python -m app.evaluation.runner --user-email you@example.com --output app/evaluation/reports/latest.json
```

Upload the files in `demo/` first. Metrics include retrieval precision/recall, context relevance, answer relevance, faithfulness, groundedness, citation correctness and hallucination rate.

## API overview

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/auth/register` | Create a unified account |
| POST | `/api/v1/auth/login` / `/refresh` | JWT access + refresh tokens |
| GET | `/api/v1/auth/me` | Current profile |
| POST | `/api/v1/documents/upload` | Upload and queue multimodal documents |
| GET | `/api/v1/documents` | List owned documents |
| GET | `/api/v1/documents/{id}/status` | Processing progress/status |
| GET | `/api/v1/documents/{id}/download` | Short-lived signed URL |
| POST | `/api/v1/documents/{id}/reindex` | Queue re-indexing |
| DELETE | `/api/v1/documents/{id}` | Delete chunks, graph data and stored object |
| POST | `/api/v1/chat/query` | Hybrid + self-correcting RAG answer |
| POST | `/api/v1/chat/query-multilang` | Translate → RAG → translate back |
| GET/DELETE | `/api/v1/chat/history` | History (delete clears it) |
| GET | `/api/v1/analytics/overview` | Usage summary |
| GET | `/api/v1/analytics/observability` | Latency, tokens, cost, abstention |
| GET | `/api/v1/analytics/processing-status` | Job/document status |
| GET | `/api/v1/tools`, POST `/api/v1/mcp` | Approved tool manifests / MCP JSON-RPC |
| POST | `/api/v1/internal/jobs/run` | Worker-token job trigger |

## Documentation

- `DEPLOYMENT.md` — Supabase, migrations, storage bucket, AI keys, Render, Vercel, verification and troubleshooting.
- `backend/.env.example` — every environment variable with a safe placeholder.

## Known limitations

See `DEPLOYMENT.md` §9: free-tier AI quotas are rate-limited; the in-memory rate limiter and in-process worker are per-instance; the lexical reranker fallback is weaker than a hosted cross-encoder; scanned PDF OCR is capped per document to control cost.
