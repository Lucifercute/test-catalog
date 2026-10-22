# Stateless checklist — details and fixes

Contents:
1. Globals and in-memory caches
2. Local filesystem writes
3. aiogram: polling, FSM storage, webhook
4. In-memory sessions and rate limits
5. Migrations on startup
6. Idempotency on redelivery
7. Hardcoded hosts/ports
8. Next.js caching across instances
9. Compose / infra

---

## 1. Globals and in-memory caches

**Bug:** module-level mutable containers written at runtime and read later
(`_cache = {}`, `seen_ids = set()`, `counter = 0` + `global counter`), class attributes used
as storage, `functools.lru_cache`/`cache`/`cachetools`/`aiocache` with memory backend on
anything that depends on DB data, `asyncio.Lock()` used to serialize work *across requests*
(only serializes within one process). JS/TS: module-level `Map`/`let` caches in route
handlers or server components.

**OK:** constants, `settings`, loggers, compiled regex, connection pools/engines/clients
created once per process, `lru_cache` on pure functions of their arguments (e.g. `get_settings()`).

**Fix:** delete the cache and query Postgres (usually fast enough), or move it to Redis
with a TTL. Cross-replica mutual exclusion → Postgres advisory lock / `SELECT ... FOR UPDATE`
/ unique constraint, or Redis lock.

## 2. Local filesystem writes

**Bug:** `open(..., "w"/"a"/"wb")`, `aiofiles.open` for write, `Path.write_*`, `shutil.copy`,
`UploadFile` saved to disk, `tempfile` that outlives the request, `os.makedirs("uploads")`,
SQLite files, `fs.writeFile*` in Next.js, bot downloading photos to disk then reading them
in another request. Compose: bind mounts / named volumes on app services for data.

**OK:** a `tempfile` created and deleted within the same request; logs to stdout.

**Fix:** images → stream to MinIO via backend, store only the object key in DB, serve via
`/media/*`. Bot: `bot.download(file, destination=BytesIO())` and send bytes in the multipart
POST — never touch disk. Logs → stdout.

## 3. aiogram: polling, FSM storage, webhook

**Critical:**
- `dp.start_polling(...)` / `run_polling` / `executor.start_polling` — Telegram allows one
  `getUpdates` consumer; replicas get `Conflict: terminated by other getUpdates request`.
  Fix: webhook (`SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=...)` mounted on
  aiohttp, or feed updates from FastAPI via `dp.feed_webhook_update(bot, update)`).
- `Dispatcher()` without `storage=` → `MemoryStorage`; explicit `MemoryStorage()` same.
  Step 1 of a scenario on replica A, step 2 on replica B → state lost.
  Fix: `storage=RedisStorage.from_url(settings.redis_url)` (add Redis to compose + `.env.example`),
  or avoid FSM entirely (single message = photo + caption, as this project does).
- Any per-user dict in the bot (`pending_uploads[user_id] = ...`) — same as FSM.

**Warning:**
- `set_webhook` called on startup by every replica — harmless if idempotent (same URL,
  `drop_pending_updates=False`!). `drop_pending_updates=True` on every replica start drops
  real updates during rolling restarts. Better: one-shot `bot-setup` service or guard.
- No `secret_token` → anyone can POST fake updates to the webhook.
- `handle_in_background=True` (default) answers 200 immediately; if the replica dies
  mid-processing, Telegram won't redeliver. Acceptable, but then processing must be idempotent
  and the user must be able to resend.

## 4. In-memory sessions and rate limits

**Bug:** session dicts, `starlette` `SessionMiddleware` storing server-side state in memory
(cookie-signed is fine *if* `SECRET_KEY` comes from env and is the same on all replicas),
`slowapi`/`limits` with default `memory://` storage, hand-written `defaultdict` counters,
aiogram throttling middleware keeping timestamps in a dict, Next.js middleware with a `Map`
rate limiter. Per-replica limit = N× intended; sessions randomly "log out".

**Fix:** `slowapi` `Limiter(storage_uri=settings.redis_url)`; Redis `INCR`+`EXPIRE`;
or rate-limit at Caddy. Secrets (JWT/session keys) from env, identical on all replicas —
never `secrets.token_hex()` at startup.

