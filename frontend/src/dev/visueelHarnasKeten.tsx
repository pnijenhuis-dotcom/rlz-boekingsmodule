// Gouden-set-harnas (blok 0 herstelrun "Basis eerst" 08-09-2026; dev-gereedschap, geen productie-entry — vite build
// bundelt alleen index.html): rendert het ECHTE controlescherm (DocumentDetailScreen) of de ECHTE documentenlijst
// (WerkvoorraadScreen, klantlanding) met de DTO's die de backend-ketentests (backend/tests/keten) exporteren naar
// src/dev/keten/<casus>.json — één stand voor backend en frontend. Gebruik:
//   npx vite --port 5199  →  /harness-keten.html?casus=h_bdo&scherm=detail   (scherm=lijst voor de documentenlijst)
//   casussen: a_universal_nederland | b_floor | c_spot_services | h_bdo (zie backend/tests/keten/casussen.py)
//   scherm=bank (blok 3 nachtrun 10/11-09): het ECHTE bankscherm (BankDetailScreen) op de bank-casus l_bank_cv_08-09 —
//   fixture-vorm `bank: { rekening_id, rekeningen, mutaties, afletter_opdrachten }` = exact de DTO's van
//   GET …/bank/rekeningen, …/mutaties en …/afletter-opdrachten (zie KetenBankFixture hieronder).
//   sweep + pixelvergelijking: scripts/keten_sweep.sh (baseline in scripts/keten_baseline/)
// Markers voor headless verificatie: <body data-keten-klaar="ja"> zodra de fixture-data door het scherm geladen is,
// data-keten-onbekend = API-paden die het harnas niet kende (leeg = alles gemockt). De OverflowBadge meet mee.
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { BankDetailScreen } from '../bank/BankDetailScreen'
import { DocumentDetailScreen } from '../document/DocumentDetailScreen'
import { WerkvoorraadScreen } from '../werkvoorraad/WerkvoorraadScreen'
import { OverflowBadge } from './overflowBadge'
import '../index.css'

/** Bank-casus (blok 3 nachtrun 10/11-09): de drie DTO's die het bankscherm bij openen ophaalt, zoals de backend-ketentest
 * ze exporteert (`administratie_naam` optioneel — anders de vaste harnasnaam). */
interface KetenBankFixture {
  rekening_id: string
  rekeningen: Record<string, unknown>
  mutaties: { mutaties: Array<Record<string, unknown>> }
  afletter_opdrachten?: Record<string, unknown>
}

interface KetenFixture {
  casus: string
  administratie_id: string
  administratie_naam?: string
  document_id?: string
  detail?: Record<string, unknown>
  boekvoorstel?: Record<string, unknown>
  checks?: Record<string, unknown>
  lijst?: { documenten: Array<Record<string, unknown> & { status: string }>; [k: string]: unknown }
  lijst_afgehandeld?: { documenten: Array<Record<string, unknown> & { status: string }>; [k: string]: unknown }
  stamgegevens?: Record<string, string>
  bank?: KetenBankFixture
}

const FIXTURES = import.meta.glob('./keten/*.json', { eager: true }) as Record<string, { default: KetenFixture }>
const PARAMS = new URLSearchParams(window.location.search)
const CASUS = PARAMS.get('casus') ?? 'h_bdo'
const SCHERM = PARAMS.get('scherm') ?? 'detail'
const fixture = FIXTURES[`./keten/${CASUS}.json`]?.default

if (!fixture) {
  document.body.innerHTML = `<pre>Onbekende casus '${CASUS}'. Beschikbaar: ${Object.keys(FIXTURES).join(', ')}</pre>`
  throw new Error(`gouden-set-harnas: casus ${CASUS} niet gevonden`)
}

const ADMINISTRATIE_ID = fixture.administratie_id
const DOCUMENT_ID = fixture.document_id ?? ''
const ADMINISTRATIE_NAAM = fixture.administratie_naam ?? 'Universal Steigerbouw B.V.'
const BANK = fixture.bank ?? null
if (SCHERM === 'bank' && !BANK) {
  document.body.innerHTML = `<pre>Casus '${CASUS}' heeft geen bank-fixture (sleutel "bank").</pre>`
  throw new Error(`gouden-set-harnas: casus ${CASUS} zonder bank-fixture`)
}
if (SCHERM !== 'bank' && (!fixture.detail || !fixture.lijst)) {
  document.body.innerHTML = `<pre>Casus '${CASUS}' heeft geen document-fixture (detail/lijst) — gebruik scherm=bank.</pre>`
  throw new Error(`gouden-set-harnas: casus ${CASUS} zonder document-fixture`)
}
const LEGE_LIJST = { documenten: [] as Array<Record<string, unknown> & { status: string }> }

