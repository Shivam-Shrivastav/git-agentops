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
  server: {
    allowedHosts: true,
    // Proxy same-origin agent mounts to the local HTTP services so the
    // dashboard chat UI works out of the box in dev (no Caddy required).
    proxy: {
      "/agent": { target: "http://localhost:8001", changeOrigin: true },
      "/simple-agent": { target: "http://localhost:8002", changeOrigin: true },
    },
  },
  preview: { allowedHosts: true },
})
