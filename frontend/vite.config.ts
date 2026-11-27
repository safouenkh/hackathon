import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En développement, /api est relayé vers le backend FastAPI (pas de CORS à ouvrir).
// En production, le backend sert lui-même le dossier dist/ (même origine).
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
