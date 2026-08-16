/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import proxyPrefixes from './proxy-prefixes.json' with { type: 'json' }
import { bouwProxyMap } from './proxyRegels.ts'

const BACKEND = 'http://localhost:8000'

// Proxy naar de backend zodat de browser alles als één origin ziet — de httpOnly
// refresh-cookie werkt dan zonder CORS-gedoe. Backend heeft CORS wél aanstaan (app/main.py)
// als vangnet voor rechtstreekse toegang op poort 8000.
//
// De prefixlijst is GEGENEREERD uit de backend-router (proxy-prefixes.json — verversen met
// `python -m app.proxy_prefixes`), na de derde herhaling van de vergeten-prefix-bug
// (browserreviews 2026-07-15 en 2026-08-07): een ontbrekende prefix valt stil terug op Vite's
// SPA-fallback (index.html, status 200) en faalt pas bij JSON.parse. Guards:
// tests/unit/test_proxy_prefixes_dump.py (backend, router↔JSON) en
// src/api/proxyDekking.test.ts (frontend, aangeroepen paden↔JSON, over álle bronbestanden).
//
// Segment-keys krijgen bewust een slash-suffix ('/instellingen/'): het kale segment kan een
// SPA-route zijn en een document-navigatie mag nooit naar de backend. Paden die de backend
// exact op één segment serveert (bv. /verzamelbak) staan apart in exacte_paden.
// Opbouw + document-navigatie-bypass (randgeval /bank/ met trailing slash, kliktest
// 2026-08-08) leven in proxyRegels.ts, getest via src/api/proxyDekking.test.ts.
const proxy = bouwProxyMap(proxyPrefixes, BACKEND)

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Vaste poort per project (Platform/registers/conventies.md, afspraak 2026-08-07:
    // RLZ = 5173, Vastly = 5174). strictPort: liever hard falen dan stil uitwijken naar een
    // andere poort — gedeelde localStorage/service-workers tussen projecten op dezelfde origin
    // veroorzaakten eerder spookbugs (verbeteringen.md 2026-07-13).
    port: 5173,
    strictPort: true,
    // LAN-bereikbaar voor de telefoon-kliktest van de accordeur-PWA (slot 2026-08-11): de
    // dev-server luistert ook op het LAN-IP; de proxy naar de backend blijft server-side
    // (localhost:8000), dus de telefoon hoeft alleen déze poort te bereiken. NB op een LAN-IP
    // is er geen secure context — echte passkeys werken daar niet; daarvoor is de expliciet
    // gemarkeerde dev-stub (backend AUTH_BIOMETRIE_DEV_STUB=true, alleen dev).
    host: true,
    proxy,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
  },
})
