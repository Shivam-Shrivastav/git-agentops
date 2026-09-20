# Host on your own machine with a Cloudflare Tunnel

This runs the **entire AgentOps stack + github-agent on this machine** and
exposes it at a public HTTPS URL via a **Cloudflare Tunnel** — no public IP,
no inbound ports, no router port-forwarding. Your machine makes only
**outbound** connections to Cloudflare; Cloudflare terminates TLS at its edge
and tunnels requests back to the local Caddy.

```
internet --HTTPS--> Cloudflare edge ==tunnel(outbound from your Mac)==> cloudflared --> caddy:80 (HTTP, basic_auth)
                                                                      \-> /api/*  ingestion-api:8000
                                                                       -> /agent/* agent-service:8001
                                                                       -> /        dashboard:5173
```

Prerequisites on this machine:
- Docker (Docker Desktop on macOS) running.
- `.env` (repo root) with real `GITHUB_TOKEN`, `OPENROUTER_API_KEY`,
  `AUTH_USER`, `AUTH_HASH` (see `.env.prod.example` / `DEPLOY.md` for the
  `$$`-escaped bcrypt hash). The stack never opens a host port — exposure is
  the tunnel only.

---

## A. Quick tunnel — instant, no account, no domain (default)

A quick tunnel gives a random `https://*.trycloudflare.com` URL with **zero
setup** — no Cloudflare account, no domain. Good to start; the URL is
unguessable but **changes on every restart**.

```bash
./home-up.sh
# read the public URL from the tunnel logs:
docker compose -f docker-compose.prod.yml -f docker-compose.home.yml logs cloudflared | grep trycloudflare
```

The line looks like:
```
INF |  https://ground-lake-ago-stomach.trycloudflare.com   |
```

Open it in a browser; basic-auth prompts for `AUTH_USER` / your password.
Stop with `./home-down.sh` (data is kept in volumes).

### Trigger an agent run through the public URL
```bash
URL=https://<your-random>.trycloudflare.com
curl -u admin:<PASSWORD> -X POST "$URL/agent/run" \
  -H 'Content-Type: application/json' \
  -d '{"task":"list open issues in Shivam-Shrivastav/Data-Structures"}'
# -> {"run_id":"...","status":"started",...}
curl -u admin:<PASSWORD> "$URL/agent/runs/<run_id>"   # poll until status=done
```
The returned `trace_id` appears in the dashboard at the same URL's root,
under Traces.

---

## B. Stable named tunnel — your own subdomain (recommended for real use)

A quick tunnel URL changes on restart. For a **stable** URL
(`https://agentops.yourdomain.com`), use a named tunnel. This needs:

1. A free **Cloudflare account**.
2. A **domain managed by Cloudflare** (add the domain in the Cloudflare
   dashboard and point its nameservers at Cloudflare; or use a domain you
   already have on Cloudflare). If you don't own one, a cheap `.com`/`.dev`
   (~$10/yr) works — there is no fully-free stable-hostname option.

### B1. Create the tunnel in the dashboard
1. Cloudflare dashboard → **Zero Trust** → **Networks** → **Tunnels** →
   **Create a tunnel** → type **Cloudflared** → name it `agentops`.
2. Under **Install and run a connector** copy the **token** (long string
   starting `eyJ...`). This is `TUNNEL_TOKEN`.
3. **Public Hostname** tab → add a hostname, e.g. `agentops.yourdomain.com`,
   service `HTTP`, URL `http://caddy:80`. (cloudflared runs in the compose
   network, so it resolves `caddy` by service name — no host port needed.)

### B2. Put the token in `.env`
```
TUNNEL_TOKEN=eyJ...your-token...
```

### B3. Run with the named-tunnel override
```bash
./home-down.sh   # stop the quick-tunnel stack first
docker compose -f docker-compose.prod.yml -f docker-compose.home.yml \
  up -d --force-recreate cloudflared
```
The URL is now stable: `https://agentops.yourdomain.com` (survives restarts;
Cloudflare DNS points the subdomain at the tunnel automatically).

---

## C. Security checklist (the URL is public)

- **Change the basic-auth password from `test`.** Generate a strong one and
  re-hash it with `$$`-escaping (see `DEPLOY.md` step 3):
  ```bash
  HASH=$(docker compose -f docker-compose.prod.yml run --rm caddy \
    caddy hash-password --plaintext 'YOUR_STRONG_PASSWORD')
  python3 -c "print('AUTH_HASH=' + __import__('sys').argv[1].replace('\$','\$\$'))" "$HASH"
  # paste the printed AUTH_HASH=... line into .env, then:
  docker compose -f docker-compose.prod.yml -f docker-compose.home.yml restart caddy
  ```
- Optional: replace Caddy basic_auth with **Cloudflare Access** (Zero Trust
  → Access → Applications → add an app for the hostname, email-OTP
  login). Then remove `basic_auth` from `Caddyfile.home` for a nicer login.
- The `.env` file has live `GITHUB_TOKEN` / `OPENROUTER_API_KEY` — it is
  gitignored; never commit it, and never paste it anywhere.

---

## D. Keep it running

- The machine must stay **on** and Docker running. On macOS, set Docker
  Desktop to start at login, and (optionally) auto-start the stack:
  ```bash
  # a launchd plist that runs ./home-up.sh at load — create if you want
  # boot-time startup; for a prototype, just re-run ./home-up.sh after reboot.
  ```
- Quick-tunnel URL changes after a restart; re-read it from the logs
  (`grep trycloudflare`). Named tunnel (section B) URL is stable.
- No inbound ports are opened, so nothing on your LAN/router needs
  configuring. Caddy's host 80/443 mappings are removed in the home override
  (`ports: !reset []`) — exposure is the tunnel only.

---

## E. What's in the home override

`docker-compose.home.yml` (stacked on `docker-compose.prod.yml`):
- `caddy`: drops host `80/443` mapping (`ports: !reset []`), mounts
  `Caddyfile.home` (HTTP, no TLS — Cloudflare does TLS — + basic_auth).
- `cloudflared`: named tunnel, `command: tunnel run` + `TUNNEL_TOKEN`
  from `.env`, reaches Caddy by service name over the compose network.

The dashboard is built with `VITE_API_BASE_URL=/api` (same-origin), and
`vite.config.js` sets `server/preview.allowedHosts: true` so the proxied
tunnel Host header isn't 403'd by Vite's host-allowlist check.