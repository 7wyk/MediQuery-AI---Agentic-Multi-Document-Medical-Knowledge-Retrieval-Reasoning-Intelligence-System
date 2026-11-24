# MediQuery AI — Deployment Guide

Target architecture: **Vercel** (React SPA) → **Render** (FastAPI) → **Supabase** (PostgreSQL + pgvector + private Storage) → hosted AI APIs.

Everything below can be done on free tiers, with documented quotas and limits (§9).

---

## 1. Supabase setup

1. Create a project at https://supabase.com (choose the region closest to Render).
2. **Database connection string** — Project Settings → Database → Connect:
   - Prefer the **Session pooler** URI (IPv4-friendly, works from Render).
   - Format: `postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`
   - Set it as `DATABASE_URL` on Render. Never commit it.
3. **Enable pgvector** (the migration does this too, but the SQL editor is a good check):
   ```sql
   create extension if not exists vector;
   ```
4. **Create a private storage bucket**: Storage → New bucket → name `mediquery-documents` → **Public bucket: OFF**.
5. **Storage policies**: the backend uses the **service-role key** server-side only. Do not add a public `select` policy. If you later add direct browser access, use signed URLs (already implemented) or scoped RLS policies keyed on `auth.uid()`.
6. Copy `Project URL` and `service_role` key (Project Settings → API) into Render as `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. The service key must never reach the frontend.

### Tables / indexes

Created by the Alembic migration:
`users`, `documents`, `chunks`, `document_jobs`, `query_logs`, `usage_stats`, `tool_executions`, `evaluation_records`, `kg_entities`, `kg_relations`, plus an HNSW index on `(embedding::vector(768))`, a GIN full-text index on `chunks.content`, and `documents(user_id, status)`.

---

## 2. Database migrations

From `backend/` with the production `DATABASE_URL` exported:

```bash
pip install -r requirements.txt
alembic upgrade head
```

- The baseline migration creates the whole schema and enables pgvector.
- `EMBEDDING_DIMENSIONS` must match the dimension used when the index was created (default 768). Changing providers/dimensions requires a new migration that rebuilds the HNSW index and re-indexes documents.
- Do **not** rely on `Base.metadata.create_all()` in production; it only runs outside production for local convenience.
- Take a Supabase backup (Database → Backups) before running migrations on a database with real data.

### Migrating an existing SQLite/Pinecone deployment

```bash
cd backend
python scripts/import_legacy_sqlite.py --sqlite ../backend/mediquery.db --with-history
# add --dry-run first to preview
```

This copies users (roles are discarded) and optionally query history. Uploaded PDFs lived on local disk and Pinecone vectors used a different embedding model, so documents must be **re-uploaded and re-indexed** — the importer intentionally does not fabricate vectors.

---

## 3. Storage bucket

- Bucket `mediquery-documents`, private.
- Object keys are `user-<id>/<document-uuid>/<sanitised-filename>`, so interests never collide across users.
- Downloads use short-lived signed URLs (`SIGNED_URL_EXPIRES_SECONDS`, default 1 hour) after an ownership check.
- Deleting a document removes its chunks, graph rows, job rows and the stored object.

---

## 4. AI provider configuration

All providers are chosen through environment variables; the RAG pipeline is provider-agnostic (see `backend/app/providers`).

| Capability | Default | Free-tier notes (verify before relying on them) |
|---|---|---|
| Embeddings | Gemini `gemini-embedding-001`, 768 dims | Free tier has per-minute/per-day request limits; 768 dims reduces storage |
| LLM | Groq `openai/gpt-oss-120b` | Free tier is rate-limited by tokens/minute and requests/day |
| Reranking | Jina `jina-reranker-v2-base-multilingual` | Free trial key has a one-time token allowance and RPM limits |
| Reranking alt. | Cohere `v3.5` (`RERANK_PROVIDER=cohere`) | Trial keys are rate-limited (~10 rerank req/min) |
| Reranking fallback | `RERANK_PROVIDER=lexical` | Local scoring algorithm, no quota, lower quality |
| OCR | Gemini vision, or OCR.space (`OCR_PROVIDER=ocrspace`) | OCR.space free tier has monthly request and file-size limits |
| Vision / charts | Gemini `gemini-3.6-flash` | Same Gemini quotas as other calls |
| Web fallback | Europe PMC / PubMed | Free, no key; disabled by default |

Set in Render:

```
GEMINI_API_KEY=...
GROQ_API_KEY=...
JINA_API_KEY=...          # or COHERE_API_KEY
```

If a provider is missing, `/health` reports `configured: false` and document/chat calls return clear errors. **There is no silent fallback to a local model.**

Cost knobs: `COST_LLM_INPUT_PER_1M`, `COST_LLM_OUTPUT_PER_1M`, `COST_EMBEDDING_PER_1M`, `COST_RERANK_PER_1K` (defaults `0` = free tier). They only affect the *estimated* cost reported in analytics.

---

## 5. Render deployment (backend)

1. New → **Web Service** → connect the repo.
2. Root directory: `backend`.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"` (the `Procfile` contains the same).
5. Health check path: `/health`.
6. Environment: copy every value from `backend/.env.example` and fill real secrets. Minimum:
   - `ENVIRONMENT=production`
   - `DATABASE_URL` (Supabase pooler)
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET`, `STORAGE_BACKEND=supabase`
   - `JWT_SECRET` (≥32 random chars)
   - `CORS_ORIGINS=https://your-app.vercel.app`
   - `GEMINI_API_KEY`, `GROQ_API_KEY`, `JINA_API_KEY` (or Cohere)
   - leave `WEB_SEARCH_ENABLED=false` unless you explicitly want external fallback
