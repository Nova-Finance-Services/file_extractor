# Flask worker environment variables

All variables for `extractor-server` as of the current codebase (file extraction + chatbot document processing + R2R accounting agent). Copy `env.example` to `.env` for **Flask**. Copy `env.celery.example` for the **Celery worker**.

Flask only authenticates HTTP and pushes a task onto Redis. It does **not** call Exact, OpenAI, Anthropic, or Supabase. Do not put those secrets on the web service.

Values are never committed. This file documents **names, purpose, defaults, and which process needs them**.

**Auth naming:** this worker reads `FILE_EXTRACTOR_KEY`. Nova Edge secrets use `FILE_EXTRACTOR_API_KEY` (and optionally `ACCOUNTING_AGENT_FLASK_API_KEY`). Those three strings must match.

---

## Required by role

| Role | Must set |
|------|----------|
| **Web (Gunicorn)** | `FILE_EXTRACTOR_KEY`. Redis URL if enqueue routes are used. |
| **Celery worker** | Same `FILE_EXTRACTOR_KEY`, Redis URL, plus domain vars below. |
| **Chatbot worker jobs** | `OPENAI_API_KEY`, `DEV_SUPABASE_FUNCTIONS_URL` / `PROD_SUPABASE_FUNCTIONS_URL`, Exact token passed in the request body (not env). `SPACE_OCR_KEY` if OCR fallback is needed. |
| **R2R accounting agent worker jobs** | `SUPABASE_SERVICE_ROLE_KEY` (or per-env override), `DEV_SUPABASE_FUNCTIONS_URL` / `PROD_SUPABASE_FUNCTIONS_URL`, `EXACT_CLIENT_ID`, `EXACT_CLIENT_SECRET`, `OPENAI_API_KEY` and/or `ANTHROPIC_API_KEY`. |

If `FILE_EXTRACTOR_KEY` is empty, HTTP auth is **disabled** on every protected route. Do not run production that way.

Tuning knobs (models, delays, file size, Celery timeouts) are **code constants**, not env. See the table at the bottom.

---

## HTTP / file extraction

| Variable | Required | Default | Used by | Description |
|----------|----------|---------|---------|-------------|
| `FILE_EXTRACTOR_KEY` | **Yes (prod)** | empty (auth off) | Web + worker | Bearer token for `/extract`, `/extract-base64`, `/chatbot-document-processing`, `/r2r/accounting-agent/enqueue`. Chatbot worker also sends this key to `chatbot-document-processing-log`. Must equal Edge `FILE_EXTRACTOR_API_KEY`. |
| `PORT` | No | `5000` | Web (`python app.py` only) | Listen port. Render/Gunicorn usually injects `PORT`. |
| `FLASK_DEBUG` | No | `false` | Web (`python app.py` only) | Set `true` to enable Flask debug. Never in production. |

`MAX_FILE_SIZE` (50 MB) and `REQUEST_TIMEOUT` (30s) are constants in `fileExtraction/config.py`.

---

## Celery / Redis

This repo is **one worker service**, not a pool of many Render workers.

| What | Default in this codebase |
|------|--------------------------|
| Render worker processes | **1** service (`celery -A celery_app worker`) |
| `--concurrency` | **2** (two child processes inside that service) |
| Tasks in flight | **2** (one per child). Extra orgs wait in Redis. |
| Prefetch | `1` (constant in `celery_app.py`) |

R2R enqueue puts **one Celery task per organization**. Chatbot document processing is still one task per org batch (already that shape).

Do not raise `--concurrency` without watching Exact + LLM rate limits; two orgs in parallel is the intended cap.

| Variable | Required | Default | Used by | Description |
|----------|----------|---------|---------|-------------|
| `CELERY_BROKER_URL` | **Yes** if enqueue is used | — | Web + worker | Redis broker URL. Preferred over `REDIS_URL`. |
| `REDIS_URL` | Fallback | `redis://localhost:6379/0` | Web + worker | Used when `CELERY_BROKER_URL` is unset. Render Redis add-on typically sets this. |
| `CELERY_RESULT_BACKEND` | No | same as broker | Web + worker | Where Celery stores task results. |

