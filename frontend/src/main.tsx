import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Deze app registreert bewust GEEN service worker — maar een lokale dev-origin (localhost:5173)
// kan gedeeld zijn (geweest) met andere projecten, en een achtergebleven service worker van zo'n
// project kaapt requests: GET's uit zijn cache (200), niet-cachebare writes uit zijn
// offline-handler (bv. 503) — zonder dat er óóit iets in de uvicorn-log verschijnt
// (Vastly-diagnose 2026-07-14, geport 2026-08-07). Opruimen is idempotent en onschadelijk.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker
    .getRegistrations()
    .then((registraties) => registraties.forEach((r) => void r.unregister()))
    .catch(() => {})
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
