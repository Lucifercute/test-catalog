# Test Catalog

Product catalog: admin adds products via Telegram bot (photo + caption),
users browse them in a Next.js page that also runs as a Telegram Mini App.

## Architecture
- `backend/`  — FastAPI. The ONLY service that touches PostgreSQL and MinIO.
- `bot/`      — aiogram 3, webhook mode. Talks to backend over HTTP only.
- `frontend/` — Next.js App Router. Fetches data from backend.
- `infra/`    — infrastructure configs (`infra/Caddyfile`).
- Caddy (`caddy:2.11.7-alpine`) is the ONLY published entry point (`CADDY_HTTP_PORT`, default 8080;
  HTTP now, HTTPS at deploy). Backend has no host ports.
  - `/api/*` → backend, prefix stripped; `dynamic a backend 8000` makes each replica its own
    upstream, `round_robin`, no sticky sessions (passive health + `lb_retries`).
  - `/media/*` → MinIO `/$MINIO_BUCKET/*`, GET/HEAD only (else 405), query string dropped,
    `/media/` → 404 (the bucket's anonymous policy allows ListBucket; Caddy hides it).
  - `/healthz` — Caddy's own healthcheck.
- `compose.yaml` (repo root) — all services; `docker compose up -d` reads `.env` from root.
  - MinIO images are `pgsty/minio` / `pgsty/mc` (official minio/* images are no longer published).
  - One-shot `minio-init` creates `$MINIO_BUCKET` with anonymous read; app services
    should depend on it with `condition: service_completed_successfully`.
- Flow: bot → POST /products (multipart) → backend → MinIO (image) + Postgres (row).
- `POST /products` (bot only): multipart `title`, `image`, `chat_id`, `message_id`;
  header `X-Internal-Token` (= `INTERNAL_TOKEN`). Responses: 201 created, 200 already exists
  (same `(chat_id, message_id)`), 401 bad token, 413 > `MAX_IMAGE_BYTES`, 415 not jpeg/png/webp
  (Content-Type must match magic bytes), 422 bad title (1-255 chars after strip).
  Image key: `products/{chat_id}/{message_id}.{ext}`.
- Backend S3 client: aiobotocore, one per process, created in lifespan → `app.state.s3`.
- Settings: `DatabaseSettings` (POSTGRES_* only; used by alembic) ⊂ `Settings` (app).
  `migrate` gets only POSTGRES_* (`x-db-env` in compose) — least privilege.

## Hard rules (graded strictly)
Every service must run as multiple replicas at once:
- No in-process state: no globals as caches, no local files, no in-memory FSM.
- Bot uses webhooks, never polling (polling breaks with >1 replica).
- Product creation is idempotent: unique (chat_id, message_id).
- DB migrations run in a separate one-shot `migrate` service, never on app startup.
- Store only the MinIO object key in DB; images are served via `/media/*`.

## Stack conventions
- Python 3.12, async everywhere, SQLAlchemy 2.0 (async), Pydantic v2, Alembic.
- Config only via env vars (pydantic-settings); `.env.example` lists all of them.
- Next.js: TypeScript, server components, `dynamic = 'force-dynamic'` for catalog.
- No styling needed — plain markup is acceptable per the task.

## Commands
- `cp .env.example .env` — first-time setup.
- `docker compose up -d` / `docker compose ps -a` / `docker compose down`.
- `docker compose up -d --build backend` — rebuild backend (migrate runs first).
- `docker compose run --rm migrate` — apply migrations manually (idempotent).
- Everything goes through Caddy: `curl localhost:8080/api/health`, `curl localhost:8080/api/products`,
  `curl -I localhost:8080/media/products/1/1.jpg`.
- Backend (`cd backend`): `uv sync`; `uv run pytest` (needs Docker: testcontainers
  Postgres + MinIO, same images as compose); `uv run ruff check . && uv run ruff format --check .`;
  `uv run alembic revision -m "..."` for a new migration (needs only POSTGRES_* env).
- Create a product by hand: `curl -H "X-Internal-Token: $INTERNAL_TOKEN" -F title=Mug
  -F chat_id=1 -F message_id=1 -F image=@mug.jpg localhost:8080/api/products`.

<!-- fill in as they appear -->

## Workflow
- For changes touching more than one service, propose a plan first.
- Before saying "done": run tests/linters for the touched service.
- Never commit or push without asking.
- Check current docs (context7) for aiogram 3 and Next.js APIs — they change often.
