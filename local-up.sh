#!/usr/bin/env sh
# Run the production stack locally over HTTP (no domain/TLS needed).
# Requires a .env at the repo root (see .env.prod.example). basicauth uses
# AUTH_USER / AUTH_HASH from .env — hit http://localhost with those creds.
#
#   ./local-up.sh          # build + start (detached)
#   ./local-up.sh --build  # rebuild after code changes
set -e
cd "$(dirname "$0")"
exec docker compose -f docker-compose.prod.yml -f docker-compose.local.yml up -d "$@"