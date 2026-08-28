#!/usr/bin/env sh
# Stop (and optionally wipe) the local prod-test stack.
#   ./local-down.sh        # stop + remove containers (keep data volumes)
#   ./local-down.sh -v     # also delete the db + caddy data volumes
set -e
cd "$(dirname "$0")"
exec docker compose -f docker-compose.prod.yml -f docker-compose.local.yml down "$@"