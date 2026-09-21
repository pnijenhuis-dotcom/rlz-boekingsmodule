// Visueel harnas Planning personeel v3 "dag-eerst" (18-09, mockup planning-v3-dag-eerst.html): het echte PlanningScreen
// met gemockte fetch — 83 actieve projecten (Universal-schaal), 12 veldwerkers, één reservering, één afwezigheid en één
// dubbel geplande persoon, zodat projectbalk ("+ N"), conflictenbalk, gereserveerde kaart en pool-standen allemaal zichtbaar
// zijn. Patroon visueelHarnasVeldwerkers.tsx.
//   npx vite --port 5202  →  http://localhost:5202/harness-planning.html [?donker=1] [?perproject=1] [?kaart=1] [?tab=transport]
// De projectbalk scrolt horizontaal BINNEN de pagina — de OverflowBadge bewaakt dat de pagina zelf nooit breder wordt.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlanningScreen } from '../planning/PlanningScreen'
import { ToastProvider } from '../ui/basis'
import { OverflowBadge } from './overflowBadge'
import '../index.css'

const EIGEN_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const ADMIN = 'dddddddd-0000-0000-0000-00000000000d'
const params = new URLSearchParams(window.location.search)
const PER_PROJECT = params.has('perproject')
const KAART = params.has('kaart')
const TAB = params.get('tab')

