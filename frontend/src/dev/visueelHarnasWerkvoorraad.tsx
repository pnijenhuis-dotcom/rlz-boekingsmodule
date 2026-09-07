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
import { ProjectenKantoorbreedScreen } from '../projecten/ProjectenKantoorbreedScreen'
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
    // C9 (fixrun 07-09), variant ?twijfel=1: de breedste rij — twijfelchip "factuur of offerte?" +
    // soort-toggle + suggestie-chip + lange tenaamstelling + picker + beide actieknoppen.
    ...(new URLSearchParams(window.location.search).has('twijfel')
      ? [
          {
            document_id: 'dddddddd-0000-0000-0000-000000000003',
            bestandsnaam: 'offerte_of_factuur_steigerwerk_koningstraat_fase_2_definitief.pdf',
            soort: 'inkoopfactuur',
            bron: 'email',
            afzender_hint: 'administratie@confide-steigerverhuur-nederland.nl',
            tenaamstelling: 'Universal Steigerbouw Nederland B.V. t.a.v. de afdeling crediteurenadministratie Eindhoven',
            suggestie_administratie_id: ADMIN_2,
            suggestie_bron: 'tenaamstelling',
            reden: 'documentsoort_onduidelijk',
            reden_label: 'factuur of offerte? — kies bij toewijzen',
            aangemaakt_op: '2026-09-07T08:15:00Z',
            splitsing_id: null,
            splitsing_voorstel: null,
          },
        ]
      : []),
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

// C5 (07-09): Inzicht › Projecten kantoorbreed (?projecten=1) — breedste realistische rij: lange projectnaam +
// werknummer, alle vier chips gevuld (negatieve marge mét onbepaalbare uren, overschreden offerte, ontbrekende
// én te-keuren weekstaten, m²-voortgang) naast een lege rij (geen cijfers / n.v.t.).
const PROJECTEN_KANTOORBREED = {
  rijen: [
    {
      administratie_id: ADMIN_1,
      administratie_naam: 'Universal Steigerbouw B.V.',
      project_id: '33333333-0000-0000-0000-000000000001',
      naam: '26014 Breda Molenstraat-Zuid fase 2 (Moeskops Bouw & Ontwikkeling)',
      opdrachtgever: 'Moeskops Bouw & Ontwikkeling B.V.',
      werknummer_opdrachtgever: 'MB-88412-2026-BRD',
      looptijd_tot: '2026-12-31',
      resultaat: { baten: '128400.00', kosten: '141260.50', marge: '-12860.50', marge_pct: '-10.0', onbepaalbaar_uren: '36', heeft_cijfers: true },
      verplichtingen: { aantal: 3, goedgekeurd_excl: '148500.00', verbruikt_excl: '151900.00', percentage: 102, overschreden: 1 },
      weekstaten: { van_toepassing: true, ontbrekend: 3, oudste_ontbrekende_jaar: 2026, oudste_ontbrekende_week: 33, te_keuren: 2, concept: 1 },
      m2: { gebouwd_m2: '3280.00', contract_m2: '4200', percentage: 78, doorlopende_huur: false },
      signalen: ['verplichting_overschreden', 'marge_negatief', 'weekstaat_ontbreekt', 'te_keuren'],
      urgentie: 15,
    },
    {
      administratie_id: ADMIN_1,
      administratie_naam: 'Universal Steigerbouw B.V.',
      project_id: '33333333-0000-0000-0000-000000000002',
      naam: '26021 Tilburg (Heijmans)',
      opdrachtgever: 'Heijmans Infra',
      werknummer_opdrachtgever: null,
      looptijd_tot: null,
      resultaat: { baten: '42800.00', kosten: '31200.00', marge: '11600.00', marge_pct: '27.1', onbepaalbaar_uren: '0', heeft_cijfers: true },
      verplichtingen: { aantal: 1, goedgekeurd_excl: '48500.00', verbruikt_excl: '27150.00', percentage: 56, overschreden: 0 },
      weekstaten: { van_toepassing: true, ontbrekend: 0, oudste_ontbrekende_jaar: null, oudste_ontbrekende_week: null, te_keuren: 0, concept: 0 },
      m2: { gebouwd_m2: '0', contract_m2: null, percentage: null, doorlopende_huur: true },
      signalen: [],
      urgentie: 0,
    },
    {
      administratie_id: '22222222-0000-0000-0000-000000000002',
      administratie_naam: 'Kempen Facilities B.V.',
      project_id: '33333333-0000-0000-0000-000000000003',
      naam: 'Kantoorpand Eindhoven',
      opdrachtgever: null,
      werknummer_opdrachtgever: null,
      looptijd_tot: null,
      resultaat: { baten: '0', kosten: '0', marge: '0', marge_pct: null, onbepaalbaar_uren: '0', heeft_cijfers: false },
      verplichtingen: { aantal: 0, goedgekeurd_excl: '0', verbruikt_excl: '0', percentage: null, overschreden: 0 },
      weekstaten: { van_toepassing: false, ontbrekend: 0, oudste_ontbrekende_jaar: null, oudste_ontbrekende_week: null, te_keuren: 0, concept: 0 },
      m2: { gebouwd_m2: '0', contract_m2: null, percentage: null, doorlopende_huur: false },
      signalen: [],
      urgentie: 0,
    },
  ],
  totaal: 3,
  pagina: 1,
  per_pagina: 25,
  administraties_in_selectie: 2,
  tellers: { projecten: 3, administraties: 2, met_signaal: 1, verplichting_overschreden: 1, marge_negatief: 1, weekstaat_ontbreekt: 1, te_keuren: 1 },
  facetten: {
    status: { alle: 3, signaal: 1, verplichting_overschreden: 1, marge_negatief: 1, weekstaat_ontbreekt: 1, te_keuren: 1, op_schema: 2 },
    administraties: [
      { administratie_id: ADMIN_1, naam: 'Universal Steigerbouw B.V.', aantal: 2 },
      { administratie_id: '22222222-0000-0000-0000-000000000002', naam: 'Kempen Facilities B.V.', aantal: 1 },
    ],
  },
}

