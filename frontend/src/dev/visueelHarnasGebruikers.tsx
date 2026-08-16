// Visueel harnas Gebruikers & toegang (fase 3 modernisering 15-08): het echte scherm met
// gemockte fetch, voor headless verificatie zonder backend/login.
//   npx vite --port 5199  →  http://localhost:5199/harness-gebruikers.html [?donker=1]
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { GebruikersScreen } from '../gebruikers/GebruikersScreen'
import { ToastProvider } from '../ui/basis'
import { OverflowBadge } from './overflowBadge'
import '../index.css'

const EIGEN_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const ADMIN_1 = 'dddddddd-0000-0000-0000-00000000000d'
const ADMIN_2 = 'eeeeeeee-0000-0000-0000-00000000000e'

function fakeAccessToken(): string {
  const payload = btoa(JSON.stringify({ sub: EIGEN_ID, rol: 'beheerder' }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

const GEBRUIKERS = [
  {
    id: EIGEN_ID,
    naam: 'Peter Nijenhuis',
    e_mail: 'p.nijenhuis@kempengroep.nl',
    rol: 'beheerder',
    status: 'actief',
    administratie_ids: [],
    heeft_totp: true,
    aantal_passkeys: 2,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
  },
  {
    id: 'bbbbbbbb-0000-0000-0000-00000000000b',
    naam: 'Demi de Vries',
    e_mail: 'demi@ak-nijenhuis.nl',
    rol: 'boekhouding',
    status: 'actief',
    administratie_ids: [ADMIN_1, ADMIN_2],
    heeft_totp: true,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
  },
  {
    id: 'ffffffff-0000-0000-0000-00000000000f',
    naam: 'J. Jansen',
    e_mail: 'j.jansen@voorbeeld.nl',
    rol: 'boekhouding',
    status: 'uitgenodigd',
    administratie_ids: [ADMIN_1],
    heeft_totp: false,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: new Date(Date.now() + 68 * 3600e3).toISOString(),
    staande_goedkeuringen: 0,
  },
  {
    id: 'cccccccc-0000-0000-0000-00000000000c',
    naam: 'R. de Groot',
    e_mail: 'r.degroot@molenhof.nl',
    rol: 'klant_accordeur',
    status: 'actief',
    administratie_ids: [ADMIN_1, ADMIN_2],
    heeft_totp: false,
    aantal_passkeys: 1,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 2,
  },
]

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

const echteFetch = window.fetch.bind(window)
window.fetch = (invoer: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = typeof invoer === 'string' ? invoer : invoer instanceof URL ? invoer.toString() : invoer.url
  if (url === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken() }))
  if (url === '/auth/gebruikers') return Promise.resolve(jsonResponse({ gebruikers: GEBRUIKERS }))
  if (url === '/auth/administraties') {
    return Promise.resolve(
      jsonResponse({
        administraties: [
          { id: ADMIN_1, naam: 'Molenhof Beheer B.V.' },
          { id: ADMIN_2, naam: 'Molenhof Verhuur B.V.' },
        ],
      }),
    )
  }
  if (url.includes('/apparaten')) {
    return Promise.resolve(
      jsonResponse({
        apparaten: [
          {
            id: 'app-1',
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
  return echteFetch(invoer, init)
}

if (new URLSearchParams(window.location.search).has('donker')) {
  document.documentElement.classList.add('dark')
  document.body.classList.add('dark')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MemoryRouter initialEntries={['/gebruikers']}>
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
              <a className="nav-item actief">Gebruikers</a>
            </nav>
            <div className="main">
              <div className="content">
                <Routes>
                  <Route path="/gebruikers" element={<GebruikersScreen />} />
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