function fakeAccessToken(): string {
  const payload = btoa(JSON.stringify({ sub: EIGEN_ID, rol: 'beheerder' })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

// Vaste week (38, 14–18 sep 2026) zodat de screenshots stabiel zijn. 21-09: het conflictenpaneel toont alleen conflicten
// vanaf VANDAAG — daarom hier óók een vaste "vandaag" (di 15-9-2026): ma 14-9 = 1 verstreken conflict (tekstregel), wo/do
// gevuld (dubbel, > 5, afwezig, dossier) en de weekchip zegt "lopende week".
const VASTE_NU = new Date(2026, 8, 15, 9, 0, 0).getTime()
class VasteDate extends Date {
  constructor(...args: unknown[]) {
    if (args.length === 0) super(VASTE_NU)
    else super(...(args as [number]))
  }
  static now(): number {
    return VASTE_NU
  }
}
;(globalThis as unknown as { Date: unknown }).Date = VasteDate
const WEEK = '2026-W38'
const D = ['2026-09-14', '2026-09-15', '2026-09-16', '2026-09-17', '2026-09-18']
const NAMEN = ['Orfan Ogur', 'Reijer de Vries', 'M. Sanli', 'R. Yücetaş', 'S. Hasturk', 'V. Ponchev', 'Z.V. Panchev', 'Hakim Lali', 'Adem Sarac', 'I. Onel', 'A. Alizada', 'Baki Genc']
const G = NAMEN.map((_, i) => `${String(i + 1).padStart(8, '0')}-0000-0000-0000-000000000001`)
const rol = (i: number) => (i < 2 ? 'uitvoerder' : 'zzper')
const k = (i: number, extra: Record<string, unknown> = {}) => ({ gebruiker_id: G[i], naam: NAMEN[i], rol: rol(i), dagdeel: 'heel', ...extra })
const P = (n: number) => `${String(n).padStart(8, '0')}-0000-0000-0000-00000000000p`.replace('p', 'a')

const PLAATSEN = ['Arnhem-Kronenburg', 'Nieuwegein', 'Rijssen', 'Apeldoorn', 'Breda', 'Zwolle', 'Deventer', 'Tilburg', 'Enschede', 'Utrecht', 'Almelo', 'Hengelo']
const OPDRACHTGEVERS = ['Pleijweg', 'Wessels', 'Olieman', 'De Bazar', 'Moeskops', 'Ben Kuijer', 'Kempen Facilities', 'Heijmans', 'BAM', 'Dura Vermeer', 'VolkerWessels', 'Bouwadvies Oost']
const projecten = Array.from({ length: 83 }, (_, i) => ({
  project_id: P(i + 1),
  project_naam: `${25000 + i * 13} ${PLAATSEN[i % PLAATSEN.length]}`,
  opdrachtgever: OPDRACHTGEVERS[i % OPDRACHTGEVERS.length],
  soort_werk: i % 3 === 0 ? 'montage' : null,
  looptijd_tot: null,
  is_actief: true,
  week_man: 0,
  per_datum: {} as Record<string, unknown[]>,
  werkopdrachten: [] as unknown[],
  werkopdracht_overrides: {} as Record<string, unknown[]>,
  week_uren: undefined as unknown,
}))
// Planning zoals de mockup: Arnhem ma–wo 4 man, Nieuwegein ma–vr 3, Rijssen ma–wo 2/5, Apeldoorn do–vr 3.
projecten[0].per_datum = {
  [D[0]]: [k(0, { uren_status: 'gekeurd', uren: '8', uren_detail: '8 u · gekeurd' }), k(2, { uren_status: 'ingevuld', uren: '8' }), k(3, { uren_status: 'ingevuld', uren: '8' }), k(4)],
  [D[1]]: [k(0), k(2), k(3), k(4)],
  [D[2]]: [k(0), k(2), k(3), k(4)],
}
projecten[0].werkopdrachten = [{ groep_id: 'w1', van: '2026-09-01', tot_en_met: '2026-09-30', tekst: 'opbouw fase 2 — 08:00 · bus 2' }]
projecten[0].week_uren = { ingevuld_uren: '24', gekeurd_uren: '8', open_aantal: 2, zonder_uren_aantal: 8 }
projecten[1].per_datum = Object.fromEntries(D.map((d) => [d, [k(1), k(5), k(6)]]))
projecten[1].werkopdrachten = [{ groep_id: 'w2', van: '2026-09-01', tot_en_met: '2026-10-30', tekst: 'Blokhoeve · 07:30' }]
projecten[2].per_datum = { [D[0]]: [k(7), k(8)], [D[1]]: [k(7), k(8)], [D[2]]: [k(7), k(8), k(2), k(9), k(10), k(11)] } // wo: Sanli dubbel + 6 man
projecten[3].per_datum = { [D[3]]: [k(0), k(2), k(4)], [D[4]]: [k(0), k(2), k(4)] }
for (const p of projecten) p.week_man = Math.max(0, ...Object.values(p.per_datum).map((x) => x.length))

const PLANNING = {
  jaar: 2026,
  weeknummer: 38,
  maandag: D[0],
  zondag: '2026-09-20',
  projecten,
  pool: NAMEN.map((naam, i) => ({
    gebruiker_id: G[i],
    naam,
    rol: rol(i),
    geplande_dagen: String(Object.values(projecten).reduce((s, p) => s + Object.values(p.per_datum).filter((x) => x.some((y) => (y as { gebruiker_id: string }).gebruiker_id === G[i])).length, 0)),
    afwezig_tot: i === 11 ? '2026-09-25' : null,
    dossier_onvolledig: i === 9,
  })),
  buiten_planning: [],
  dubbele_dagen: [],
  dubbele_dag_tellers: [],
  reserveringen: [{ id: 'r1', project_id: P(5), projectnaam: projecten[4].project_naam, datum: D[3] }],
  afwezigheid: [
    { id: 'a1', gebruiker_id: G[3], van: D[3], tot: D[3], reden: 'verlof' },
    { id: 'a2', gebruiker_id: G[11], van: '2026-09-14', tot: '2026-09-25', reden: 'vakantie' },
  ],
  wachtrisico: [],
}
projecten[1].per_datum[D[3]] = [k(1), k(5), k(3)] // Yücetaş afwezig do maar gepland

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

window.fetch = (invoer: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = typeof invoer === 'string' ? invoer : invoer instanceof URL ? invoer.toString() : invoer.url
  if (url === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken() }))
  if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADMIN, naam: 'Universal Steigerbouw B.V.', uren_meerwerk_ingeschakeld: true }] }))
  if (url === '/uren/kantoor/mijn-toegang')
    return Promise.resolve(jsonResponse({ heeft_meerwerk_recht: true, administraties_met_opt_in: [ADMIN], aantal_administraties_in_scope: 1, is_beheerder: true, heeft_veldwerkerbeheer_recht: true, is_beheerder_of_bp: true, mag_project_aanmaken: true }))
  if (url.includes('/uren/kantoor/planning') && init?.method === 'POST') {
    const body = JSON.parse(String(init.body ?? '{}')) as { items?: unknown[] }
    if (url.includes('/bulk')) return Promise.resolve(jsonResponse({ correlatie_id: 'c1', aangemaakt: body.items ?? [], resultaten: (body.items ?? []).map((i) => ({ ...(i as object), dagdeel: 'heel', uitkomst: 'gedaan', reden: null, conflict: null, conflict_projectnaam: null })) }))
    return Promise.resolve(new Response(null, { status: 204 }))
  }
  if (url.includes('/uren/kantoor/planning')) return Promise.resolve(jsonResponse(PLANNING))
  if (url.includes('/uren/kantoor/werkopdrachten')) return Promise.resolve(jsonResponse([]))
  if (url.includes('/materiaal/') || url.includes('/transport')) return Promise.resolve(jsonResponse([]))
  return Promise.resolve(jsonResponse({ detail: `harnas: onbekend pad ${url}` }, 404))
}

if (params.get('donker') === '1') {
  document.documentElement.classList.add('dark')
  document.body.classList.add('dark')
}
try {
  window.localStorage.setItem('planning-weergave', PER_PROJECT ? 'project' : 'dag')
} catch {
  /* geen opslag */
}

const start = new URLSearchParams({ administratie: ADMIN, week: WEEK })
if (KAART) start.set('kaart', `${P(1)}|${D[0]}`)
if (TAB) start.set('tab', TAB)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MemoryRouter initialEntries={[`/planning?${start.toString()}`]}>
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
              <div className="nav-kop">Werk</div>
              <a className="nav-item">Werkvoorraad</a>
              <a className="nav-item actief">Planning</a>
            </nav>
            <div className="main">
              <div className="content">
                <Routes>
                  <Route path="/planning" element={<PlanningScreen />} />
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