Global Celery kill (300s) and prefetch (1) are constants in `celery_app.py`. Chatbot and R2R tasks set their own longer limits in code.

---

## Shared Supabase (dev / prod)

These URLs are the **Supabase project origin** (e.g. `https://xxxx.supabase.co`), not the `/functions/v1/...` path.

| Variable | Required | Default | Used by | Description |
|----------|----------|---------|---------|-------------|
| `DEV_SUPABASE_FUNCTIONS_URL` | **Yes** for `environment=dev` jobs | empty | **Worker** | Dev project URL. Chatbot uses it to POST processing logs. R2R uses `{url}/rest/v1/...` (PostgREST). |
| `PROD_SUPABASE_FUNCTIONS_URL` | **Yes** for `environment=prod` jobs | empty | **Worker** | Prod project URL. Same usage as dev. |
| `SUPABASE_SERVICE_ROLE_KEY` | **Yes for R2R** | empty | **Worker** (R2R) | Service-role JWT for PostgREST (`connections`, `p2p_settings`, `o2c_settings`, `agent_memory`, …). **High privilege.** Do not put this on Flask. |
| `DEV_SUPABASE_SERVICE_ROLE_KEY` | No | falls back to `SUPABASE_SERVICE_ROLE_KEY` | **Worker** (R2R) | Optional override when `environment=dev`. |
| `PROD_SUPABASE_SERVICE_ROLE_KEY` | No | falls back to `SUPABASE_SERVICE_ROLE_KEY` | **Worker** (R2R) | Optional override when `environment=prod`. |

Chatbot document processing does **not** need the service-role key (it uses the Exact access token from the request and logs via the Edge function + `FILE_EXTRACTOR_KEY`).

---

## Chatbot document processing

Celery task `tasks.process_chatbot_documents`. Time limits default to 15 minutes.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | **Yes** for summarization | empty | OpenAI key used to summarize extracted attachment text. |
| `SPACE_OCR_KEY` | No | empty | OCR.space key when PDF/image text extraction is empty. |
| `EXACT_API_BASE_URL` | No | `https://start.exactonline.nl/api` | Exact Online API origin (no trailing `/v1/...`). Shared with R2R. |

Chatbot model, pacing, retries, remaining-count, and task timeouts are constants in `chatbot/config.py` and `provider/exact/const.py` (`OPENAI_MODEL_SMALL`, `DOCUMENT_PROCESSING_*`, `EXACT_DOCUMENT_API_MIN_INTERVAL_MS`, `EXACT_API_MAX_RETRIES`, `CHATBOT_TASK_*`).

---

## R2R accounting agent

