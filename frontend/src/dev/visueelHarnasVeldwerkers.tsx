// Visueel harnas Beheer › Veldwerkers (veldwerkers-run 14-09): het echte scherm met gemockte fetch, voor headless
// verificatie zonder backend/login — patroon visueelHarnasGebruikers.tsx.
//   npx vite --port 5199  →  http://localhost:5199/harness-veldwerkers.html [?donker=1]
// Varianten:
//   ?breed=1                     brede variant: langste namen/e-mails, álle koppelingen (projecten, bureaus, crediteur
//                                mét tarief + ⚡ autoboeken), alle dossier-standen (compleet / 2 ontbreken / verlopen /
//                                ter controle / geblokkeerd / —) en de ⚠-correctie-detailregel
//   ?filter=dossier_onvolledig   de deeplink van de klantpagina (KlantStanden "ZZP-dossiers — signaal") mét
//                                &administratie=<id> — de filterstand zoals Peter 'm ziet
//   ?rol=recht                   niet-Beheerder (B+P) mét het recht 'veldwerkerbeheer' → zelfde scherm
//   ?rol=geen                    niet-Beheerder zonder recht → /uren/beheer/veldgebruikers geeft 403 → leesbare melding
// Probes op <body> (uit te lezen met --dump-dom):
//   data-veldwerkers-kolombreedtes   "kop=offsetWidth;…" van de tabel
//   data-veldwerkers-chipregels      max offsetHeight van .chips-regel (één regel ≈ ≤ 24 px)
//   data-veldwerkers-tabelscroll     scrollWidth − clientWidth van .tabel-scroll (0 = geen interne scroll)
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { ToastProvider } from '../ui/basis'
import { VeldwerkersScreen } from '../veldwerkers/VeldwerkersScreen'
import { OverflowBadge } from './overflowBadge'
import '../index.css'

const EIGEN_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const ADMIN_1 = 'dddddddd-0000-0000-0000-00000000000d'
const ADMIN_2 = 'eeeeeeee-0000-0000-0000-00000000000e'
const ADMIN_3 = 'ffffffff-0000-0000-0000-0000000000f0'

const params = new URLSearchParams(window.location.search)
const BREED = params.has('breed')
const ROL = params.get('rol') // null = beheerder, 'recht' = B+P mét recht, 'geen' = B+P zonder recht
const FILTER = params.get('filter')
const ADMINISTRATIE = params.get('administratie')

