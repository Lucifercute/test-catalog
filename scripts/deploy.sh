#!/usr/bin/env bash
# Deploy main to the server: push, then pull + rebuild there, then check https://<domain>/api/health.
# Settings: scripts/deploy.conf (gitignored, template: scripts/deploy.conf.example).
# First-time server setup is manual: docs/deploy.md.
set -euo pipefail

cd "$(dirname "$0")/.."

die() {
	echo "deploy: $*" >&2
	exit 1
}

conf=scripts/deploy.conf
[[ -f $conf ]] || die "no $conf; run: cp $conf.example $conf and fill it in"
# shellcheck source=deploy.conf.example
source "$conf"
for var in DEPLOY_HOST DEPLOY_SSH_KEY DEPLOY_PATH DEPLOY_DOMAIN; do
	[[ -n ${!var:-} ]] || die "$var is empty in $conf"
done
[[ -f $DEPLOY_SSH_KEY ]] || die "ssh key not found: $DEPLOY_SSH_KEY"

[[ -z $(git status --porcelain) ]] || die "uncommitted changes (git status), commit or stash them first"
branch=$(git rev-parse --abbrev-ref HEAD)
[[ $branch == main ]] || die "on branch '$branch', deploy only from main"

git push origin main
sha=$(git rev-parse HEAD)

echo "deploy: $sha -> $DEPLOY_HOST:$DEPLOY_PATH"
ssh -i "$DEPLOY_SSH_KEY" -o IdentitiesOnly=yes "$DEPLOY_HOST" bash -s -- "$DEPLOY_PATH" "$sha" <<'REMOTE'
set -euo pipefail
cd "$1"
git pull --ff-only
[[ $(git rev-parse HEAD) == "$2" ]] || { echo "server HEAD $(git rev-parse HEAD) != $2" >&2; exit 1; }

# Guard: only Caddy's 80/443 may be published. Fails if the dev override got loaded
# (COMPOSE_FILE=compose.yaml missing from the server's .env).
extra=$(docker compose config | sed -nE 's/^ +published: "?([0-9]+)"?$/\1/p' | grep -vxE '80|443' || true)
[[ -z $extra ]] || { echo "refusing: would publish ports $(echo $extra); set COMPOSE_FILE=compose.yaml in .env" >&2; exit 1; }

docker compose up -d --build --remove-orphans
docker compose ps -a
REMOTE

url="https://$DEPLOY_DOMAIN/api/health"
echo "deploy: checking $url"
# Retries cover replicas starting up and the first certificate issuance.
curl -fsS --retry 20 --retry-delay 3 --retry-all-errors --max-time 10 "$url"
echo
echo "deploy: OK"
