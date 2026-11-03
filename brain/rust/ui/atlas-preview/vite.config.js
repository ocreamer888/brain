import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    port: 5199,
    strictPort: true,
    headers: {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
    },
  },
  optimizeDeps: {
    exclude: ['@duckdb/duckdb-wasm'],
    include: ['@cosmograph/cosmograph'],
  },
})
