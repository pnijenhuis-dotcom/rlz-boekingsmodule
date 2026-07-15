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
    //
    // LET OP (bug browserreview 2026-07-15): een backend-prefix die hier ontbreekt valt
    // stil terug op Vite's SPA-fallback — de fetch krijgt dan index.html met status 200 en
    // JSON.parse faalt pas later ("Unexpected token '<'"). Nieuwe backend-router-prefix?
    // Hier toevoegen; de guard-test src/instellingen/instellingenApi.test.ts controleert dit
    // voor de API-helpers. '/instellingen/' staat er bewust MET slash: het kale
    // '/instellingen' is een SPA-route (document-navigatie) en mag niet naar de backend.
    proxy: {
      '/auth': 'http://localhost:8000',
      '/administraties': 'http://localhost:8000',
      '/instellingen/': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})
