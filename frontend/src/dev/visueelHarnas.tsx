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
  mogelijk_duplicaat_van: null as null | { document_id: string; bestandsnaam: string; aangemaakt_op: string },
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
// projectplicht aan (extra kolom, samenvoegen uitgesloten), ?geheugen=1 koppelt de crediteur
// vooraf zodat de geheugen-chips (incl. seed-only-oranje hint) meerenderen — zo zijn alle
// tabelvarianten zonder interactie te screenshotten.
const PARAMS = new URLSearchParams(window.location.search)
const START_GESPLITST = PARAMS.has('splitsen')
const PROJECT_VERPLICHT = PARAMS.has('project')
const MET_GEHEUGEN = PARAMS.has('geheugen')
// ?vraag=1: status vraag_open met een lange vraagtekst (open-vraag-banner + geblokkeerde
// actiebalk); ?checks=1: klikt na het laden automatisch op "Controleren" zodat het checks-
// rapport (incl. lange blokkerende meldingen zoals de IBAN-wissel) meerendert; ?duplicaat=1:
// duplicaatverdenking met lange bestandsnaam in de tijdlijn-banner.
const MET_VRAAG = PARAMS.has('vraag')
const MET_CHECKS = PARAMS.has('checks')
const MET_DUPLICAAT = PARAMS.has('duplicaat')

const BOEKVOORSTEL = {
  document_id: DOCUMENT_ID,
  vendor_id: MET_GEHEUGEN ? 'eeeeeeee-0000-0000-0000-000000000001' : null,
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

// Geheugenvoorstel (UI-koppeling 2026-07-14) — de seed-only-oranje variant met hint-tekst, zodat
// de breedste chip-stand ("uit historie, nog niet bevestigd") meetelt in de layout-verificatie.
const GEHEUGEN_VOORSTEL = {
  gb: {
    waarde: 'cccccccc-0000-0000-0000-000000000002',
    telling: 7,
    confidence: 0.92,
    oranje: true,
    reden: 'alleen rlz-historie, nog geen app-bevestiging',
    app_bevestigd: false,
  },
  btw: {
    waarde: 'dddddddd-0000-0000-0000-000000000002',
    telling: 5,
    confidence: 0.88,
    oranje: true,
    reden: 'leverancier-fallback',
    app_bevestigd: false,
  },
  project: { waarde: null, telling: 0, confidence: 0, oranje: false, reden: null, app_bevestigd: false },
}

// Vragenworkflow (PART B 2026-07-14): zonder ?vraag=1 geen open vraag — het controlescherm
// toont dan de normale actiebalk met "Vraag stellen…" naast de boekknop.
const MEDEWERKERS = [
  { id: '11111111-0000-0000-0000-000000000001', naam: 'Peter Nijenhuis' },
  { id: '11111111-0000-0000-0000-000000000002', naam: 'Medewerker Boekhouding' },
]

const OPEN_VRAAG = {
  id: '22222222-0000-0000-0000-000000000001',
  document_id: DOCUMENT_ID,
  vraag_tekst:
    'Op de factuur staat een G-rekeningsplitsing van 35% terwijl het contract met Universal 25% voorschrijft — is hier een aangepaste WKA-afspraak voor dit werk, of moet de factuur terug naar de leverancier?',
  status: 'open',
  gesteld_door: '11111111-0000-0000-0000-000000000001',
  gesteld_op: '2026-07-10T15:00:00Z',
  toegewezen_aan: '11111111-0000-0000-0000-000000000002',
  antwoord_tekst: null,
  beantwoord_op: null,
}

if (MET_VRAAG) DETAIL.status = 'vraag_open'
if (MET_DUPLICAAT) {
  DETAIL.mogelijk_duplicaat_van = {
    document_id: 'bbbbbbbb-0000-0000-0000-000000000003',
    bestandsnaam: '20260064 Universal Steigerbouw week 27 herzonden kopie administratie.pdf',
    aangemaakt_op: '2026-07-09T09:00:00Z',
  }
}

// Checks-rapport met de langste realistische meldingen (IBAN-wissel + duplicaat) — het
// clipping-gevoeligste geval voor de rechterkolom.
const CHECK_RAPPORT = {
  geblokkeerd: true,
  resultaten: [
    { naam: 'Duplicaat', ok: false, melding: 'Er bestaat al een document met dezelfde crediteur, referentie 202600645-2026-0917 en totaalbedrag € 2.224,29 (geboekt op 2026-07-03, boekstuk 20260112) — controleer of dit een heraanlevering is.' },
    { naam: 'Regeltelling', ok: true, melding: 'Aantal boekingsregels sluit aan op het gelezen document (3 regels).' },
    { naam: 'Verplichte velden', ok: true, melding: 'Crediteur, referentie, factuurdatum en totaalbedrag zijn ingevuld.' },
    { naam: 'IBAN-wissel', ok: false, melding: 'Het IBAN op deze factuur (NL91ABNA0417164300) wijkt af van het laatst bevestigde IBAN van deze crediteur (NL02RABO0123456789, bevestigd 2026-06-12) — bevestig de wijziging expliciet voordat er geboekt kan worden.' },
    { naam: 'Vraag blokkeert boeken', ok: true, melding: 'Geen open vraag op dit document.' },
  ],
}

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
  if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') {
    return Promise.resolve(jsonResponse({ boekvoorstel: BOEKVOORSTEL, checks: CHECK_RAPPORT }))
  }
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
  if (url.endsWith('/boekingsgeheugen/voorstel')) return Promise.resolve(jsonResponse(GEHEUGEN_VOORSTEL))
  if (url.includes('/vragen')) return Promise.resolve(jsonResponse({ vragen: MET_VRAAG ? [OPEN_VRAAG] : [] }))
  if (url.endsWith('/medewerkers')) return Promise.resolve(jsonResponse({ medewerkers: MEDEWERKERS }))
  return echteFetch(invoer, init)
}

