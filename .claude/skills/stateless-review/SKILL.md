---
name: stateless-review
description: Review code and config of any service in this repo (backend/FastAPI, bot/aiogram, frontend/Next.js, compose.yaml, Dockerfiles, infra/Caddy) for compatibility with running as multiple replicas at once. Finds in-memory state and caches, local file writes, aiogram polling or MemoryStorage FSM, in-memory sessions/rate limits, migrations on app startup, non-idempotent webhook/product creation, hardcoded hosts/ports, and Next.js caching that diverges between instances. Outputs findings with file, line and fix. Use this whenever the user asks to check "stateless", "replicas", "scaling", "horizontal scaling", "can this run in N copies", "multi-instance", "проверь на реплики/stateless", or before saying a service is done, after adding a new service, or when reviewing a diff that touches state, caching, startup hooks, webhooks or compose — even if the user doesn't name this skill.
---

# Stateless review

The project's hard rule (see CLAUDE.md) is that every service — backend, bot, frontend —
runs as several replicas behind Caddy at the same time. Any state that lives inside one
process or one container's filesystem silently breaks this: requests land on different
replicas, Telegram webhook retries land on a different replica, restarts wipe memory.
Your job is to find every such place and say exactly how to fix it.

## Scope

- If the user names a service/path/diff — review only that.
- Otherwise review everything: `backend/`, `bot/`, `frontend/`, `infra/`, `compose.yaml`,
  `Dockerfile*`, `.env.example`, `alembic/`/`migrations/`.
- Skip `node_modules/`, `.next/`, `.venv/`, `__pycache__/`, lockfiles, tests (but tests can
  reveal intent — e.g. a test asserting a module-level cache).

## Workflow

1. **Candidate scan.** Run the bundled scanner to get a fast list of suspicious lines:
   ```bash
   python3 .claude/skills/stateless-review/scripts/scan.py [paths...]
   ```
   It is grep-level and noisy on purpose. Every hit is a *candidate*, not a finding.
2. **Read the code around each candidate** and decide whether it is really a problem.
   Module-level constants, compiled regexes, `settings = Settings()`, a logger, an
   `engine`/`async_sessionmaker`/`httpx.AsyncClient`/`Bot` created once per process are
   fine — they hold connections or immutable config, not shared mutable data. A dict that
   gets written at runtime and read on later requests is not fine.
3. **Look for what grep can't see**: missing things. The scanner only catches present
   patterns; absences need you to check intent:
   - no unique constraint on `(chat_id, message_id)` / no `ON CONFLICT` handling;
   - no `migrate` service in compose, or app services not depending on it;
   - no `NEXT_SERVER_ACTIONS_ENCRYPTION_KEY` / `deploymentId` when the frontend is replicated;
   - no `secret_token` on the webhook; `.env.example` missing a var the code reads.
4. **Read `references/checklist.md`** for the detailed checklist, what counts as a bug vs. OK,
   and canonical fixes for this stack. Read it the first time you run this skill in a
   session — the Next.js and aiogram sections encode non-obvious rules.
5. If unsure about a current framework API (aiogram 3, Next.js caching changes often),
   check context7 before recommending a fix.
6. Report (format below). Don't edit code unless the user asks — this is a review.

## Severity

- **critical** — breaks correctness with >1 replica (lost/duplicated data, FSM state lost
  between steps, polling conflict, two replicas migrating at once, "Failed to find Server Action").
- **warning** — works but diverges between replicas or on restart (stale per-instance cache,
  per-replica rate limit = N× the intended limit, hardcoded host that breaks outside compose).
- **info** — hygiene that will bite later (env var with a hardcoded default that only works
  locally, missing `.env.example` entry).

## Output format

Answer in the user's language. Use this structure:

```
## Stateless review: <scope>

Итого: X critical, Y warning, Z info   (or "Summary: ..." in English)

### critical
1. `bot/main.py:42` — <what is wrong, one sentence>
   Почему ломается: <what happens with 2+ replicas, concretely>
   Как исправить: <specific change; short code snippet if it helps>

### warning
...

### info
...

### Проверено, проблем нет
- <checklist items you verified and found OK, one line each>
```

Rules for findings:
- Every finding has `path:line` (clickable). If the problem is an absence, point at the
  place where the fix belongs (e.g. the model class, the compose service) and say "missing".
- Explain *why it breaks with replicas*, not just "globals are bad" — the reader should be
  able to judge the fix.
- Fix must be concrete for this stack (Redis/Postgres/MinIO, aiogram RedisStorage,
  `INSERT ... ON CONFLICT`, `migrate` service, env var via pydantic-settings).
- Group duplicates: same pattern in 5 files → one finding listing all locations.
- Don't report false positives to look thorough. If a candidate was OK, at most mention it
  in "Проверено" with the reason.
- If nothing is wrong, say so plainly and list what was checked.
