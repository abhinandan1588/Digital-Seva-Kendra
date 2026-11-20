import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The production build is served by Flask under /app/ (see app/api/routes.py).
// `npm run dev` starts the Vite dev server on :5173 and proxies the Flask
// endpoints (API, QR images, receipts, document downloads, uploaded images)
// to the Flask dev server on :5000, so sessions/cookies just work.
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:5000',
      '/pay': 'http://127.0.0.1:5000',
      '/order': 'http://127.0.0.1:5000',
      '/static': 'http://127.0.0.1:5000',
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