/** Proef voor de combobox-flip + scroll-sprong (?focusgb=1): zet het eerste GB-veld in de
 * regeltabel vlak boven de onderrand van de viewport en focust het dan programmatic — de lijst
 * hoort naar bóven open te klappen (flip) en de pagina hoort niet te springen. De badge
 * rechtsonder toont de gemeten scrollY vóór/na. */
function FocusGbProef() {
  const [meting, setMeting] = useState<string | null>(null)
  useEffect(() => {
    if (!PARAMS.has('focusgb')) return
    const timer = setInterval(() => {
      const veld = document.querySelector<HTMLInputElement>('.boekingsregels-tabel input[role="combobox"]')
      if (!veld) return
      clearInterval(timer)
      const rect = veld.getBoundingClientRect()
      window.scrollTo(0, window.scrollY + rect.bottom - window.innerHeight + 60)
      setTimeout(() => {
        const voor = Math.round(window.scrollY)
        veld.focus()
        setTimeout(() => {
          const na = Math.round(window.scrollY)
          // Echte gerenderde breedte (layout, geen jsdom): de listbox hoort dankzij het
          // breedte-anker duidelijk breder te zijn dan het smalle tabelveld.
          const lijst = document.querySelector<HTMLElement>('.combobox-listbox')
          const veldBreedte = Math.round(veld.getBoundingClientRect().width)
          const lijstBreedte = lijst ? Math.round(lijst.getBoundingClientRect().width) : 0
          setMeting(
            `scrollY ${voor} → ${na}${voor === na ? ' (geen sprong)' : ' — SPRONG!'} · ` +
              `veld ${veldBreedte}px, lijst ${lijstBreedte}px${lijstBreedte > veldBreedte + 40 ? ' (verbreed)' : ' — NIET VERBREED!'}`,
          )
        }, 400)
      }, 100)
    }, 100)
    return () => clearInterval(timer)
  }, [])
  if (!meting) return null
  return (
    <div
      style={{
        position: 'fixed',
        right: 8,
        bottom: 8,
        zIndex: 999,
        padding: '4px 10px',
        borderRadius: 6,
        fontSize: 12,
        fontWeight: 700,
        color: '#fff',
        background: meting.includes('SPRONG') ? '#b42318' : '#1c7a54',
      }}
    >
      {meting}
    </div>
  )
}

/** ?checks=1: klikt na het laden op "Controleren" zodat het checks-rapport meerendert —
 * headless Chrome kan zelf niet klikken, dus het harnas doet het (zelfde patroon als
 * FocusGbProef). */
