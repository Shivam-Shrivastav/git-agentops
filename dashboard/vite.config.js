import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // The dashboard is served behind Caddy / a Cloudflare Tunnel, so the
  // request's Host header is the tunnel hostname, not localhost. Vite 8
  // 403s any non-localhost Host by default; allow all hosts so the reverse
  // proxy (and any future public hostname) works. Caddy's basic_auth still
  // gates access — this only relaxes the Host check.
  server: { allowedHosts: true },
  preview: { allowedHosts: true },
})
