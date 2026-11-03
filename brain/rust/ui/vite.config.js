import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Builds into brain/rust/static/ for rust-embed.
export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    outDir: '../static',
    // false so brain/rust/static/eval_dashboard.json survives a build --
    // deploy.sh already clears stale hashed assets itself (rm -rf
    // static/assets). true here wipes the whole outDir including
    // eval_dashboard.json, which isn't part of this build at all (see
    // docs/superpowers/specs/2026-07-29-verification-queue-handoff.md and
    // 2026-07-28-durable-entity-linking-amendments.md -- this exact
    // config/comment mismatch was already diagnosed twice before).
    emptyOutDir: false,
    assetsDir: 'assets',
  },
  server: {
    proxy: {
      '/stats': 'http://127.0.0.1:8787',
      '/v1': 'http://127.0.0.1:8787',
      '/neighbors': 'http://127.0.0.1:8787',
      '/entities': 'http://127.0.0.1:8787',
      '/linked': 'http://127.0.0.1:8787',
      '/list': 'http://127.0.0.1:8787',
      '/get-episode': 'http://127.0.0.1:8787',
      '/eval_dashboard.json': 'http://127.0.0.1:8787',
    },
  },
})
