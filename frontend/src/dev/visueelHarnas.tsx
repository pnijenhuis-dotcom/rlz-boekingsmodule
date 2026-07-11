// Visueel harnas (dev-gereedschap, geen productie-entry — vite build bundelt alleen index.html):
// het echte controlescherm met gemockte fetch, in de echte Shell-layout (sidebar + main), zodat
// Chrome headless de review-split pixel-echt kan vastleggen zonder backend of login. Gebruik:
//   npx vite --port 5199  →  http://localhost:5199/harness.html
//   varianten: ?splitsen=1 (gesplitste regels), ?project=1 (projectplicht, extra kolom)
//   screenshot: "…/Google Chrome" --headless --screenshot=uit.png --window-size=1280,2000 <url>
// De badge linksonder meet horizontale overflow (rood = breder dan de viewport). Data bootst
// Peters kliktest na: lange leveranciersnaam zonder cache-match (fix 2-blok), meerregelig
// AI-voorstel (fix 3-vinkje).
import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { DocumentDetailScreen } from '../document/DocumentDetailScreen'
import '../index.css'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'

const MINI_PDF = `%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Contents 4 0 R>>endobj
4 0 obj<</Length 44>>stream
BT /F1 18 Tf 60 780 Td (Factuur 20260064) Tj ET
endstream
endobj
trailer<</Root 1 0 R>>
%%EOF`

const REGELS = [
  { o: 'Steigerhuur week 27 — trappentoren 26014 Amersfoort (Universal)', n: '1.240,00', b: '260,40' },
  { o: 'Transport en montage steigermateriaal, incl. hoogwerker', n: '385,50', b: '80,96' },
  { o: 'Veiligheidsnetten en gaasdoek per m² (verrekenbaar volgens contract)', n: '212,75', b: '44,68' },
].map((r) => ({
  omschrijving: r.o,
  netto_bedrag: r.n.replace('.', '').replace(',', '.'),
  btw_bedrag: r.b.replace(',', '.'),
  hoeveelheid: null,
  taxrate_id: null,
}))

const AI_VOORSTEL = {
  bron: 'ai',
  leverancier_naam: 'Universal Steigerbouw Nederland B.V.',
  factuurnummer: '202600645-2026-0917',
  factuurdatum: '2026-07-08',
  vervaldatum: '2026-08-07',
  valuta: 'EUR',
  totaal_excl: '1838.25',
  totaal_incl: '2224.29',
  btw_bedrag: '386.04',
  regelaantal: REGELS.length,
  regels: REGELS,
  zekerheid: {
    leverancier_naam: 0.93,
    factuurnummer: 0.97,
    factuurdatum: 0.96,
    vervaldatum: 0.71,
    totaal_excl: 0.95,
    totaal_incl: 0.95,
    btw_bedrag: 0.94,
    valuta: 0.99,
  },
  regel_zekerheid: [0.95, 0.9, 0.78],
  zekerheid_drempel: 0.8,
  vendor_suggestie: null,
  controle: {
    regelsom: '2224.29',
    regelsom_wijkt_af: false,
    onparseerbaar: [],
    lage_zekerheid: ['vervaldatum', 'regel 3'],
    bsn_verwijderd: 0,
    onvolledig: false,
  },
}

const DETAIL = {
  id: DOCUMENT_ID,
  administratie_id: ADMINISTRATIE_ID,
  bestandsnaam: '20260064 Universal Steigerbouw week 27.pdf',
  status: 'te_controleren',
  bron: 'upload',
  mogelijk_duplicaat_van: null,
  toegewezen_aan: null,
  aangemaakt_op: '2026-07-10T14:03:00Z',
  laatst_gewijzigd_op: '2026-07-10T14:04:00Z',
  veldvoorstel: AI_VOORSTEL,
  tijdlijn: [
    { van_status: null, naar_status: 'extractie_bezig', actor_id: 'x', actor_is_systeem: false, detail: null, tijdstip: '2026-07-10T14:03:00Z' },
    { van_status: 'extractie_bezig', naar_status: 'te_controleren', actor_id: 'x', actor_is_systeem: true, detail: { veldvoorstel: AI_VOORSTEL }, tijdstip: '2026-07-10T14:04:00Z' },
  ],
}

// Varianten via querystring: ?splitsen=1 start in de gesplitste weergave, ?project=1 zet de
// projectplicht aan (extra kolom, samenvoegen uitgesloten) — zo zijn alle tabelvarianten
// zonder interactie te screenshotten.
const PARAMS = new URLSearchParams(window.location.search)
const START_GESPLITST = PARAMS.has('splitsen')
const PROJECT_VERPLICHT = PARAMS.has('project')

