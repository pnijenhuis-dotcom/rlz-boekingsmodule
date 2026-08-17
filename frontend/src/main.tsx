import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Service-worker-hygiëne (Vastly-diagnose 2026-07-14, geport 2026-08-07; herzien 2026-08-15
// voor de accordeur-push): een achtergebleven service worker van een ánder project op een
// gedeelde dev-origin kaapt requests — GET's uit zijn cache (200), writes uit zijn
// offline-handler (bv. 503) — zonder dat er óóit iets in de uvicorn-log verschijnt. Opruimen
// blijft daarom staan, met één bewuste uitzondering: onze eigen push-worker op scope
// /accordeur (public/accordeur-sw.js — géén fetch-handler/caching, alleen Web Push), die de
// accordeur-PWA zelf registreert via src/accordeur/pushClient.ts. Al het andere blijft
// idempotent en onschadelijk opgeruimd.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker
    .getRegistrations()
    .then((registraties) =>
      registraties.forEach((r) => {
        if (!new URL(r.scope).pathname.startsWith('/accordeur')) void r.unregister()
      }),
    )
    .catch(() => {})
}

// Startroute native schil (store-app fase 4): de Capacitor-app laadt index.html op '/' —
// dat is de kántoor-route. De accordeur-app hoort op /accordeur te openen; vóór de eerste
// render zodat de router meteen goed start. Web: no-op.
declare global {
  interface Window {
    Capacitor?: { isNativePlatform?: () => boolean }
  }
}
if (window.Capacitor?.isNativePlatform?.() && window.location.pathname === '/') {
  window.history.replaceState(null, '', '/accordeur')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
