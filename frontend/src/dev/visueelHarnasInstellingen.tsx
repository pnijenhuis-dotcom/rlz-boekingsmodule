// Visueel harnas Instellingen (nazorg designsysteem 2026-08-16, kliktest Peter ~1170px): het
// echte scherm met gemockte fetch in de shell-layout, voor headless verificatie zonder
// backend/login. Data bootst de breedste realistische stand na: meerdere administraties
// (waarvan één vastgoed → extra Autoboeken-kolom), AI-kostenblok met 80%-waarschuwing,
// passkey-apparaten (incl. kantoor-overzicht) en een accordeur mét staande regels.
//   npx vite --port 5199  →  http://localhost:5199/harness-instellingen.html [?donker=1]
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { InstellingenScreen } from '../instellingen/InstellingenScreen'
import { ToastProvider } from '../ui/basis'
import { OverflowBadge } from './overflowBadge'
import '../index.css'

const EIGEN_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const MEDEWERKER_ID = 'bbbbbbbb-0000-0000-0000-00000000000b'
const ACCORDEUR_ID = 'cccccccc-0000-0000-0000-00000000000c'
const ADMIN_1 = 'dddddddd-0000-0000-0000-00000000000d'
const ADMIN_2 = 'eeeeeeee-0000-0000-0000-00000000000e'
const ADMIN_3 = 'ffffffff-0000-0000-0000-00000000000f'