const BOEKVOORSTEL = {
  document_id: DOCUMENT_ID,
  vendor_id: null,
  referentie: '202600645-2026-0917',
  factuurdatum: '2026-07-08',
  totaalbedrag: '2224.29',
  rlz_boekstuknummer: null,
  opgeslagen: false,
  regels: REGELS.map((r) => ({
    ledger_id: null,
    taxrate_id: null,
    project_id: null,
    netto_bedrag: r.netto_bedrag,
    btw_bedrag: r.btw_bedrag,
    omschrijving: r.omschrijving,
  })),
  regels_samenvoegen: !START_GESPLITST && !PROJECT_VERPLICHT,
  samenvoegen_toegestaan: !PROJECT_VERPLICHT,
  samengevoegde_regel: PROJECT_VERPLICHT
    ? null
    : {
        ledger_id: null,
        taxrate_id: null,
        project_id: null,
        netto_bedrag: '1838.25',
        btw_bedrag: '386.04',
        omschrijving: 'Factuur 202600645-2026-0917 — samengevoegd (3 regels)',
      },
}

const VENDORS = [
  { id: 'eeeeeeee-0000-0000-0000-000000000001', naam: 'Universal Steigerbouw B.V.' },
  { id: 'eeeeeeee-0000-0000-0000-000000000002', naam: 'Universal Steigerverhuur Holding' },
  { id: 'eeeeeeee-0000-0000-0000-000000000003', naam: 'Technische Unie' },
]

const GROOTBOEK = [
  { ledger_id: 'cccccccc-0000-0000-0000-000000000001', code: '4699', naam: 'Diverse kosten', soort: 2 },
  { ledger_id: 'cccccccc-0000-0000-0000-000000000002', code: '7000', naam: 'Inkoop onderaanneming', soort: 2 },
]

const TAXRATES = [
  { id: 'dddddddd-0000-0000-0000-000000000001', naam: 'NL Hoog 21% (inkoop)', percentage: '0.2100' },
  { id: 'dddddddd-0000-0000-0000-000000000002', naam: 'NL, BTW verlegd (inkoop)', percentage: '0.0000' },
]

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

const echteFetch = window.fetch.bind(window)
window.fetch = (invoer: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = String(invoer)
  if (url.endsWith('/bestand')) {
    return Promise.resolve(new Response(MINI_PDF, { status: 200, headers: { 'Content-Type': 'application/pdf' } }))
  }
  if (url.endsWith(`/documenten/${DOCUMENT_ID}`)) return Promise.resolve(jsonResponse(DETAIL))
  if (url.endsWith('/boekvoorstel') && (!init || !init.method)) return Promise.resolve(jsonResponse(BOEKVOORSTEL))
  if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: GROOTBOEK }))
  if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: TAXRATES }))
  if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: VENDORS }))
  if (url.endsWith('/projecten')) {
    return Promise.resolve(
      jsonResponse({
        projecten: PROJECT_VERPLICHT ? [{ id: 'ffffffff-0000-0000-0000-000000000001', naam: '26014 Amersfoort' }] : [],
      }),
    )
  }
  if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: PROJECT_VERPLICHT }))
  return echteFetch(invoer, init)
}

/** Rode/groene badge linksonder: is de pagina breder dan de viewport (horizontale clipping)? */
function OverflowBadge() {
  const [meting, setMeting] = useState('')
  const [overflow, setOverflow] = useState(false)
  useEffect(() => {
    const meet = () => {
      const scrollBreedte = document.documentElement.scrollWidth
      const viewport = window.innerWidth
      setOverflow(scrollBreedte > viewport)
      setMeting(`scrollWidth ${scrollBreedte} / viewport ${viewport}`)
    }
    meet()
    const timer = setInterval(meet, 500)
    window.addEventListener('resize', meet)
    return () => {
      clearInterval(timer)
      window.removeEventListener('resize', meet)
    }
  }, [])
  return (
    <div
      style={{
        position: 'fixed',
        left: 8,
        bottom: 8,
        zIndex: 999,
        padding: '4px 10px',
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 700,
        color: '#fff',
        background: overflow ? '#b42318' : '#1c7a54',
      }}
    >
      {overflow ? 'OVERFLOW' : 'past'} — {meting}
    </div>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MemoryRouter initialEntries={[`/documenten/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`]}>
      <div className="app">
        <div className="sidebar">
          <div className="logo">
            RLZ <span style={{ opacity: 0.6, fontWeight: 400 }}>Boekingsmodule</span>
          </div>
          <div className="sub">Administratiekantoor Nijenhuis</div>
          <div className="nav">
            <a className="active">Werkvoorraad</a>
          </div>
        </div>
        <div className="main">
          <Routes>
            <Route path="/documenten/:administratieId/:documentId" element={<DocumentDetailScreen />} />
          </Routes>
        </div>
      </div>
      <OverflowBadge />
    </MemoryRouter>
  </StrictMode>,
)
