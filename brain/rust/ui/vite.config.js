import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    outDir: '../static',
    // Must stay false: ../static also holds runtime data (eval_dashboard.json)
    // that a full-dir wipe would destroy. deploy.sh clears stale assets instead.
    emptyOutDir: false,
  },
  server: {
    proxy: {
      '/v1': 'http://localhost:8787',
      '/stats': 'http://localhost:8787',
      '/search': 'http://localhost:8787',
      '/save': 'http://localhost:8787',
      '/memories': 'http://localhost:8787',
      '/feedback': 'http://localhost:8787',
      '/reflect': 'http://localhost:8787',
      '/get-episode': 'http://localhost:8787',
      '/eval_dashboard.json': 'http://localhost:8787',
      '/list': 'http://localhost:8787',
    },
  },
})