function fakeAccessToken(): string {
  const payload = btoa(JSON.stringify({ sub: EIGEN_ID, rol: 'beheerder' }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

const ADMINISTRATIES = [
  {
    id: ADMIN_1,
    naam: 'Universal Steigerbouw Nederland B.V.',
    boeken_ingeschakeld: true,
    project_verplicht: true,
    ai_extractie_ingeschakeld: true,
    eigenaar_gebruiker_id: MEDEWERKER_ID,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
    eigenaar_naam: 'Demi de Vries',
    iban_accordeurs_aantal: 2,
    laatste_sync_op: '2026-08-31T06:14:00Z',
    webservice_username: 'ws-universal',
    probe_groen: true,
    rlz_admin_id: '11111111-2222-3333-4444-555555555555',
  },
  {
    id: ADMIN_2,
    naam: 'Molenhof Verhuur B.V.',
    boeken_ingeschakeld: true,
    project_verplicht: false,
    ai_extractie_ingeschakeld: false,
    eigenaar_gebruiker_id: null,
    is_vastgoed: true,
    verkoop_autoboeken_ingeschakeld: true,
  },
  {
    id: ADMIN_3,
    naam: 'BLOW B.V.',
    boeken_ingeschakeld: false,
    project_verplicht: false,
    ai_extractie_ingeschakeld: false,
    eigenaar_gebruiker_id: EIGEN_ID,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
  },
  // Kopregel-fix 01-09 (screenshot Peter: knop half over "N actief · gearchiveerd (1)"): één
  // gearchiveerde rij zodat de filterregel mét gearchiveerd-link in de sweep meedraait.
  {
    id: 'abcdefff-0000-0000-0000-0000000000ff',
    naam: 'Gearchiveerd Voorbeeld B.V.',
    boeken_ingeschakeld: true,
    project_verplicht: false,
    ai_extractie_ingeschakeld: true,
    eigenaar_gebruiker_id: null,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
    gearchiveerd_op: '2026-08-30T10:00:00Z',
    gearchiveerd_door_naam: 'Peter Nijenhuis',
  },
  // Sticky-koppen-regressie (kliktest Peter 01-09): genoeg rijen dat .tabel-scroll.sticky-koppen
  // intern scrolt — het sweep-geval ?pad=/instellingen/administraties toetst deze lange lijst.
  ...Array.from({ length: 14 }, (_, i) => ({
    id: `abcdef0${i.toString(16)}-0000-0000-0000-0000000000${i.toString(16).padStart(2, '0')}`,
    naam: `Vulling ${i + 1} B.V. (sticky-koppen-regressie)`,
    boeken_ingeschakeld: true,
    project_verplicht: false,
    ai_extractie_ingeschakeld: true,
    eigenaar_gebruiker_id: null,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
    eigenaar_naam: 'Demi de Vries',
    iban_accordeurs_aantal: 1,
    laatste_sync_op: '2026-08-31T06:14:00Z',
    webservice_username: `ws-vulling-${i + 1}`,
    probe_groen: true,
  })),
]

const MEDEWERKERS = {
  medewerkers: [
    { id: EIGEN_ID, naam: 'Peter Nijenhuis' },
    { id: MEDEWERKER_ID, naam: 'Demi de Vries' },
  ],
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

const echteFetch = window.fetch.bind(window)
window.fetch = (invoer: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = typeof invoer === 'string' ? invoer : invoer instanceof URL ? invoer.toString() : invoer.url
  if (url === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken() }))
  if (url === '/instellingen/administraties' || url.startsWith('/instellingen/administraties?'))
    return Promise.resolve(jsonResponse({ administraties: ADMINISTRATIES }))
  if (url === '/instellingen/boeken-kill-switch') return Promise.resolve(jsonResponse({ ingeschakeld: true }))
  if (url === '/instellingen/intake-ai') return Promise.resolve(jsonResponse({ ingeschakeld: false }))
  if (url === '/instellingen/ai-kosten') {
    return Promise.resolve(
      jsonResponse({
        maand: '2026-08',
        verbruik_eur: '82,40',
        limiet_eur: '100',
        percentage: 82,
        waarschuwing_80: true,
        limiet_bereikt: false,
        extracties_template_maand: 7,
        extracties_ai_maand: 12,
        templates_actief: 2,
      }),
    )
  }
  if (url.endsWith('/iban-accordeurs')) return Promise.resolve(jsonResponse({ accordeurs: [] }))
  if (url.endsWith('/medewerkers')) return Promise.resolve(jsonResponse(MEDEWERKERS))
  if (url === '/auth/webauthn/config') return Promise.resolve(jsonResponse({ dev_stub: true, rp_id: 'localhost' }))
  if (url === '/auth/mijn/apparaten') {
    return Promise.resolve(
      jsonResponse({
        apparaten: [
          {
            id: 'app-eigen-1',
            apparaat_naam: 'MacBook van Peter',
            is_dev_stub: false,
            aangemaakt_op: '2026-08-15T09:00:00Z',
            laatst_gebruikt_op: '2026-08-16T08:00:00Z',
            ingetrokken_op: null,
          },
        ],
      }),
    )
  }
  if (url === '/auth/apparaten/kantoor') {
    return Promise.resolve(
      jsonResponse({
        apparaten: [
          {
            id: 'app-kantoor-1',
            gebruiker_naam: 'Demi de Vries',
            apparaat_naam: 'Windows Hello — werkplek boekhouding (langere apparaatnaam)',
            is_dev_stub: false,
            aangemaakt_op: '2026-08-15T10:00:00Z',
            laatst_gebruikt_op: '2026-08-16T07:30:00Z',
            ingetrokken_op: null,
          },
        ],
      }),
    )
  }
  if (url.endsWith('/accordering/instellingen')) {
    return Promise.resolve(
      jsonResponse({
        ingeschakeld: url.includes(ADMIN_2),
        lagen: url.includes(ADMIN_2) ? [{ volgnummer: 1, accordeur_gebruiker_id: ACCORDEUR_ID, bedrag_drempel: null }] : [],
      }),
    )
  }
  if (url.endsWith('/accordering/kandidaten')) {
    return Promise.resolve(
      jsonResponse({
        kandidaten: url.includes(ADMIN_2) ? [{ id: ACCORDEUR_ID, naam: 'R. de Groot', e_mail: 'r.degroot@molenhof.nl' }] : [],
      }),
    )
  }
  if (url.endsWith('/accordering/staande-regels')) return Promise.resolve(jsonResponse({ regels: [] }))
  if (url.includes('/auth/gebruikers/') && url.endsWith('/apparaten')) {
    return Promise.resolve(
      jsonResponse({
        apparaten: [
          {
            id: 'app-acc-1',
            apparaat_naam: 'iPhone van R.',
            is_dev_stub: false,
            aangemaakt_op: '2026-08-11T10:00:00Z',
            laatst_gebruikt_op: '2026-08-15T09:00:00Z',
            ingetrokken_op: null,
          },
        ],
      }),
    )
  }
  if (url.endsWith('/doorbelasting-instelling')) return Promise.resolve(jsonResponse({ ingeschakeld: false }))
  return echteFetch(invoer, init)
}

if (new URLSearchParams(window.location.search).has('donker')) {
  document.documentElement.classList.add('dark')
  document.body.classList.add('dark')
}

// Startroute overschrijfbaar (?pad=/instellingen/administraties) — zo kan de overflow-sweep
// óók de subpagina's meten (sticky-koppen-regressie 01-09) zonder klik-automatisering.
const startPad = new URLSearchParams(window.location.search).get('pad') ?? '/instellingen'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MemoryRouter initialEntries={[startPad]}>
      <AuthProvider>
        <ToastProvider>
          <div className="app">
            <nav className="sidebar">
              <div className="logo">
                <div className="logo-mark">N</div>
                <div>
                  <b>Nijenhuis</b>
                  <small>Boekingsmodule</small>
                </div>
              </div>
              <div className="nav-kop">Beheer</div>
              <a className="nav-item actief">Instellingen</a>
            </nav>
            <div className="main">
              <div className="content">
                <Routes>
                  <Route path="/instellingen" element={<InstellingenScreen />} />
                  <Route path="/instellingen/:sectie" element={<InstellingenScreen />} />
                </Routes>
              </div>
            </div>
          </div>
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>
    <OverflowBadge />
  </StrictMode>,
)