7. Run migrations once from your machine (or a Render shell): `alembic upgrade head`.
8. Deploy and verify `https://<service>.onrender.com/health` returns `status: healthy`.

**Background processing.** The default is an in-process worker (`BACKGROUND_WORKER_ENABLED=true`) that polls `document_jobs` in PostgreSQL; it is safe across restarts and retries failures. If you scale to multiple instances, run **one** instance with the worker enabled and set `BACKGROUND_WORKER_ENABLED=false` on the others. Alternatives:
- Render **Background Worker** (paid plan): start command `python -m app.worker`, same env vars, worker enabled there and disabled on the web service.
- Render **Cron Job** (paid) or any external scheduler: `POST /api/v1/internal/jobs/run` with header `X-Worker-Token: $WORKER_TOKEN` (set `WORKER_TOKEN` first).

Render free web services sleep after inactivity; the first request after idle is slow. Free instances also restart periodically — the DB-backed job queue and Supabase storage make this safe.

---

## 6. Vercel deployment (frontend)

1. Import the repo, set **Root Directory** to `frontend`.
2. Framework preset: **Vite**. Build `npm run build`, output `dist`.
3. Environment variable: `VITE_API_BASE_URL=https://<your-render-service>.onrender.com` (no trailing slash).
4. `vercel.json` already rewrites all routes to `index.html` for React Router.
5. Deploy, then update Render's `CORS_ORIGINS` with the exact Vercel origin (scheme + host, no path) and redeploy the backend.

Never place provider keys or the Supabase service key in the frontend.

---

## 7. Production verification checklist

1. `GET /health` → `status: healthy`, database `ok`, expected providers `configured: true`.
2. Register two accounts; confirm `POST /documents/upload` with a PDF for user A, then `GET /documents` for user B returns 0 and direct access to A's document id returns 404.
3. Upload a programming `.txt` → status `rejected` with a reason; confirm no chunks exist (`chunk_count: 0`).
4. Upload a medical PDF → status progresses to `completed` with chunk count and progress 100.
5. Ask a medical question → answer includes document citations with page numbers; open a source and verify the page.
6. Ask an unrelated question (e.g. football) → rejection message, `evidence_status: rejected_domain`, no sources.
7. Ask something not covered by the documents → `insufficient_evidence: true`, answer abstains (`Sorry, I don't know.`).
8. Clear chat → `GET /chat/history` returns `total: 0`.
9. Delete a document → chunks gone, object gone from the Supabase bucket, citations no longer reference it.
10. `GET /analytics/observability` shows latency, tokens, abstention rate.
11. Restart the Render service mid-processing → the job resumes from PostgreSQL (attempts/progress persisted).
12. Foreign-origin request returns no CORS headers (only `CORS_ORIGINS` is allowed).

---

## 8. Environment variables

Full annotated list: `backend/.env.example`. Key groups: runtime, database, Supabase/storage, JWT, CORS/rate limits, ingestion limits, hosted AI providers, retrieval/agentic RAG, web fallback, graph RAG, background jobs, observability/cost. No real secrets belong in the file — only placeholders.

---

## 9. Free-tier limits & remaining limitations

- **AI quotas are finite.** Gemini, Groq, Jina and Cohere free tiers impose per-minute and per-day caps. Multi-page scanned uploads consume OCR/vision calls; `MAX_OCR_PAGES`, `MAX_IMAGE_ANALYSIS_PER_DOCUMENT` and `MAX_CHUNKS_PER_DOCUMENT` bound this, but a busy free-tier deployment will hit 429s. The app surfaces a clear 503/error rather than switching to a local model.
- **Reranker quality.** If no hosted reranker key is configured, the deterministic lexical reranker is used (reported as `reranker: lexical`). It is not a cross-encoder and is weaker for synonyms/abbreviations.
- **Web fallback is opt-in.** Europe PMC only; WHO/CDC pages are not crawled. External evidence is always labelled and never merged silently with your documents.
- **Graph RAG is per-user and best-effort.** Extraction is one LLM call per ingested document; failures do not block indexing. It supplements, never replaces, document retrieval.
- **Rate limiting is in-memory** (single instance). For multiple instances, move it to a shared store (Upstash/Redis or a Postgres table).
- **In-process worker** runs inside the web service by default. Multi-instance deployments need a single worker process or the cron trigger; Render background workers/cron are paid features.
- **Claim verification and grading consume LLM calls** in addition to answering. Disable `ENABLE_CLAIM_VERIFICATION` only if you accept unverified answers (they are then marked `unverified`).
- **Chart understanding** depends on the vision model and image quality; charts are represented as textual descriptions plus a vision-derived label block, not as a structured chart object.
- **PDF rendering/OCR** uses PyMuPDF + hosted OCR; very large or image-only PDFs are truncated at configured page/OCR limits.
- **Evaluation needs indexed documents** and calls the real pipeline; run it against a funded/quota-available key, not during production traffic.
