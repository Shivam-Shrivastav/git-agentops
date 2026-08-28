#!/usr/bin/env bash
# Start the home-hosted stack behind a Cloudflare Tunnel.
#   ./home-up.sh            build + start
#   ./home-up.sh --build    force a rebuild
# After up, read the public URL from the cloudflared logs:
#   docker compose -f docker-compose.prod.yml -f docker-compose.home.yml logs cloudflared | grep trycloudflare
set -euo pipefail
exec docker compose -f docker-compose.prod.yml -f docker-compose.home.yml up -d "$@"