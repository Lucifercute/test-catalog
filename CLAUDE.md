# Test Catalog

Product catalog: admin adds products via Telegram bot (photo + caption),
users browse them in a Next.js page that also runs as a Telegram Mini App.

## Architecture
- `backend/`  — FastAPI. The ONLY service that touches PostgreSQL and MinIO.
- `bot/`      — aiogram 3, webhook mode. Talks to backend over HTTP only.
- `frontend/` — Next.js 16 App Router (TypeScript 5.9 — Next doesn't officially support TS 6/7). Fetches data from backend.
- `infra/`    — infrastructure configs (`infra/Caddyfile`).
- Caddy (`caddy:2.11.7-alpine`) is the ONLY published entry point (`CADDY_HTTP_PORT`, default 8080;
  HTTP now, HTTPS at deploy). Backend has no host ports.
  - `/api/*` → backend, prefix stripped; `dynamic a backend 8000` makes each replica its own
    upstream, `round_robin`, no sticky sessions (passive health + `lb_retries`).
  - `/media/*` → MinIO `/$MINIO_BUCKET/*`, GET/HEAD only (else 405), query string dropped,
    `/media/` → 404 (the bucket's anonymous policy allows ListBucket; Caddy hides it).
  - `/tg/webhook` → bot replicas (`dynamic a bot 8080`, same balancing), POST only (else 405),
    path kept. The bot itself checks `X-Telegram-Bot-Api-Secret-Token` (401).
  - `/healthz` — Caddy's own healthcheck.
  - everything else (fallback `handle`) → frontend replicas (`dynamic a frontend 3000`, same balancing).
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
- Bot (`bot/`, aiohttp on :8080, 2 replicas, no host ports): `SimpleRequestHandler` with
  `handle_in_background=False` — the webhook answers only after the handler finishes, so a
  transient failure (backend down/5xx/429, Telegram network error) raises → 500 → Telegram
  redelivers (safe: `POST /products` is idempotent). Permanent errors (413/415/422/401) are
  answered to the admin and acked with 200; so are `TelegramForbiddenError`/`TelegramBadRequest`
  (narrow `router.errors` handler). Never add a catch-all errors handler — it would kill the retry.
  - No FSM (`Dispatcher(disable_fsm=True)`): admin sends photo + caption in one message.
  - Backend via Caddy (`BACKEND_URL=http://caddy/api`); httpx client created in `dp.startup`,
    kept in `dp["backend"]` (not a global). Photos downloaded into `BytesIO`, never to disk.
  - Router is built by `build_router()` (a Router attaches to one dispatcher only).
  - `bot-setup` (one-shot, `python -m app.setup`): `set_webhook` on `PUBLIC_BASE_URL/tg/webhook`
    with `secret_token`, commands (admins get `/new` via `BotCommandScopeChat`), Mini App menu
    button. Replicas never call `set_webhook`. Gets no `INTERNAL_TOKEN`.
  - Telegram needs HTTPS: `PUBLIC_BASE_URL`/`WEBAPP_URL` are https-only; locally use a tunnel.
- Frontend (`frontend/`, `next start` via standalone `server.js` on :3000, 2 replicas, no host ports):
  - `/` — server component, `dynamic = 'force-dynamic'`, `fetch` with `cache: 'no-store'` and a 5 s
    timeout (`lib/backend.ts`, `import 'server-only'`). `BACKEND_URL=http://caddy/api` is server-only,
    never `NEXT_PUBLIC_*`. Empty list → «Товаров пока нет»; backend error → message, page still 200.
  - Images: plain `<img src={image_url}>`, never `next/image` (its optimizer caches on each replica's
    disk; `images.unoptimized` too). `MEDIA_BASE_URL=/media` — page and images share Caddy's origin.
  - Telegram: `telegram-web-app.js` via `next/script` `beforeInteractive` in the root layout;
    `app/telegram-ready.tsx` calls `WebApp.ready()`; a no-op in a regular browser.
  - `/health` — liveness for the Docker healthcheck, doesn't call the backend.
  - Dockerfile: multi-stage, `output: 'standalone'`, runs as `node`, `HOSTNAME=0.0.0.0`.
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
- Everything goes through Caddy: `curl localhost:8080/` (catalog), `curl localhost:8080/api/health`, `curl localhost:8080/api/products`,
  `curl -I localhost:8080/media/products/1/1.jpg`.
- Backend (`cd backend`): `uv sync`; `uv run pytest` (needs Docker: testcontainers
  Postgres + MinIO, same images as compose); `uv run ruff check . && uv run ruff format --check .`;
  `uv run alembic revision -m "..."` for a new migration (needs only POSTGRES_* env).
- Bot (`cd bot`): `uv sync`; `uv run pytest` (no Docker, fake Bot API session + httpx
  MockTransport); `uv run ruff check . && uv run ruff format --check .`.
- Frontend (`cd frontend`): `npm ci`; `npm run typecheck && npm run build`;
  `BACKEND_URL=http://localhost:8080/api npm run dev` (needs compose running).
- `docker compose run --rm bot-setup` — re-register webhook/commands/menu (idempotent).
- After editing `infra/Caddyfile`: `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile`.
- Create a product by hand: `curl -H "X-Internal-Token: $INTERNAL_TOKEN" -F title=Mug
  -F chat_id=1 -F message_id=1 -F image=@mug.jpg localhost:8080/api/products`.

<!-- fill in as they appear -->

## Workflow
- For changes touching more than one service, propose a plan first.
- Before saying "done": run tests/linters for the touched service.
- Never commit or push without asking.
- Check current docs (context7) for aiogram 3 and Next.js APIs — they change often.
