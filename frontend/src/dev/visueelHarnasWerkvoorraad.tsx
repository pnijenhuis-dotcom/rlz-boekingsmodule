// Visueel harnas voor het werkvoorraad-scherm (dev-gereedschap, geen productie-entry — vite
// build bundelt alleen index.html): de echte WerkvoorraadScreen met gemockte fetch in de echte
// Shell-layout, zodat headless Chrome het responsive gedrag pixel-echt kan vastleggen zonder
// backend of login (responsive-bug Peter 2026-08-15: layout schuift niet goed in elkaar bij
// versmallen). Gebruik:
//   npx vite --port 5199  →  http://localhost:5199/harness-werkvoorraad.html
//   variant: ?klant=1 (klantpagina met documentenlijst i.p.v. de klantenlijst-ingang)
//   screenshot: "…/Google Chrome" --headless --screenshot=uit.png --window-size=420,1400 <url>
// De badge linksonder (gedeeld, overflowBadge.tsx) meet horizontale overflow. De data bootst de
// breedste realistische stand na: alle tellerkolommen gevuld + IBAN-chip in de naamcel
// (klantenlijst), lange bestandsnamen/afwijzingsredenen/duplicaat-verwijzing (documentenlijst)
// en een gevulde verzamelbak.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { WerkvoorraadScreen } from '../werkvoorraad/WerkvoorraadScreen'
import { OverflowBadge } from './overflowBadge'
import '../index.css'

const ADMIN_1 = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADMIN_2 = 'aaaaaaaa-0000-0000-0000-000000000002'
const ADMIN_3 = 'aaaaaaaa-0000-0000-0000-000000000003'

const ADMINISTRATIES = [
  { id: ADMIN_1, naam: 'Kempen Facilities B.V.' },
  { id: ADMIN_2, naam: 'Universal Steigerbouw Nederland B.V.' },
  { id: ADMIN_3, naam: 'BLOW B.V.' },
]

// Breedste realistische klantenlijst: alle kolommen gevuld, IBAN-accorderingschip in de
// naamcel, spiegel-taken-kolom zichtbaar (Kempen-doorbelasting).
const WERKVOORRAAD_OVERZICHT = {
  klanten: [
    {
      administratie_id: ADMIN_1,
      naam: 'Kempen Facilities B.V.',
      te_controleren: 2,
      klaar_om_te_boeken: 2,
      vragen: 1,
      afgewezen: 1,
      bij_klant: 1,
      iban_wachtend: 2,
    },
    {
      administratie_id: ADMIN_2,
      naam: 'Universal Steigerbouw Nederland B.V.',
      te_controleren: 1,
      klaar_om_te_boeken: 0,
      vragen: 1,
      afgewezen: 0,
      bij_klant: 0,
      iban_wachtend: 0,
    },
    {
      administratie_id: ADMIN_3,
      naam: 'BLOW B.V.',
      te_controleren: 0,
      klaar_om_te_boeken: 1,
      vragen: 0,
      afgewezen: 0,
      bij_klant: 1,
      iban_wachtend: 0,
    },
  ],
}

const BANK_OVERZICHT = {
  klanten: [
    {
      administratie_id: ADMIN_1,
      naam: 'Kempen Facilities B.V.',
      open_mutaties: 6,
      oudste_open_datum: '2026-08-01',
      rekeningen: ['NL02RABO0123456789'],
      laatste_sync_op: '2026-08-15T06:00:00Z',
      ooit_gesynchroniseerd: true,
    },
    {
      administratie_id: ADMIN_3,
      naam: 'BLOW B.V.',
      open_mutaties: 3,
      oudste_open_datum: '2026-08-05',
      rekeningen: ['NL91ABNA0417164300'],
      laatste_sync_op: '2026-08-15T06:00:00Z',
      ooit_gesynchroniseerd: true,
    },
  ],
}