// Stamgegevens zoals tests/keten/conftest.py ze in de testadministratie zet (vaste id's).
const GROOTBOEK = [
  { ledger_id: '44444444-0000-0000-0000-000000004400', code: '4400', naam: 'Inhuur onderaannemers', soort: 2 },
  { ledger_id: '44444444-0000-0000-0000-000000004600', code: '4600', naam: 'Huur materieel', soort: 2 },
  { ledger_id: '44444444-0000-0000-0000-000000004700', code: '4700', naam: 'Advies- en accountantskosten', soort: 2 },
]
const TAXRATES = [
  { id: '55555555-0000-0000-0000-000000000021', naam: 'NL, Hoog Tarief', percentage: '0.2100' },
  { id: '55555555-0000-0000-0000-000000000009', naam: 'NL, BTW verlegd (hoog)', percentage: '0.0000' },
  { id: '55555555-0000-0000-0000-000000000000', naam: 'NL, Geen BTW (Vrijgesteld)', percentage: '0.0000' },
]
const PROJECTEN = [
  { id: 'aaaaaaaa-0000-0000-0000-000000026049', naam: '26049 Hoofddorp (Grunsven)' },
  { id: 'aaaaaaaa-0000-0000-0000-000000025011', naam: '25011 Zwolle (Bouwbedrijf Zwolle)' },
  { id: 'aaaaaaaa-0000-0000-0000-000000026084', naam: '26084 Opdrachtgever A (Universal Nederland)' },
]
const CREDITEUREN = [
  { id: '33333333-0000-0000-0000-000000000001', naam: 'Universal Nederland B.V.' },
  { id: '33333333-0000-0000-0000-000000000002', naam: 'Floor Bouwliftenservice' },
  { id: '33333333-0000-0000-0000-000000000003', naam: 'Spot Services B.V.' },
  { id: '33333333-0000-0000-0000-000000000004', naam: 'BDO Accountancy, Tax & Legal B.V.' },
  { id: '33333333-0000-0000-0000-000000000005', naam: 'DCTE B.V. (Derks Computers, Telecom & Electronica)' },
  { id: '33333333-0000-0000-0000-000000000006', naam: 'Kader Consultancy & Interim B.V.' },
  { id: '33333333-0000-0000-0000-000000000007', naam: 'BOOT organiserend ingenieursburo B.V.' },
]
// Het beeld: de vervang-PDF uit de gouden set is een echte PDF, hier volstaat een minimale PDF (zelfde viewer-pad).
const MINI_PDF = `%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R>>endobj
4 0 obj<</Length 44>>stream
BT /F1 18 Tf 60 780 Td (Gouden set — beeld) Tj ET
endstream
endobj
trailer<</Root 1 0 R>>
%%EOF`

const LEEG_GEHEUGEN_VELD = { waarde: null, telling: 0, confidence: 0, oranje: false, reden: null, app_bevestigd: false }
const WACHTEN_STATUSSEN = new Set(['ter_accordering', 'vraag_open'])

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const onbekend: string[] = []
let dataGeladen = 0

function lijstVoor(url: URL): unknown {
  const bron = (url.searchParams.get('toon_afgehandeld') === 'true' ? fixture.lijst_afgehandeld : fixture.lijst) ?? LEGE_LIJST
  const groep = url.searchParams.get('groep')
  if (groep === 'wachten') return { ...bron, documenten: bron.documenten.filter((d) => WACHTEN_STATUSSEN.has(d.status)) }
  if (groep === 'kantoor') return { ...bron, documenten: bron.documenten.filter((d) => !WACHTEN_STATUSSEN.has(d.status)) }
  return bron
}

