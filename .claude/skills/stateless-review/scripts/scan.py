#!/usr/bin/env python3
"""Grep-level candidate scan for multi-replica problems.

Every hit is a candidate to be verified by reading the code, not a finding.
Usage: python3 scan.py [path ...]   (default: repo root = cwd)
"""

import re
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git", "node_modules", ".next", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".claude",
}
EXTS = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".yaml", ".yml", ".toml",
        ".ini", ".cfg", ".sh", ".json", ".env", ".example"}
NAMES = {"Dockerfile", "Caddyfile", "compose.yaml", "docker-compose.yml", "entrypoint.sh"}

PY = {".py"}
JS = {".ts", ".tsx", ".js", ".mjs", ".cjs"}
CFG = {".yaml", ".yml", ".toml", ".ini", ".cfg", ".sh", ".json", ".env", ".example", ""}

# (category, extensions or None for all, regex)
RULES = [
    ("global-state", PY, r"^[A-Za-z_]\w*\s*(:\s*[^=]+)?=\s*(\{\}|\[\]|set\(\)|dict\(\)|list\(\)|defaultdict|OrderedDict|deque|Counter)"),
    ("global-state", PY, r"^\s+global\s+\w+"),
    ("global-state", PY, r"@(functools\.)?(lru_cache|cache)\b|TTLCache|LRUCache|aiocache|cachetools"),
    ("global-state", PY, r"^\w+\s*=\s*asyncio\.(Lock|Semaphore|Event)\("),
    ("global-state", JS, r"^(export\s+)?(const|let|var)\s+\w+\s*(:\s*[^=]+)?=\s*(new\s+(Map|Set|WeakMap)|\{\}|\[\])"),
    ("local-fs", PY, r"open\([^)]*['\"][wa]b?\+?['\"]|aiofiles\.open|\.write_(text|bytes)\(|shutil\.(copy|move)|os\.makedirs|mkdir\(|NamedTemporaryFile\([^)]*delete\s*=\s*False|sqlite"),
    ("local-fs", JS, r"fs\.(promises\.)?(writeFile|appendFile|mkdir|createWriteStream)|writeFileSync"),
    ("local-fs", PY, r"\.download\([^)]*destination\s*=\s*['\"/]"),
    ("aiogram", PY, r"start_polling|run_polling|executor\.start_polling|delete_webhook"),
    ("aiogram", PY, r"MemoryStorage|Dispatcher\(\s*\)"),
    ("aiogram", PY, r"set_webhook|drop_pending_updates|SimpleRequestHandler|feed_webhook_update|feed_update|secret_token|handle_in_background"),
    ("sessions-ratelimit", PY, r"SessionMiddleware|Limiter\(|slowapi|memory://|throttl|rate_?limit|token_hex|token_urlsafe|uuid4\(\)\.hex\s*$"),
    ("sessions-ratelimit", JS, r"rateLimit|ratelimit|session"),
    ("migrations", None, r"alembic\s+upgrade|command\.upgrade|create_all\(|migrate\s+deploy|on_event\(['\"]startup|lifespan"),
    ("idempotency", PY, r"UniqueConstraint|unique\s*=\s*True|on_conflict|IntegrityError|message_id|update_id|uuid4\("),
    ("hardcoded-host", None, r"localhost|127\.0\.0\.1|0\.0\.0\.0|https?://[a-z][\w-]*:\d{2,5}|\b(postgres|minio|backend|bot|frontend|redis):\d{2,5}(?![\d.])"),
    ("nextjs-cache", JS, r"revalidate|force-cache|unstable_cache|['\"]use cache['\"]|cacheLife|cacheTag|revalidatePath|revalidateTag|export\s+const\s+dynamic|cacheHandler|deploymentId|['\"]use server['\"]|NEXT_SERVER_ACTIONS_ENCRYPTION_KEY|NEXT_PUBLIC_"),
    ("compose-infra", CFG, r"container_name|^\s+ports:|depends_on|service_completed_successfully|reverse_proxy|lb_policy|volumes:"),
]
COMPILED = [(c, e, re.compile(p, re.IGNORECASE if c in {"sessions-ratelimit"} else 0)) for c, e, p in RULES]


def iter_files(roots):
    for root in roots:
        root = Path(root)
        if root.is_file():
            yield root
            continue
        for p in root.rglob("*"):
            if any(part in SKIP_DIRS for part in p.parts) or not p.is_file():
                continue
            if p.suffix in EXTS or p.name in NAMES or p.name.startswith("Dockerfile"):
                yield p


def main():
    roots = sys.argv[1:] or ["."]
    hits = {}
    for f in iter_files(roots):
        ext = f.suffix if f.suffix in EXTS else ""
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for n, line in enumerate(lines, 1):
            if line.lstrip().startswith(("#", "//")) and "use " not in line:
                continue
            for cat, exts, rx in COMPILED:
                if exts is not None and ext not in exts:
                    continue
                if rx.search(line):
                    hits.setdefault(cat, []).append(f"{f}:{n}: {line.strip()[:160]}")
    if not hits:
        print("No candidates found. Still check for absences (unique constraint, migrate service, env vars).")
        return
    for cat, _, _ in RULES:
        if cat in hits:
            items = hits.pop(cat)
            print(f"\n== {cat} ({len(items)}) ==")
            print("\n".join(dict.fromkeys(items)))


if __name__ == "__main__":
    main()
