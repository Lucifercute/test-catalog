# Test Catalog

Product catalog: admin adds products via Telegram bot (photo + caption),
users browse them in a Next.js page that also runs as a Telegram Mini App.

## Architecture
- `backend/`  — FastAPI. The ONLY service that touches PostgreSQL and MinIO.
- `bot/`      — aiogram 3, webhook mode. Talks to backend over HTTP only.
- `frontend/` — Next.js App Router. Fetches data from backend.
- `infra/`    — docker-compose, Caddy (HTTPS + load balancing).
- Flow: bot → POST /products (multipart) → backend → MinIO (image) + Postgres (row).

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
<!-- fill in as they appear -->

## Workflow
- For changes touching more than one service, propose a plan first.
- Before saying "done": run tests/linters for the touched service.
- Never commit or push without asking.
- Check current docs (context7) for aiogram 3 and Next.js APIs — they change often.
