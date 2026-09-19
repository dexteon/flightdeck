import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev runs on 9311 and proxies to the FastAPI backend on 9310, so the frontend
// talks to the same relative URLs it will use in production, where one process
// serves both.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 9311,
    proxy: {
      '/api': { target: 'http://127.0.0.1:9310', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:9310', ws: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