const VERZAMELBAK = {
  items: [
    {
      document_id: 'dddddddd-0000-0000-0000-000000000001',
      bestandsnaam: 'factuur_energie_gecombineerd_juli_2026.pdf',
      soort: 'inkoopfactuur',
      bron: 'email',
      afzender_hint: 'administratie@energieleverancier-nederland.nl',
      tenaamstelling: 'BLOW Holding B.V.',
      suggestie_administratie_id: ADMIN_3,
      suggestie_bron: 'tenaamstelling',
      aangemaakt_op: '2026-08-14T09:12:00Z',
      splitsing_id: null,
      splitsing_voorstel: null,
    },
    {
      document_id: 'dddddddd-0000-0000-0000-000000000002',
      bestandsnaam: 'scan_whatsapp_bonnetje.jpg.pdf',
      soort: 'inkoopfactuur',
      bron: 'upload',
      afzender_hint: null,
      tenaamstelling: null,
      suggestie_administratie_id: null,
      suggestie_bron: null,
      aangemaakt_op: '2026-08-14T10:30:00Z',
      splitsing_id: null,
      splitsing_voorstel: null,
    },
  ],
}

// Documentenlijst (klantpagina) — de breedste statuscel: duplicaatverwijzing met lange
// bestandsnaam, afwijzing met reden, automatisch-chip, plus een IBAN-wachtend document zodat
// de topbar-chips meerenderen.
const DOCUMENTEN = {
  documenten: [
    {
      id: 'bbbbbbbb-0000-0000-0000-000000000001',
      bestandsnaam: '20260064 Universal Steigerbouw week 27 herzonden kopie administratie.pdf',
      status: 'te_controleren',
      bron: 'upload',
      soort: 'inkoopfactuur',
      mogelijk_duplicaat_van: {
        document_id: 'bbbbbbbb-0000-0000-0000-000000000009',
        bestandsnaam: '20260064 Universal Steigerbouw week 27.pdf',
        aangemaakt_op: '2026-07-09T09:00:00Z',
      },
      toegewezen_aan: null,
      aangemaakt_op: '2026-08-10T14:03:00Z',
      laatst_gewijzigd_op: '2026-08-10T14:04:00Z',
      afwijzing: null,
      leverancier: 'Universal Steigerbouw Nederland B.V.',
      totaalbedrag: '2224.29',
      factuurdatum: '2026-07-08',
      automatisch_geboekt: false,
    },
    {
      id: 'bbbbbbbb-0000-0000-0000-000000000002',
      bestandsnaam: 'bouwmaat_2026-0642.pdf',
      status: 'vraag_open',
      bron: 'email',
      soort: 'inkoopfactuur',
      mogelijk_duplicaat_van: null,
      toegewezen_aan: '11111111-0000-0000-0000-000000000002',
      aangemaakt_op: '2026-08-11T08:00:00Z',
      laatst_gewijzigd_op: '2026-08-11T09:00:00Z',
      afwijzing: null,
      leverancier: 'Bouwmaat Nederland B.V.',
      totaalbedrag: '1847.23',
      factuurdatum: '2026-06-29',
      automatisch_geboekt: false,
    },
    {
      id: 'bbbbbbbb-0000-0000-0000-000000000003',
      bestandsnaam: 'technische_unie_202608.pdf',
      status: 'afgewezen',
      bron: 'email',
      soort: 'inkoopfactuur',
      mogelijk_duplicaat_van: null,
      toegewezen_aan: '11111111-0000-0000-0000-000000000001',
      aangemaakt_op: '2026-08-12T11:00:00Z',
      laatst_gewijzigd_op: '2026-08-12T12:00:00Z',
      afwijzing: {
        id: 'cccccccc-0000-0000-0000-000000000001',
        reden: 'G-rekeningsplitsing wijkt af van het contract (35% i.p.v. 25%) — eerst uitzoeken met de leverancier',
        afgewezen_door: '11111111-0000-0000-0000-000000000001',
        afgewezen_op: '2026-08-12T12:00:00Z',
        toegewezen_aan: '11111111-0000-0000-0000-000000000002',
        status_voor_afwijzing: 'te_controleren',
      },
      leverancier: 'Technische Unie B.V.',
      totaalbedrag: '391.44',
      factuurdatum: '2026-08-01',
      automatisch_geboekt: false,
    },
    {
      id: 'bbbbbbbb-0000-0000-0000-000000000004',
      bestandsnaam: 'kassarapport_week_32_blow_marge.pdf',
      status: 'geboekt',
      bron: 'upload',
      soort: 'kassarapport',
      mogelijk_duplicaat_van: null,
      toegewezen_aan: null,
      aangemaakt_op: '2026-08-13T09:00:00Z',
      laatst_gewijzigd_op: '2026-08-13T09:30:00Z',
      afwijzing: null,
      leverancier: null,
      totaalbedrag: '12480.55',
      factuurdatum: '2026-08-09',
      automatisch_geboekt: true,
    },
    {
      id: 'bbbbbbbb-0000-0000-0000-000000000005',
      bestandsnaam: 'universal_20260071_week28.pdf',
      status: 'wacht_op_iban_accordering',
      bron: 'email',
      soort: 'inkoopfactuur',
      mogelijk_duplicaat_van: null,
      toegewezen_aan: null,
      aangemaakt_op: '2026-08-14T07:45:00Z',
      laatst_gewijzigd_op: '2026-08-14T07:46:00Z',
      afwijzing: null,
      leverancier: 'Universal Steigerbouw Nederland B.V.',
      totaalbedrag: '4310.07',
      factuurdatum: '2026-07-15',
      automatisch_geboekt: false,
    },
  ],
}