function AutoChecksProef() {
  useEffect(() => {
    if (!MET_CHECKS) return
    const timer = setInterval(() => {
      const knoppen = Array.from(document.querySelectorAll<HTMLButtonElement>('button.btn'))
      const knop = knoppen.find((b) => b.textContent?.trim() === 'Controleren')
      if (!knop) return
      clearInterval(timer)
      knop.click()
    }, 100)
    return () => clearInterval(timer)
  }, [])
  return null
}

/** Korte, leesbare beschrijving van een element voor de boosdoener-lijst. */
function beschrijfElement(el: Element): string {
  const tag = el.tagName.toLowerCase()
  const klassen = typeof el.className === 'string' && el.className ? `.${el.className.trim().split(/\s+/).join('.')}` : ''
  const rect = el.getBoundingClientRect()
  return `${tag}${klassen} [${Math.round(rect.left)}..${Math.round(rect.right)}]`
}

/** Rode/groene badge linksonder: is de pagina breder dan de viewport (horizontale clipping)?
 * Bij overflow somt de badge de diepste boosdoeners op — elementen die rechts buiten de viewport
 * steken zónder kinderen die dat ook doen (de bladeren van de overflow-boom), zodat headless
 * Chrome (--dump-dom) de oorzaak direct benoemt in plaats van alleen "OVERFLOW". */
function OverflowBadge() {
  const [meting, setMeting] = useState('')
  const [overflow, setOverflow] = useState(false)
  const [boosdoeners, setBoosdoeners] = useState<string[]>([])
  useEffect(() => {
    const meet = () => {
      const scrollBreedte = document.documentElement.scrollWidth
      const viewport = window.innerWidth
      setOverflow(scrollBreedte > viewport)
      setMeting(`scrollWidth ${scrollBreedte} / viewport ${viewport}`)
      if (scrollBreedte <= viewport) {
        setBoosdoeners([])
        return
      }
      const uitstekend = Array.from(document.querySelectorAll('body *')).filter((el) => {
        if (el.closest('[data-harnas-badge]')) return false
        return el.getBoundingClientRect().right > viewport + 1
      })
      const bladeren = uitstekend.filter((el) => !uitstekend.some((ander) => ander !== el && el.contains(ander)))
      setBoosdoeners(bladeren.slice(0, 8).map(beschrijfElement))
    }
    // ?rapporteer=<poort>: post de meting naar een lokaal meetscript — voor browsers waar we
    // niet in kunnen kijken (Safari zonder 'Allow JavaScript from Apple Events').
    const rapporteerPoort = PARAMS.get('rapporteer')
    const rapporteer = () => {
      if (!rapporteerPoort) return
      const viewport = window.innerWidth
      const uitstekend = Array.from(document.querySelectorAll('body *')).filter((el) => {
        if (el.closest('[data-harnas-badge]')) return false
        const r = el.getBoundingClientRect()
        return r.right > viewport + 1 && r.width > 0
      })
      const bladeren = uitstekend.filter((el) => !uitstekend.some((a) => a !== el && el.contains(a)))
      void echteFetch(`http://localhost:${rapporteerPoort}/meting`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ua: navigator.userAgent.slice(0, 80),
          viewport,
          scrollBreedte: document.documentElement.scrollWidth,
          boosdoeners: bladeren.slice(0, 10).map(beschrijfElement),
        }),
      }).catch(() => undefined)
    }
    const rapporteerTimer = setInterval(rapporteer, 1500)
    meet()
    const timer = setInterval(meet, 500)
    window.addEventListener('resize', meet)
    return () => {
      clearInterval(timer)
      clearInterval(rapporteerTimer)
      window.removeEventListener('resize', meet)
    }
  }, [])
  return (
    <div
      data-harnas-badge
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
        maxWidth: '90vw',
      }}
    >
      {overflow ? 'OVERFLOW' : 'past'} — {meting}
      {boosdoeners.map((b) => (
        <div key={b} style={{ fontWeight: 400, fontSize: 11 }}>
          → {b}
        </div>
      ))}
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
      <FocusGbProef />
      <AutoChecksProef />
    </MemoryRouter>
  </StrictMode>,
)
