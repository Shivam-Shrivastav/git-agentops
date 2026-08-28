#!/usr/bin/env bash
# Stop the home-hosted stack (keeps volumes/data).
set -euo pipefail
exec docker compose -f docker-compose.prod.yml -f docker-compose.home.yml down "$@"