const echteFetch = window.fetch.bind(window)
window.fetch = (invoer: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = String(invoer)
  if (url.endsWith('/auth/administraties')) return Promise.resolve(jsonResponse({ administraties: ADMINISTRATIES }))
  if (url.includes('/projecten/kantoorbreed')) return Promise.resolve(jsonResponse(PROJECTEN_KANTOORBREED))
  if (url.endsWith('/werkvoorraad/overzicht')) return Promise.resolve(jsonResponse(WERKVOORRAAD_OVERZICHT))
  if (url.endsWith('/bank/overzicht')) return Promise.resolve(jsonResponse(BANK_OVERZICHT))
  if (url.includes('/doorbelasting/') && url.endsWith('/spiegel-taken')) {
    // Eén open spiegel-taak bij Kempen Facilities → de extra kolom "Spiegel-taken" rendert mee.
    return Promise.resolve(jsonResponse(url.includes(ADMIN_1) ? [{ id: 'taak' }] : []))
  }
  if (url.endsWith('/verzamelbak')) return Promise.resolve(jsonResponse(VERZAMELBAK))
  if (url.includes('/documenten')) return Promise.resolve(jsonResponse(DOCUMENTEN))
  if (url.endsWith('/medewerkers')) return Promise.resolve(jsonResponse(MEDEWERKERS))
  // Klantpagina = standen (IA-verbouwing 15-08): bank per rekening + open vragen.
  if (url.includes('/rekeningen')) {
    return Promise.resolve(
      jsonResponse({
        rekeningen: [
          { id: 'rek-1', naam: 'Rabobank zakelijk', iban: 'NL02RABO0123456789', open_mutaties: 12 },
          { id: 'rek-2', naam: 'G-rekening', iban: 'NL10INGB0000002277', open_mutaties: 3 },
          { id: 'rek-3', naam: 'Kas', iban: null, open_mutaties: 0 },
        ],
        laatste_sync_op: null,
        ooit_gesynchroniseerd: true,
        heeft_bankaanlevering: true,
      }),
    )
  }
  if (url.includes('/vragen')) {
    return Promise.resolve(
      jsonResponse({
        vragen: [
          {
            id: 'vraag-1',
            document_id: 'doc-1',
            document_bestandsnaam: 'factuur_vve_dorpsstraat.pdf',
            document_status: 'vraag_open',
            totaalbedrag: '418.00',
            vraag_tekst: 'Nieuwe kostenpost "servicekosten VvE" — welk grootboek?',
            status: 'open',
            status_voor_vraag: 'te_controleren',
            gesteld_door: 'g-1',
            gesteld_op: '2026-08-14T09:00:00Z',
            toegewezen_aan: 'g-2',
            antwoord_tekst: null,
            beantwoord_door: null,
            beantwoord_op: null,
            ingetrokken_door: null,
            ingetrokken_op: null,
            ingetrokken_reden: null,
          },
        ],
      }),
    )
  }
  return echteFetch(invoer, init)
}

const PARAMS = new URLSearchParams(window.location.search)
// IA-verbouwing 15-08: ?klant=1 = klantpagina (standen), ?docs=1 = documenten-deelscherm.
// C5 (07-09): ?projecten=1 = Inzicht › Projecten kantoorbreed.
const START_URL = PARAMS.has('projecten')
  ? '/projecten'
  : PARAMS.has('docs')
    ? `/?administratie=${ADMIN_1}&sectie=documenten`
    : PARAMS.has('klant')
      ? `/?administratie=${ADMIN_1}`
      : '/'

// C9 (07-09): rijhoogte-probe voor headless verificatie — schrijft de offsetHeight van élke
// verzamelbak-rij als data-attribuut op <body> (uit te lezen met --dump-dom), zodat "constante
// rijhoogte" een meetbaar feit is en geen oogschatting.
window.setTimeout(() => {
  const rijen = Array.from(document.querySelectorAll<HTMLTableRowElement>('.verzamelbak-tabel tbody tr'))
  document.body.dataset.verzamelbakRijhoogtes = rijen.map((r) => r.offsetHeight).join(',')
}, 1500)

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
              <Route path="/projecten" element={<ProjectenKantoorbreedScreen />} />
            </Routes>
          </div>
        </div>
      </div>
      <OverflowBadge />
    </MemoryRouter>
  </StrictMode>,
)
