/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Proxy naar de backend zodat de browser alles als één origin ziet — de httpOnly
    // refresh-cookie werkt dan zonder CORS-gedoe. Backend heeft CORS wél aanstaan
    // (app/main.py) als vangnet voor rechtstreekse toegang op poort 8000.
    proxy: {
      '/auth': 'http://localhost:8000',
      '/administraties': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})