function fakeAccessToken(): string {
  const payload = btoa(JSON.stringify({ sub: EIGEN_ID, rol: ROL ? 'boekhouding_projecten' : 'beheerder' }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

const ADMINISTRATIES = [
  { id: ADMIN_1, naam: 'Molenhof Beheer B.V.' },
  { id: ADMIN_2, naam: 'Kempen Facilities B.V.' },
  { id: ADMIN_3, naam: 'Universal Steigerbouw B.V.', uren_meerwerk_ingeschakeld: true },
]

const UNIVERSAL = 'Universal Steigerbouw B.V.'
const P1 = { administratie_id: ADMIN_3, administratie_naam: UNIVERSAL, project_id: 'p1', project_naam: '26049 Hoofddorp (Dura Vermeer)', bron: 'planning' }
const P2 = { administratie_id: ADMIN_3, administratie_naam: UNIVERSAL, project_id: 'p2', project_naam: '26051 Amsterdam (BAM)', bron: 'weekstaat' }

function dossier(overrides: Record<string, unknown> = {}) {
  return {
    administratie_id: ADMIN_3,
    administratie_naam: UNIVERSAL,
    aantal_verplicht: 6,
    aantal_aanwezig: 6,
    aantal_ontbrekend: 0,
    aantal_verlopen: 0,
    aantal_verloopt_binnenkort: 0,
    aantal_ter_controle: 0,
    compleet: true,
    geblokkeerd: false,
    herinneringen_teller: 0,
    herinneringen_max: 3,
    laatste_herinnering_op: null,
    ...overrides,
  }
}

const MILAN = '66666666-0000-0000-0000-000000000066'
const THIJS = '99999999-0000-0000-0000-000000000099'
const ANNE = '11111111-0000-0000-0000-000000000011'
const BART = '22222222-0000-0000-0000-000000000022'

/** Basis: ZZP'er compleet, uitvoerder, detacheerder, ZZP'er uitgenodigd. */
const VELDGEBRUIKERS = [
  {
    gebruiker_id: MILAN,
    naam: 'Milan Kowalczyk',
    e_mail: 'milan@steigerbouw-montage.nl',
    rol: 'zzper',
    status: 'actief',
    administratie_ids: [ADMIN_3],
    projecten: [P1, P2],
    zzpers: [],
    crediteuren: [{ administratie_id: ADMIN_3, administratie_naam: UNIVERSAL, vendor_id: 'v1', vendor_naam: 'Kowalczyk Montage', uurtarief: '42.50', autoboeken_ingeschakeld: true }],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    dossiers: [dossier()],
    recentste_planning_administratie_id: ADMIN_3,
  },
  {
    gebruiker_id: '88888888-0000-0000-0000-000000000088',
    naam: 'Stefan Bouwmeester',
    e_mail: 's.bouwmeester@universal-steigers.nl',
    rol: 'uitvoerder',
    status: 'actief',
    administratie_ids: [ADMIN_3],
    projecten: [P1],
    zzpers: [],
    crediteuren: [],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    dossiers: [dossier({ aantal_verplicht: 2, aantal_aanwezig: 1, aantal_ter_controle: 1, compleet: false })],
  },
  {
    gebruiker_id: '77777777-0000-0000-0000-000000000077',
    naam: 'Karin Steenbergen',
    e_mail: 'k.steenbergen@detacheringsbureau-bouw.nl',
    rol: 'detacheerder',
    status: 'actief',
    administratie_ids: [ADMIN_3],
    projecten: [],
    zzpers: [
      { gebruiker_id: MILAN, naam: 'Milan Kowalczyk', uurtarief: '51.00' },
      { gebruiker_id: THIJS, naam: 'Thijs van den Heuvel', uurtarief: null },
    ],
    crediteuren: [{ administratie_id: ADMIN_3, administratie_naam: UNIVERSAL, vendor_id: 'v2', vendor_naam: 'Detacheringsbureau Bouw & Techniek B.V.', uurtarief: null, autoboeken_ingeschakeld: false }],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    dossiers: [],
  },
  {
    gebruiker_id: THIJS,
    naam: 'Thijs van den Heuvel',
    e_mail: 't.vandenheuvel@zzp-steigers.nl',
    rol: 'zzper',
    status: 'uitgenodigd',
    administratie_ids: [ADMIN_3],
    projecten: [],
    zzpers: [],
    crediteuren: [],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    dossiers: [dossier({ aantal_aanwezig: 4, aantal_ontbrekend: 2, compleet: false })],
  },
]

/** Breed: de langste realistische inhoud per kolom, alle dossier-standen en chips tegelijk aan. */
const VELDGEBRUIKERS_BREED = [
  ...VELDGEBRUIKERS.map((v) =>
    v.gebruiker_id === MILAN ? { ...v, uren_afwijking_aantal: 2, uren_afwijking_som: '3.5', dossiers: [dossier({ aantal_verloopt_binnenkort: 1 })] } : v,
  ),
  {
    gebruiker_id: ANNE,
    naam: 'Anne-Marie van der Westerlaken-Nieuwenhuizen',
    e_mail: 'anne-marie.vanderwesterlaken@steigerbouw-en-montagebedrijf-oost-nederland.nl',
    rol: 'zzper',
    status: 'geblokkeerd',
    administratie_ids: [ADMIN_2, ADMIN_3],
    projecten: [P1, P2],
    zzpers: [],
    crediteuren: [
      { administratie_id: ADMIN_3, administratie_naam: UNIVERSAL, vendor_id: 'v3', vendor_naam: 'Van der Westerlaken Steigerbouw & Montage V.O.F.', uurtarief: '47.25', autoboeken_ingeschakeld: true },
      { administratie_id: ADMIN_2, administratie_naam: 'Kempen Facilities B.V.', vendor_id: 'v4', vendor_naam: 'Westerlaken Facilitair', uurtarief: null, autoboeken_ingeschakeld: false },
    ],
    uren_afwijking_aantal: 5,
    uren_afwijking_som: '12.25',
    dossiers: [dossier({ aantal_aanwezig: 3, aantal_ontbrekend: 2, aantal_verlopen: 1, compleet: false, geblokkeerd: true })],
  },
  {
    gebruiker_id: BART,
    naam: 'Bartholomeus Groenewegen',
    e_mail: 'b.groenewegen@zzp-steigers.nl',
    rol: 'zzper',
    status: 'wacht_op_passkey',
    administratie_ids: [ADMIN_3],
    projecten: [P2],
    zzpers: [],
    crediteuren: [],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    dossiers: [dossier({ aantal_aanwezig: 5, aantal_verlopen: 1, compleet: false })],
  },
  {
    gebruiker_id: '33333333-0000-0000-0000-000000000033',
    naam: 'Cornelia Schoonderbeek-Verhoeven',
    e_mail: 'c.schoonderbeek@detacheringsbureau-bouw-en-infra-nederland.nl',
    rol: 'detacheerder',
    status: 'actief',
    administratie_ids: [ADMIN_3],
    projecten: [],
    zzpers: [
      { gebruiker_id: ANNE, naam: 'Anne-Marie van der Westerlaken-Nieuwenhuizen', uurtarief: '58.00' },
      { gebruiker_id: BART, naam: 'Bartholomeus Groenewegen', uurtarief: '49.50' },
      { gebruiker_id: THIJS, naam: 'Thijs van den Heuvel', uurtarief: null },
    ],
    crediteuren: [],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    dossiers: [],
  },
]

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const echteFetch = window.fetch.bind(window)
window.fetch = (invoer: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = typeof invoer === 'string' ? invoer : invoer instanceof URL ? invoer.toString() : invoer.url
  if (url === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken() }))
  if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: ADMINISTRATIES }))
  if (url === '/uren/kantoor/mijn-toegang') {
    return Promise.resolve(
      jsonResponse({
        heeft_meerwerk_recht: true,
        administraties_met_opt_in: [ADMIN_3],
        aantal_administraties_in_scope: ADMINISTRATIES.length,
        is_beheerder: !ROL,
        heeft_veldwerkerbeheer_recht: ROL !== 'geen',
        is_beheerder_of_bp: true,
      }),
    )
  }
  if (url === '/uren/beheer/veldgebruikers') {
    if (ROL === 'geen') return Promise.resolve(jsonResponse({ detail: "Geen recht op veldwerkerbeheer (Beheerder of recht 'veldwerkerbeheer' vereist)." }, 403))
    return Promise.resolve(jsonResponse(BREED ? VELDGEBRUIKERS_BREED : VELDGEBRUIKERS))
  }
  if (url.match(/\/administraties\/[^/]+\/crediteuren/)) return Promise.resolve(jsonResponse({ crediteuren: [] }))
  return echteFetch(invoer, init)
}

