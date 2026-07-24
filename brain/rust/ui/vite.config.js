import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Builds into brain/rust/static/ for rust-embed.
export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    outDir: '../static',
    emptyOutDir: true,
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
