import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import localize from './localize.cjs'

// In sviluppo (`npm run dev`) le chiamate vanno al backend su 8760;
// in produzione il backend serve direttamente la cartella dist.
export default defineConfig({
  plugins: [react({ babel: { plugins: [localize] } })],
  base: './',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8760',
      '/ws': { target: 'ws://127.0.0.1:8760', ws: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, chunkSizeWarningLimit: 900 },
})