const echteFetch = window.fetch.bind(window)
window.fetch = (invoer: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const ruw = String(invoer instanceof Request ? invoer.url : invoer)
  const url = new URL(ruw, window.location.origin)
  const pad = url.pathname
  const methode = (init?.method ?? 'GET').toUpperCase()

  // Bank-casus (blok 3 nachtrun 10/11-09): de bank-routes vóór de generieke matches ('/rekeningen' hieronder geeft voor
  // de document-schermen bewust een lege lijst). Achtergrond-sync = overgeslagen (geen ronde, geen toast), panelen leeg.
  if (BANK) {
    if (pad.endsWith('/bank/rekeningen')) return Promise.resolve(jsonResponse(BANK.rekeningen))
    if (pad.includes('/bank/rekeningen/') && pad.endsWith('/mutaties') && methode === 'GET') {
      dataGeladen++
      return Promise.resolve(jsonResponse(BANK.mutaties))
    }
    if (pad.endsWith('/afletter-opdrachten')) {
      return Promise.resolve(jsonResponse(BANK.afletter_opdrachten ?? { opdrachten: [], aantal_oud: 0, toon_oud: false, oud_na_dagen: 30 }))
    }
    if (pad.endsWith('/bank/sync-achtergrond') && methode === 'POST') {
      return Promise.resolve(
        jsonResponse(
          { run_id: null, status: 'overgeslagen', overgeslagen: true, laatste_sync_op: (BANK.rekeningen as { laatste_sync_op?: string | null }).laatste_sync_op ?? null, resultaat: null, fout_reden: null },
          202,
        ),
      )
    }
    if (pad.endsWith('/bank/aanbetalingen')) return Promise.resolve(jsonResponse({ aanbetalingen: [] }))
    if (pad.endsWith('/splitsingen')) return Promise.resolve(jsonResponse({ splitsingen: [] }))
  }
  if (pad.endsWith('/bestand')) {
    return Promise.resolve(new Response(MINI_PDF, { status: 200, headers: { 'Content-Type': 'application/pdf' } }))
  }
  if (pad.includes('/accordering/documenten/')) return Promise.resolve(jsonResponse(null))
  if (pad.endsWith('/accordering/vervallen-meldingen')) return Promise.resolve(jsonResponse([]))
  if (pad.endsWith('/accordering/instellingen')) return Promise.resolve(jsonResponse({ ingeschakeld: false, lagen: [] }))
  if (pad.endsWith(`/documenten/${DOCUMENT_ID}`)) {
    dataGeladen++
    return Promise.resolve(jsonResponse(fixture.detail))
  }
  if (pad.endsWith('/boekvoorstel/checks')) return Promise.resolve(jsonResponse(fixture.checks))
  if (pad.endsWith('/boekvoorstel') && methode === 'GET') {
    dataGeladen++
    return Promise.resolve(jsonResponse(fixture.boekvoorstel))
  }
  if (pad.endsWith('/boekvoorstel') && methode === 'PUT') {
    return Promise.resolve(jsonResponse({ boekvoorstel: fixture.boekvoorstel, checks: fixture.checks, factuurmatch: null }))
  }
  if (pad.endsWith('/documenten') && methode === 'GET') {
    dataGeladen++
    return Promise.resolve(jsonResponse(lijstVoor(url)))
  }
  if (pad.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: GROOTBOEK }))
  if (pad.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: TAXRATES }))
  if (pad.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: CREDITEUREN }))
  if (pad.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: PROJECTEN }))
  if (pad.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: true }))
  if (pad.endsWith('/afdelingen')) return Promise.resolve(jsonResponse({ ingeschakeld: false, afdelingen: [] }))
  if (pad.endsWith('/boekingsgeheugen/voorstel')) {
    return Promise.resolve(jsonResponse({ gb: LEEG_GEHEUGEN_VELD, btw: LEEG_GEHEUGEN_VELD, project: LEEG_GEHEUGEN_VELD }))
  }
  if (pad.endsWith('/projectverdeling') && pad.includes('/documenten/')) {
    return Promise.resolve(
      jsonResponse({ document_id: DOCUMENT_ID, status: 'geen', opgeslagen: false, beschikbaar: false, vaste_regels: [], delen: [] }),
    )
  }
  if (pad.endsWith('/leveranciers-projectverdeling')) return Promise.resolve(jsonResponse({ leveranciers: [] }))
  if (pad.endsWith('/projectverdeling-instellingen')) return Promise.resolve(jsonResponse({ drempel_pct: '5.00', wachtweken: 4 }))
  if (pad.includes('/iban-accorderingen')) return Promise.resolve(jsonResponse({ accorderingen: [] }))
  if (pad.endsWith('/iban-accordeurs')) return Promise.resolve(jsonResponse({ accordeurs: [] }))
  if (pad.endsWith('/al-betaald') || pad.endsWith('/aanbetaling-open')) {
    return Promise.resolve(jsonResponse({ toetsbaar: false, treffers: [] }))
  }
  if (pad.endsWith('/factuurmatch/kandidaat-staten')) return Promise.resolve(jsonResponse({ staten: [] }))
  if (pad.endsWith('/tegenboek-toets')) {
    return Promise.resolve(
      jsonResponse({
        document_id: DOCUMENT_ID,
        storno_geblokkeerd: false,
        blokkade_melding: null,
        tegenboeken_beschikbaar: false,
        aanbod_reden: null,
        duplicaat_van_geboekt: [],
        tegenboeking: null,
      }),
    )
  }
  if (pad.endsWith('/terugkerend-signaal')) {
    return Promise.resolve(
      jsonResponse({ prijsstijging_pct: null, vorige_bedrag: null, vorige_datum: null, laatste_bedrag: null, patroon: null, leverancier: null }),
    )
  }
  if (pad.startsWith('/terugkerend') || pad.endsWith('/terugkerend')) return Promise.resolve(jsonResponse({ signalen: [] }))
  if (pad.endsWith('/eigenaar')) return Promise.resolve(jsonResponse({ eigenaar_gebruiker_id: null, eigenaar_naam: null }))
  if (pad.endsWith('/vragen') || pad.includes('/vragen?') || pad === '/vragen') return Promise.resolve(jsonResponse({ vragen: [] }))
  if (pad.endsWith('/medewerkers')) return Promise.resolve(jsonResponse({ medewerkers: [] }))
  if (pad.endsWith('/auth/administraties')) {
    return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: ADMINISTRATIE_NAAM }] }))
  }
  if (pad.endsWith('/werkvoorraad/overzicht')) {
    const kantoor = (fixture.lijst ?? LEGE_LIJST).documenten.filter((d) => !WACHTEN_STATUSSEN.has(d.status)).length
    return Promise.resolve(
      jsonResponse({
        klanten: [
          {
            administratie_id: ADMINISTRATIE_ID,
            naam: ADMINISTRATIE_NAAM,
            te_controleren: kantoor,
            klaar_om_te_boeken: 0,
            vragen: 0,
            afgewezen: 0,
            bij_klant: 0,
            iban_wachtend: 0,
          },
        ],
      }),
    )
  }
  if (pad.endsWith('/bank/overzicht')) return Promise.resolve(jsonResponse({ klanten: [] }))
  if (pad.endsWith('/verzamelbak')) return Promise.resolve(jsonResponse({ items: [] }))
  if (pad.endsWith('/rekeningen')) {
    return Promise.resolve(
      jsonResponse({ rekeningen: [], laatste_sync_op: null, ooit_gesynchroniseerd: true, heeft_bankaanlevering: true }),
    )
  }
  if (pad.includes('/doorbelasting/') && pad.endsWith('/spiegel-taken')) return Promise.resolve(jsonResponse([]))
  if (pad.includes('/uren/') || pad.includes('/weekstaten')) return Promise.resolve(jsonResponse({}))
  if (pad.startsWith('/administraties/') || pad.startsWith('/auth/') || pad.startsWith('/projecten')) {
    onbekend.push(`${methode} ${pad}`)
    document.body.dataset.ketenOnbekend = Array.from(new Set(onbekend)).join(' | ')
    return Promise.resolve(jsonResponse({}))
  }
  return echteFetch(invoer, init)
}