Celery task `tasks.process_accounting_agent_job` (one task per organization). Runs the Python agent in-process (Exact + LLM + `agent_memory`). It does **not** call the Edge agent. Default time limit is **2 hours**.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EXACT_CLIENT_ID` | **Yes** to refresh tokens | empty | Exact OAuth app client id. Used when `connections.expires_at` is in the past. |
| `EXACT_CLIENT_SECRET` | **Yes** to refresh tokens | empty | Exact OAuth app client secret. |
| `EXACT_TOKEN_URL` | No | `{EXACT_API_BASE_URL}/oauth2/token` | Token endpoint. Override only if Exact uses a non-default host. |
| `OPENAI_API_KEY` | **Yes** (or Anthropic) | empty | Primary LLM for the agent tool loop. |
| `ANTHROPIC_API_KEY` | Recommended failover | empty | Failover LLM. Called via HTTPS (`api.anthropic.com`); no extra Python package. |

Model IDs, Celery time limits, and supplier-run gap are **code constants** in `r2r/config.py` (`OPENAI_MODEL_COMPLEX`, `OPENAI_MODEL_MEDIUM`, `CLAUDE_MODEL_*`, `ACCOUNTING_AGENT_TASK_*`, `SUPPLIER_RUN_GAP_SECONDS`). Change them there, not in `.env`.

---

## Not used by this Flask process

These appear in Nova Edge / cron, or were leftover in older Python config. They are **not** read by the Flask worker.

| Variable | Where it actually lives | Description |
|----------|-------------------------|-------------|
| `FILE_EXTRACTOR_URL` | Nova Edge | Base URL of this Flask app (`https://….onrender.com`). |
| `FILE_EXTRACTOR_API_KEY` | Nova Edge | Same value as this worker’s `FILE_EXTRACTOR_KEY`. |
| `ACCOUNTING_AGENT_FLASK_URL` | Nova Edge (optional) | Dedicated override; falls back to `FILE_EXTRACTOR_URL`. |
| `ACCOUNTING_AGENT_FLASK_API_KEY` | Nova Edge (optional) | Dedicated override; falls back to `FILE_EXTRACTOR_API_KEY`. |
| `ENVIRONMENT` | Nova Edge | `dev` or `prod`. Sent to Flask in the JSON body as `environment`, not read from Flask env. |
| `CRON_SECRET` | Nova Edge | Auth for `r2r-accounting-agent-cron`. Flask uses `FILE_EXTRACTOR_KEY` instead. |
| `PYTHON_VERSION` | Render `render.yaml` | Build-time Python version (`3.11.0`). Not read by app code. |

---

## Minimal `.env` examples

### Flask web

```env
FILE_EXTRACTOR_KEY=replace-me
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

### Celery worker (chatbot + R2R)

```env
FILE_EXTRACTOR_KEY=replace-me
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
DEV_SUPABASE_FUNCTIONS_URL=https://your-dev.supabase.co
PROD_SUPABASE_FUNCTIONS_URL=https://your-prod.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...
EXACT_CLIENT_ID=
EXACT_CLIENT_SECRET=
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
SPACE_OCR_KEY=
```

---

## Related Nova Edge secrets

Set on the **Backend** Supabase project so cron can enqueue this worker:

```env
FILE_EXTRACTOR_URL=https://your-flask-host
FILE_EXTRACTOR_API_KEY=same-as-FILE_EXTRACTOR_KEY
# optional dedicated names:
# ACCOUNTING_AGENT_FLASK_URL=
# ACCOUNTING_AGENT_FLASK_API_KEY=
CRON_SECRET=
ENVIRONMENT=prod
```

---

## Code constants (not env)

| Constant | Value | File |
|----------|-------|------|
| `MAX_FILE_SIZE` | 50 MB | `fileExtraction/config.py` |
| `REQUEST_TIMEOUT` | 30s | `fileExtraction/config.py` |
| Celery global `task_time_limit` / soft / prefetch | 300s / 270s / 1 | `celery_app.py` |
| `OPENAI_MODEL_SMALL` | `gpt-4o-mini` | `chatbot/config.py` |
| `DOCUMENT_PROCESSING_COUNT_REMAINING` | `True` | `chatbot/config.py` |
| `CHATBOT_TASK_TIME_LIMIT` / soft | 900s / 840s | `chatbot/config.py` |
| `EXACT_API_MAX_RETRIES` | 3 | `provider/exact/const.py` |
| `EXACT_DOCUMENT_API_MIN_INTERVAL_MS` | 900 | `provider/exact/const.py` |
| `DOCUMENT_PROCESSING_API_DELAY_MS` | 800 | `provider/exact/const.py` |
| `OPENAI_MODEL_COMPLEX` / `MEDIUM` | `gpt-5.4` / `gpt-5-mini` | `r2r/config.py` |
| `ACCOUNTING_AGENT_TASK_TIME_LIMIT` / soft | 7200s / 6900s | `r2r/config.py` |
| `SUPPLIER_RUN_GAP_SECONDS` | 0.75 | `r2r/config.py` |