## 5. Migrations on startup

**Bug:** `alembic upgrade head` in app `command`/entrypoint/Dockerfile `CMD`,
`command.upgrade(...)` or `Base.metadata.create_all` in FastAPI `lifespan`/`startup`,
`prisma migrate deploy` / `next build` steps doing DB work at container start.
N replicas race on DDL; a failing migration crash-loops every replica.

**Fix:** one-shot `migrate` service in compose (same backend image,
`command: alembic upgrade head`, `restart: "no"`, depends on postgres healthy); backend
`depends_on: migrate: condition: service_completed_successfully`.

## 6. Idempotency on redelivery

Telegram redelivers a webhook update if the response isn't 2xx in time; the bot may retry
POST /products; a user may double-tap. With replicas, the duplicate lands elsewhere, so an
in-memory "seen" set doesn't help.

**Bug:** product table without `UniqueConstraint("chat_id", "message_id")`; insert without
handling conflict (500 on duplicate → Telegram retries forever); image uploaded to MinIO under
a random key (`uuid4()`) before the insert → orphan objects on every retry; dedup via
in-memory set; `update_id` tracking in memory.

**Fix:** unique constraint + `insert(...).on_conflict_do_nothing(index_elements=[...])
.returning(...)`, then fetch existing row and return 200/existing id. Deterministic object
key (e.g. `products/{chat_id}/{message_id}.jpg`) so re-upload overwrites instead of
orphaning. Bot always returns 200 to Telegram for handled-or-duplicate updates.

## 7. Hardcoded hosts/ports

**Bug:** `localhost`, `127.0.0.1`, `http://backend:8000`, `minio:9000`, `postgres://...@db`,
ports or bucket names as literals in code; `NEXT_PUBLIC_*` URLs baked at build time pointing
at localhost; Caddy upstreams listed as fixed containers (`backend-1:8000`) instead of the
service name.

**OK:** `uvicorn --host 0.0.0.0` bind address; defaults inside `Settings` only if every
deployment overrides them — still flag as info and ensure `.env.example` lists the var.

**Fix:** pydantic-settings field + `.env.example` entry; compose passes it. In Next.js,
server-side fetches use a server-only env var (`BACKEND_INTERNAL_URL`), not `NEXT_PUBLIC_*`.

## 8. Next.js caching across instances

Each `next start` process has its own in-memory + `.next/cache` filesystem cache. With
replicas behind Caddy:

**Critical:**
- Server Actions with no `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY` set at build → "Failed to
  find Server Action" when the action hits another replica (only if images are built
  separately per replica; still flag if Server Actions exist).
- No `deploymentId` / mixed builds during rolling deploy → version skew. Fix:
  `deploymentId: process.env.DEPLOYMENT_VERSION` in `next.config`.

**Warning:**
- Catalog page not `export const dynamic = 'force-dynamic'` (project rule) — or uses
  `export const revalidate = N`, `fetch(..., { next: { revalidate } })`,
  `cache: 'force-cache'`, `unstable_cache`, `'use cache'`, `cacheLife` on product data:
  replicas show different catalogs until each one revalidates.
- `revalidatePath`/`revalidateTag` called from one replica only clears *that* replica.
- `output: 'export'`/ISR with per-instance `.next/cache`.

**Fix:** for this project: `force-dynamic` + `cache: 'no-store'` on backend fetches.
If caching is really wanted: shared `cacheHandler` (Redis) with `cacheMaxMemorySize: 0`
(and `cacheHandlers` for `'use cache'`), so revalidation is global.
Check context7 for the current Next.js version's API before prescribing.

## 9. Compose / infra

- App service with `container_name:` → can't `--scale`. Host `ports:` on a replicated app
  service → port conflict; expose only via Caddy.
- App services missing `depends_on` `minio-init`/`migrate` with
  `condition: service_completed_successfully`.
- Caddy `reverse_proxy` should target the service name (Docker DNS round-robins) or use
  `dynamic a` upstreams; sticky sessions (`lb_policy cookie/ip_hash`) used to *hide* state
  bugs — flag it.
- Healthchecks missing on app services → Caddy routes to replicas still starting.