if (params.has('donker')) {
  document.documentElement.classList.add('dark')
  document.body.classList.add('dark')
}

// Probes (patroon visueelHarnasGebruikers): meetbare feiten i.p.v. oogschatting.
window.setTimeout(() => {
  const tabellen = Array.from(document.querySelectorAll<HTMLTableElement>('.gebruikers-tabel'))
  document.body.dataset.veldwerkersKolombreedtes = tabellen
    .map((t) =>
      Array.from(t.querySelectorAll<HTMLTableCellElement>('thead th'))
        .map((th) => `${th.textContent?.trim() || 'acties'}=${th.offsetWidth}`)
        .join(';'),
    )
    .join('|')
  document.body.dataset.veldwerkersChipregels = tabellen
    .map((t) => Math.max(0, ...Array.from(t.querySelectorAll<HTMLElement>('.chips-regel')).map((c) => c.offsetHeight)))
    .join('|')
  document.body.dataset.veldwerkersTabelscroll = Array.from(document.querySelectorAll<HTMLElement>('.tabel-scroll'))
    .map((s) => s.scrollWidth - s.clientWidth)
    .join('|')
}, 1500)

const startParams = new URLSearchParams()
if (FILTER) startParams.set('filter', FILTER)
if (ADMINISTRATIE) startParams.set('administratie', ADMINISTRATIE)
const START = `/veldwerkers${startParams.size > 0 ? `?${startParams.toString()}` : ''}`

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MemoryRouter initialEntries={[START]}>
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
              {!ROL && <a className="nav-item">Gebruikers</a>}
              <a className="nav-item actief">Veldwerkers</a>
              <a className="nav-item">Instellingen</a>
            </nav>
            <div className="main">
              <div className="content">
                <Routes>
                  <Route path="/veldwerkers" element={<VeldwerkersScreen />} />
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