const MEDEWERKERS = {
  medewerkers: [
    { id: '11111111-0000-0000-0000-000000000001', naam: 'Peter Nijenhuis' },
    { id: '11111111-0000-0000-0000-000000000002', naam: 'Medewerker Boekhouding' },
  ],
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

const echteFetch = window.fetch.bind(window)
window.fetch = (invoer: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = String(invoer)
  if (url.endsWith('/auth/administraties')) return Promise.resolve(jsonResponse({ administraties: ADMINISTRATIES }))
  if (url.endsWith('/werkvoorraad/overzicht')) return Promise.resolve(jsonResponse(WERKVOORRAAD_OVERZICHT))
  if (url.endsWith('/bank/overzicht')) return Promise.resolve(jsonResponse(BANK_OVERZICHT))
  if (url.includes('/doorbelasting/') && url.endsWith('/spiegel-taken')) {
    // Eén open spiegel-taak bij Kempen Facilities → de extra kolom "Spiegel-taken" rendert mee.
    return Promise.resolve(jsonResponse(url.includes(ADMIN_1) ? [{ id: 'taak' }] : []))
  }
  if (url.endsWith('/verzamelbak')) return Promise.resolve(jsonResponse(VERZAMELBAK))
  if (url.includes('/documenten')) return Promise.resolve(jsonResponse(DOCUMENTEN))
  if (url.endsWith('/medewerkers')) return Promise.resolve(jsonResponse(MEDEWERKERS))
  return echteFetch(invoer, init)
}

const PARAMS = new URLSearchParams(window.location.search)
const START_URL = PARAMS.has('klant') ? `/?administratie=${ADMIN_1}` : '/'

// ?donker=1 — dark mode voor headless verificatie (thema.ts-klassepatroon).
if (new URLSearchParams(window.location.search).has('donker')) {
  document.documentElement.classList.add('dark')
  document.body.classList.add('dark')
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MemoryRouter initialEntries={[START_URL]}>
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
          <a className="nav-item actief">Werkvoorraad</a>
        </nav>
        <div className="main">
          <div className="content">
            <Routes>
              <Route path="/" element={<WerkvoorraadScreen />} />
            </Routes>
          </div>
        </div>
      </div>
      <OverflowBadge />
    </MemoryRouter>
  </StrictMode>,
)
