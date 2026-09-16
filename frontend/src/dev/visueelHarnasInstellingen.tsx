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
    // v3 (01-09): álle tabs zichtbaar op de detailpagina (sweep-geval ?pad=/instellingen/administraties/<id>).
    uren_meerwerk_ingeschakeld: true,
    uren_dagmax_uren: '12',
    voorraad_ingeschakeld: true,
    mini_voorraad_ingeschakeld: true,
    afdelingen_ingeschakeld: true,
    accordering_ingeschakeld: true,
    doorbelasting_ingeschakeld: true,
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
  // Blok A 16-09: intercompany-relaties + RC-koppelingen op Boeken platformbreed (sweep-geval ?pad=/instellingen/boeken).
  if (url === '/intercompany/relaties') {
    const rel = (id: string, a: string, aId: string, naam: string, b: string, bId: string, richting: 'crediteur' | 'debiteur', basis: string, status: string, reden: string | null = null) => ({
      id, administratie_a_id: aId, administratie_a_naam: a, entity_in_a: `e-${id}`, entity_naam: naam, administratie_b_id: bId, administratie_b_naam: b,
      richting, basis, status, bron: status === 'afgeleid' ? 'afgeleid' : 'mens', reden, gewijzigd_op: null, actief: status === 'bevestigd' || (status === 'afgeleid' && basis !== 'naam'),
    })
    return Promise.resolve(
      jsonResponse({
        relaties: [
          rel('r1', 'Universal Steigerbouw Nederland B.V.', ADMIN_1, 'Universal Verkoop B.V.', 'Universal Verkoop B.V.', ADMIN_2, 'crediteur', 'kvk', 'afgeleid'),
          rel('r2', 'Universal Verkoop B.V.', ADMIN_2, 'Universal Steigerbouw Nederland', 'Universal Steigerbouw Nederland B.V.', ADMIN_1, 'debiteur', 'doorbelasting', 'bevestigd'),
          rel('r3', 'BLOW B.V.', ADMIN_3, 'Molenhof Verhuur', 'Molenhof Verhuur B.V.', ADMIN_2, 'crediteur', 'naam', 'afgeleid'),
          rel('r4', 'Molenhof Verhuur B.V.', ADMIN_2, 'Blow Coffeeshop (extern)', 'BLOW B.V.', ADMIN_3, 'debiteur', 'naam', 'uitgesloten', 'Externe klant met toevallig dezelfde naam — geen groepsmaatschappij.'),
        ],
      }),
    )
  }
  if (url === '/intercompany/rc-koppelingen') {
    return Promise.resolve(
      jsonResponse({
        koppelingen: [
          { id: 'k1', administratie_a_id: ADMIN_1, administratie_a_naam: 'Universal Steigerbouw Nederland B.V.', rekening_a: 'l1', rekening_a_code: '1400', rekening_a_naam: 'RC Universal Verkoop B.V.', administratie_b_id: ADMIN_2, administratie_b_naam: 'Universal Verkoop B.V.', rekening_b: 'l2', rekening_b_code: '1600', rekening_b_naam: 'Rekening-courant Universal Steigerbouw Nederland', basis: 'naam', status: 'afgeleid', bron: 'afgeleid', reden: null, gewijzigd_op: null, actief: true },
          { id: 'k2', administratie_a_id: ADMIN_2, administratie_a_naam: 'Universal Verkoop B.V.', rekening_a: 'l2', rekening_a_code: '1600', rekening_a_naam: 'Rekening-courant Universal Steigerbouw Nederland', administratie_b_id: ADMIN_1, administratie_b_naam: 'Universal Steigerbouw Nederland B.V.', rekening_b: 'l1', rekening_b_code: '1400', rekening_b_naam: 'RC Universal Verkoop B.V.', basis: 'naam', status: 'bevestigd', bron: 'mens', reden: null, gewijzigd_op: '2026-09-16T09:00:00Z', actief: true },
          { id: 'k3', administratie_a_id: ADMIN_3, administratie_a_naam: 'BLOW B.V.', rekening_a: 'l3', rekening_a_code: '1410', rekening_a_naam: 'RC MV', administratie_b_id: ADMIN_2, administratie_b_naam: 'Molenhof Verhuur B.V.', rekening_b: null, rekening_b_code: null, rekening_b_naam: null, basis: 'afkorting', status: 'afgeleid', bron: 'afgeleid', reden: null, gewijzigd_op: null, actief: true },
        ],
        identiteiten: [
          { administratie_id: ADMIN_1, administratie_naam: 'Universal Steigerbouw Nederland B.V.', naam: 'Universal Steigerbouw Nederland B.V.', kvk: '12345678', btw: null, bron: 'rlz', afkortingen: ['USN'], gelezen_op: '2026-09-16T05:00:00Z' },
          { administratie_id: ADMIN_2, administratie_naam: 'Molenhof Verhuur B.V.', naam: 'Molenhof Verhuur B.V.', kvk: '87654321', btw: 'NL001234567B01', bron: 'odoo', afkortingen: ['MV'], gelezen_op: '2026-09-16T05:00:00Z' },
          { administratie_id: ADMIN_3, administratie_naam: 'BLOW B.V.', naam: null, kvk: null, btw: null, bron: 'rlz', afkortingen: [], gelezen_op: null },
        ],
      }),
    )
  }
  // 0151 (16-09 avond): blok "Stores" op Boeken platformbreed — store → administratie (sweep-geval ?pad=/instellingen/boeken).
  if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: ADMINISTRATIES }))
  if (url === '/instellingen/omzet/stores') {
    return Promise.resolve(
      jsonResponse({
        doel_pad: '/instellingen/boeken#stores',
        stores: [
          { id: 's1', store_naam: 'Elderveld', store_norm: 'elderveld', administratie_id: ADMIN_3, administratie_naam: 'BLOW B.V.', actief: true, bron: 'migratie', gewijzigd_op: null },
          { id: 's2', store_naam: 'Sunshine Island', store_norm: 'sunshine island', administratie_id: ADMIN_2, administratie_naam: 'Molenhof Verhuur B.V.', actief: true, bron: 'mens', gewijzigd_op: '2026-09-16T20:00:00Z' },
          { id: 's3', store_naam: 'Oude store', store_norm: 'oude store', administratie_id: ADMIN_1, administratie_naam: 'Universal Steigerbouw Nederland B.V.', actief: false, bron: 'mens', gewijzigd_op: null },
        ],
      }),
    )
  }
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
  // Omzetbronnen (besluiten Peter 16-09 blok B): GET/PUT bron-instellingen mét defaults + keuzelijsten (CONTRACT_4).
  // `?omzetbronnen=1` = de breedste stand (twee stores, eigen regels, lange rekeningnamen) voor de overflow-sweep.
  if (url.endsWith('/omzet/bron-instellingen')) {
    const breed = new URLSearchParams(window.location.search).has('omzetbronnen')
    const rekeningen = [
      { ledger_id: 'gb-1010', code: '1010', naam: 'Kas' },
      { ledger_id: 'gb-1020', code: '1020', naam: 'Kruisposten / PIN onderweg (nog niet op de bank ontvangen)' },
      { ledger_id: 'gb-1025', code: '1025', naam: 'Stripe / PSP onderweg' },
      { ledger_id: 'gb-1030', code: '1030', naam: 'Storting automaat onderweg' },
      { ledger_id: 'gb-4890', code: '4890', naam: 'Kasverschillen' },
      { ledger_id: 'gb-4850', code: '4850', naam: 'Transactiekosten PSP' },
    ]
    const tarieven = [
      { taxrate_id: 'btw-laag', naam: 'NL, Laag Tarief', percentage: '0.0900' },
      { taxrate_id: 'btw-hoog', naam: 'NL, Hoog Tarief', percentage: '0.2100' },
      { taxrate_id: 'btw-verlegd', naam: 'EU, Diensten verlegd', percentage: '0' },
    ]
    const defaults = {
      tegenrekeningen: { pin: 'gb-1020', cash: 'gb-1010', stripe: 'gb-1025', kasverschil: 'gb-4890', storting: 'gb-1030' },
      // X-vorm (service.defaults_voor): per categorie-SLEUTEL {klasse, taxrate_id}; psp/eten zitten niet in defaults maar
      // komen gemerged in de hoofdwaarden terug.
      categorie_btw: {
        pilateslessen: { klasse: 'laag', taxrate_id: 'btw-laag' },
        yoga: { klasse: 'laag', taxrate_id: 'btw-laag' },
        'kleding producten': { klasse: 'hoog', taxrate_id: 'btw-hoog' },
        'eten drinken': { klasse: 'laag', taxrate_id: 'btw-laag' },
        'transactiekosten psp': { klasse: 'verlegd', taxrate_id: 'btw-verlegd' },
        points: { klasse: 'hoog', taxrate_id: 'btw-hoog' },
        tanning: { klasse: 'hoog', taxrate_id: 'btw-hoog' },
      },
      btw_per_klasse: { laag: 'btw-laag', hoog: 'btw-hoog', verlegd: 'btw-verlegd' },
      verlegd_herkomst: 'meest gebruikt in RLZ-historie (12×)',
      product_categorieen: { 'onbeperkt abonnement': 'Pilateslessen', '10 rittenkaart': 'Pilateslessen', 'yoga 10 rittenkaart': 'Yoga', 'losse les yoga': 'Yoga' },
      psp_kosten_ledger_id: 'gb-4850',
      psp_btw_herkomst: 'Stripe · EU-dienst verlegd',
    }
    if (init?.method === 'PUT') {
      const body = JSON.parse(String(init.body ?? '{}')) as Record<string, unknown>
      return Promise.resolve(jsonResponse({ ...body, defaults, rekeningen, tarieven }))
    }
    return Promise.resolve(
      jsonResponse({
        stores: breed ? ['Elderveld', 'Sunshine Island'] : [],
        product_categorieen: breed ? { 'grip sokken (antislip) maat 39-42': 'Kleding & producten' } : {},
        tegenrekeningen: { pin: breed ? 'gb-1020' : null, cash: null, stripe: null, kasverschil: null, storting: null },
        categorie_btw: breed ? { 'eten drinken': 'btw-hoog' } : {},
        combi_regel: 'pro_rato_batch',
        psp: 'stripe',
        psp_kosten_ledger_id: null,
        eten_drinken_tarief: 'laag',
        defaults,
        rekeningen,
        tarieven,
      }),
    )
  }
  // Blok B (01-09): autoboek-kandidaten (nav-item Autoboeken) — tellers + drie kandidaten mét chips.
  const tellers = { kandidaten: 31, actief: 12, heroverwegen: 2, verborgen: 1, administraties_met_kandidaten: 14, drempel: 5, laatste_run_op: '2026-09-01T06:00:00Z' }
  if (url === '/instellingen/autoboeken/stand') return Promise.resolve(jsonResponse(tellers))
  if (url.startsWith('/instellingen/autoboeken/kandidaten')) {
    const heroverwegen = url.includes('tab=heroverwegen')
    const rij = (naam: string, adm: string, admId: string, reeks: number, extra: string[], bedrag: string, signalen: string[] = []) => ({
      administratie_id: admId,
      administratie_naam: adm,
      vendor_id: `v-${naam}`,
      leverancier_naam: naam,
      reeks_ongewijzigd: reeks,
      correcties: 0,
      open_vragen: 0,
      kwalificeert: !heroverwegen,
      actief: heroverwegen,
      actief_sinds: heroverwegen ? '2026-08-12T09:00:00Z' : null,
      redenen: [],
      chips: [`${reeks} identieke boekingen`, 'geheugen bevestigd', '0 vragen / 0 correcties', ...extra],
      heroverweeg_signalen: signalen,
      laatste_factuur_datum: '2026-08-25',
      laatste_factuur_bedrag: bedrag,
      laatste_document_id: null,
      snooze_reden: null,
      snooze_op: null,
      berekend_op: '2026-09-01T06:00:00Z',
    })
    const rijen = heroverwegen
      ? [
          rij('Bouwmaat Eindhoven — Steigerbouwmaterialen B.V.', 'Universal Steigerbouw Nederland B.V.', ADMIN_1, 0, [], '1.240,00', ['2 correcties ná activatie', 'GB-code gewijzigd door mens (28 Aug)']),
          rij('Labo Derva', 'Molenhof Verhuur B.V.', ADMIN_2, 0, [], '388,90', ['btw-tarief gewijzigd door mens (01 Sep)', 'buitenland-signaal']),
        ]
      : [
          rij('Ebbers Salarisadvies B.V.', 'Administratiekantoor Nijenhuis C.V.', ADMIN_3, 12, ['vast maandbedrag'], '2721.83'),
          rij('Transip B.V.', 'Administratiekantoor Nijenhuis C.V.', ADMIN_3, 9, [], '12.09'),
          rij('Kadaster', 'Universal Steigerbouw Nederland B.V.', ADMIN_1, 6, ['bedrag wisselt'], '175.34'),
        ]
    return Promise.resolve(jsonResponse({ rijen, totaal: rijen.length, pagina: 1, per_pagina: 25, tellers }))
  }
  // v3-detailpagina: tab "Boeken & AI" (leverancier-autoboeken + afdelingen).
  if (url.endsWith('/leveranciers-autoboeken')) {
    return Promise.resolve(
      jsonResponse({
        leveranciers: [
          { vendor_id: 'v-1', naam: 'Ebbers Salarisadvies B.V.', autoboeken_ingeschakeld: true },
          { vendor_id: 'v-2', naam: 'Bouwmaat Eindhoven — Steigerbouwmaterialen en Toebehoren B.V.', autoboeken_ingeschakeld: false },
        ],
      }),
    )
  }
  if (url.endsWith('/afdelingen')) {
    return Promise.resolve(
      jsonResponse({
        ingeschakeld: true,
        afdelingen: [{ id: 'alg', naam: 'Algemeen', is_terugval: true, actief: true, route: [], staande_goedkeuringen: 0, gearchiveerd_op: null }],
      }),
    )
  }
  return echteFetch(invoer, init)
}

if (new URLSearchParams(window.location.search).has('donker')) {
  document.documentElement.classList.add('dark')
  document.body.classList.add('dark')
}

// Startroute overschrijfbaar (?pad=/instellingen/administraties, optioneel &tab=boeken-ai voor de
// detailpagina) — zo kan de overflow-sweep óók de subpagina's meten zonder klik-automatisering.
const params = new URLSearchParams(window.location.search)
const startTab = params.get('tab')
const startPad = (params.get('pad') ?? '/instellingen') + (startTab ? `?tab=${startTab}` : '')

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
                  <Route path="/instellingen/administraties/:administratieId" element={<InstellingenScreen />} />
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