// Klaar-marker: de fixture-data is door het scherm opgehaald (detail + boekvoorstel, of de lijst) en React heeft
// geschilderd — headless Chrome leest 'm uit de DOM (--dump-dom) vóór het de screenshot als bewijs telt.
const NODIG = SCHERM === 'lijst' || SCHERM === 'bank' ? 1 : 2
const wachter = window.setInterval(() => {
  if (dataGeladen >= NODIG) {
    window.clearInterval(wachter)
    window.setTimeout(() => {
      document.body.dataset.ketenKlaar = 'ja'
      document.body.dataset.ketenCasus = CASUS
    }, 800)
  }
}, 100)

if (PARAMS.has('donker')) {
  document.documentElement.classList.add('dark')
  document.body.classList.add('dark')
}

const START_URL =
  SCHERM === 'bank'
    ? `/bank/${ADMINISTRATIE_ID}?rekening=${BANK?.rekening_id ?? ''}`
    : SCHERM === 'lijst'
      ? `/?administratie=${ADMINISTRATIE_ID}`
      : `/documenten/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`

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
              <Route path="/documenten/:administratieId/:documentId" element={<DocumentDetailScreen />} />
              <Route path="/bank/:administratieId" element={<BankDetailScreen />} />
            </Routes>
          </div>
        </div>
      </div>
      <OverflowBadge />
    </MemoryRouter>
  </StrictMode>,
)
