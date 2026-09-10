// Visueel harnas Gebruikers & toegang (fase 3 modernisering 15-08): het echte scherm met
// gemockte fetch, voor headless verificatie zonder backend/login.
//   npx vite --port 5199  →  http://localhost:5199/harness-gebruikers.html [?donker=1]
// Varianten (blok 2 vervolgrun 10-09 avond, kliktest Peter — tabel-layout met kolomminima):
//   ?breed=1              brede variant: langste namen/e-mails, account mét "Opnieuw mailen", álle
//                         beveiligings-/statuschips aan, geblokkeerd mét detail, Rechten-switches aan
//   ?groep=veldwerkers    de Veldwerkers-tab (mock /uren/beheer/veldgebruikers)
//   ?groep=accordeurs     de Klant-accordeurs-tab (toestel + oude passkey + half geactiveerd)
//   ?scope=71             blok 2 nachtrun 10/11-09: de scope-dialoog "Scope van Demi de Vries" open bóven het scherm
//                         met 71 administraties (4 gearchiveerd in scope, lange namen) — ScopeLijst i.p.v. chips-wolk;
//                         &variant=accordeur = de accordeur-variant "Administraties toevoegen…" (R. de Groot) in
//                         de toevoeg-stand. Probe body[data-scope-dialoog] = "rijen=N;scrollx=…;lijstScrollx=…" en,
//                         als de dialooginhoud intern horizontaal overloopt, de tekst "OVERFLOW — scope-dialoog …" in
//                         de body (de OverflowBadge meet alleen de pagina; een Radix-overlay scrolt zelf).
//   ?meet=1               meetstand: table-layout auto + nowrap op alle cellen — op een zeer breed venster
//                         (bv. --window-size=4000,1600) toont body[data-gebruikers-kolombreedtes] de
//                         natuurlijke max-content-breedte per kolom (bron voor de minima in
//                         gebruikers/gebruikersKolommen.ts). Alleen dev, nooit productie.
// Probes op <body> (uit te lezen met --dump-dom, patroon C9 verzamelbak-rijhoogtes):
//   data-gebruikers-kolombreedtes   "kop=offsetWidth;…" per tabel
//   data-gebruikers-chipregels      max offsetHeight van .chips-regel per tabel (één regel ≈ ≤ 24 px)
//   data-gebruikers-tabelscroll     scrollWidth − clientWidth van .tabel-scroll (0 = geen interne scroll)
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { AccordeurAdministraties } from '../gebruikers/AccordeurAdministraties'
import { GebruikersScreen } from '../gebruikers/GebruikersScreen'
import { ScopeModal } from '../gebruikers/ScopeModal'
import { SCOPELIJST_RIJHOOGTE_PX } from '../gebruikers/ScopeLijst'
import { ToastProvider } from '../ui/basis'
import { OverflowBadge } from './overflowBadge'
import '../index.css'

const EIGEN_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const ADMIN_1 = 'dddddddd-0000-0000-0000-00000000000d'
const ADMIN_2 = 'eeeeeeee-0000-0000-0000-00000000000e'
const ADMIN_3 = 'ffffffff-0000-0000-0000-0000000000f0'

const params = new URLSearchParams(window.location.search)
const BREED = params.has('breed')
const MEET = params.has('meet')
const GROEP = params.get('groep')
const SCOPE = params.has('scope') ? Math.max(1, Number(params.get('scope')) || 71) : 0
const SCOPE_VARIANT = params.get('variant')

function fakeAccessToken(): string {
  const payload = btoa(JSON.stringify({ sub: EIGEN_ID, rol: 'beheerder' }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

const over = (uren: number) => new Date(Date.now() + uren * 3600e3).toISOString()

const BASIS = {
  half_geactiveerd: false,
  open_herstel_verloopt_op: null,
  geblokkeerd_op: null,
  geblokkeerd_door_naam: null,
}

const GEBRUIKERS = [
  {
    ...BASIS,
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
    ...BASIS,
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
    ...BASIS,
    id: 'ffffffff-0000-0000-0000-00000000000f',
    naam: 'J. Jansen',
    e_mail: 'j.jansen@voorbeeld.nl',
    rol: 'boekhouding',
    status: 'uitgenodigd',
    administratie_ids: [ADMIN_1],
    heeft_totp: false,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: over(68),
    staande_goedkeuringen: 0,
  },
  {
    ...BASIS,
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

/** Brede variant: de langste realistische inhoud per kolom, alle chips tegelijk aan. */
const GEBRUIKERS_BREED = [
  ...GEBRUIKERS,
  {
    ...BASIS,
    id: '11111111-0000-0000-0000-000000000011',
    naam: 'Anne-Marie van der Westerlaken-Nieuwenhuizen',
    e_mail: 'anne-marie.vanderwesterlaken@administratiekantoor-nijenhuis.nl',
    rol: 'boekhouding_projecten',
    status: 'actief',
    administratie_ids: [ADMIN_1, ADMIN_2, ADMIN_3],
    heeft_totp: true,
    aantal_passkeys: 3,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
  },
  {
    ...BASIS,
    id: '22222222-0000-0000-0000-000000000022',
    naam: 'Bartholomeus Groenewegen',
    e_mail: 'b.groenewegen@ak-nijenhuis.nl',
    rol: 'boekhouding',
    status: 'actief',
    administratie_ids: [ADMIN_1],
    heeft_totp: false,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
  },
  {
    ...BASIS,
    id: '33333333-0000-0000-0000-000000000033',
    naam: 'Cornelia Schoonderbeek-Verhoeven',
    e_mail: 'c.schoonderbeek@ak-nijenhuis.nl',
    rol: 'boekhouding_projecten',
    status: 'geblokkeerd',
    geblokkeerd_op: '2026-09-01T09:00:00Z',
    geblokkeerd_door_naam: 'Peter Nijenhuis',
    administratie_ids: [ADMIN_1, ADMIN_2],
    heeft_totp: true,
    aantal_passkeys: 1,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
  },
  {
    ...BASIS,
    id: '44444444-0000-0000-0000-000000000044',
    naam: 'Dirk-Jan Oosterhuis',
    e_mail: 'dj.oosterhuis@ak-nijenhuis.nl',
    rol: 'boekhouding',
    status: 'wacht_op_totp',
    administratie_ids: [ADMIN_2],
    heeft_totp: false,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
  },
  {
    ...BASIS,
    id: '55555555-0000-0000-0000-000000000055',
    naam: 'Evert-Jan Kuipers-Boonstra',
    e_mail: 'ej.kuipers@ak-nijenhuis.nl',
    rol: 'boekhouding',
    status: 'uitgenodigd',
    administratie_ids: [ADMIN_1],
    heeft_totp: false,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: over(-3),
    staande_goedkeuringen: 0,
  },
  // Veldwerkers (tab Veldwerkers): ZZP'er mét dossier + correctie-⚠, detacheerder mét tarieven, uitvoerder half geactiveerd.
  {
    ...BASIS,
    id: '66666666-0000-0000-0000-000000000066',
    naam: 'Milan Kowalczyk-Nieuwenhuis',
    e_mail: 'milan.kowalczyk-nieuwenhuis@steigerbouw-montage.nl',
    rol: 'zzper',
    status: 'actief',
    administratie_ids: [ADMIN_3],
    heeft_totp: false,
    aantal_passkeys: 1,
    open_uitnodiging_verloopt_op: null,
    open_herstel_verloopt_op: over(70),
    staande_goedkeuringen: 0,
  },
  {
    ...BASIS,
    id: '77777777-0000-0000-0000-000000000077',
    naam: 'Karin Steenbergen-van Dijk',
    e_mail: 'k.steenbergen@detacheringsbureau-bouw.nl',
    rol: 'detacheerder',
    status: 'actief',
    administratie_ids: [ADMIN_3],
    heeft_totp: false,
    aantal_passkeys: 1,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
  },
  {
    ...BASIS,
    id: '88888888-0000-0000-0000-000000000088',
    naam: 'Stefan Bouwmeester',
    e_mail: 's.bouwmeester@universal-steigers.nl',
    rol: 'uitvoerder',
    status: 'actief',
    half_geactiveerd: true,
    administratie_ids: [ADMIN_3],
    heeft_totp: false,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
  },
  {
    ...BASIS,
    id: '99999999-0000-0000-0000-000000000099',
    naam: 'Thijs van den Heuvel',
    e_mail: 't.vandenheuvel@zzp-steigers.nl',
    rol: 'zzper',
    status: 'uitgenodigd',
    administratie_ids: [ADMIN_3],
    heeft_totp: false,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: over(40),
    staande_goedkeuringen: 0,
  },
  // Klant-accordeurs: half geactiveerd mét herstel-link, veel administraties, geblokkeerd, uitgenodigd.
  {
    ...BASIS,
    id: 'a1a1a1a1-0000-0000-0000-0000000000a1',
    naam: 'Hendrik-Jan van Zuijlekom-Brinkerhoff',
    e_mail: 'hendrik-jan.vanzuijlekom@vastgoedgroep-nederland-beheer.nl',
    rol: 'klant_accordeur',
    status: 'actief',
    half_geactiveerd: true,
    open_herstel_verloopt_op: over(71),
    administratie_ids: [ADMIN_1, ADMIN_2, ADMIN_3],
    heeft_totp: false,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 14,
  },
  {
    ...BASIS,
    id: 'a2a2a2a2-0000-0000-0000-0000000000a2',
    naam: 'Wilhelmina Oudenampsen',
    e_mail: 'w.oudenampsen@molenhof.nl',
    rol: 'klant_accordeur',
    status: 'geblokkeerd',
    geblokkeerd_op: '2026-08-30T09:00:00Z',
    geblokkeerd_door_naam: 'Peter Nijenhuis',
    administratie_ids: [ADMIN_2],
    heeft_totp: false,
    aantal_passkeys: 1,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
  },
  {
    ...BASIS,
    id: 'a3a3a3a3-0000-0000-0000-0000000000a3',
    naam: 'Nieuwe Accordeur',
    e_mail: 'nieuw@klant.nl',
    rol: 'klant_accordeur',
    status: 'uitgenodigd',
    administratie_ids: [ADMIN_1],
    heeft_totp: false,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: over(60),
    staande_goedkeuringen: 0,
  },
]

const ADMINISTRATIES_BASIS = [
  { id: ADMIN_1, naam: 'Molenhof Beheer B.V.' },
  { id: ADMIN_2, naam: 'Molenhof Verhuur B.V.' },
  { id: ADMIN_3, naam: 'Universal Steigerbouw B.V.', uren_meerwerk_ingeschakeld: true },
]

/** ?scope=N — N fictieve administraties (kantoorschaal, kliktest 10-09: 71), realistische namenmix incl. één zeer
 * lange naam; deterministisch (geen random) zodat de meting herhaalbaar is. */
const SCOPE_VOORNAMEN = ['Akkerman', 'Baard', 'Boxx', 'De Kempen', 'Derva', 'Floor', 'Groenewegen', 'Hoogland', 'IJsselsteijn', 'Jansen', 'Kempen Facilities', 'Labo', 'Molenhof', 'Nijenhuis', 'Oosterhuis', 'Poelman', 'Quist', 'Roerdink', 'Spot Services', 'Ter Braak', 'Universal', 'Vastly', 'Westerlaken', 'Zilver']
const SCOPE_ACHTER = ['Beheer B.V.', 'Holding B.V.', 'Vastgoed B.V.', 'Onroerend Goed B.V.', 'Exploitatie B.V.', 'V.O.F.', 'Pensioen B.V.']
function scopeAdministraties(n: number): { id: string; naam: string }[] {
  const uit: { id: string; naam: string }[] = []
  for (let i = 0; i < n; i++) {
    const id = `5c0be000-0000-4000-8000-${String(i + 1).padStart(12, '0')}`
    const naam =
      i === 7
        ? 'Administratiekantoor Nijenhuis Beheer- en Exploitatiemaatschappij Oost-Nederland B.V.'
        : `${SCOPE_VOORNAMEN[i % SCOPE_VOORNAMEN.length]} ${SCOPE_ACHTER[(i * 5) % SCOPE_ACHTER.length]}${i >= SCOPE_VOORNAMEN.length ? ` ${Math.floor(i / SCOPE_VOORNAMEN.length) + 1}` : ''}`
    uit.push({ id, naam })
  }
  return uit
}
const SCOPE_ACTIEF = SCOPE ? scopeAdministraties(SCOPE - Math.min(4, SCOPE - 1)) : []
const SCOPE_GEARCHIVEERD = SCOPE
  ? Array.from({ length: Math.min(4, SCOPE - 1) }, (_, i) => ({
      id: `5c0be000-0000-4000-8000-9${String(i + 1).padStart(11, '0')}`,
      naam: `Oud ${['Akkerman', 'Baard', 'Derva', 'Zilver'][i]} B.V.`,
      actief: false,
    }))
  : []
const ADMINISTRATIES = SCOPE ? SCOPE_ACTIEF : ADMINISTRATIES_BASIS
/** Demi in de scope-variant: elke derde actieve + alle gearchiveerde in scope. */
const SCOPE_DEMI_IDS = SCOPE
  ? [...SCOPE_ACTIEF.filter((_, i) => i % 3 === 0).map((a) => a.id), ...SCOPE_GEARCHIVEERD.map((a) => a.id)]
  : []
const SCOPE_DEMI = {
  ...GEBRUIKERS[1],
  administratie_ids: SCOPE_DEMI_IDS,
  administraties: [
    ...SCOPE_ACTIEF.filter((_, i) => i % 3 === 0).map((a) => ({ ...a, actief: true })),
    ...SCOPE_GEARCHIVEERD,
  ],
}
const SCOPE_ACCORDEUR = {
  ...GEBRUIKERS[3],
  administratie_ids: [...SCOPE_ACTIEF.slice(0, 5).map((a) => a.id), SCOPE_GEARCHIVEERD[0]?.id].filter(Boolean) as string[],
  administraties: [...SCOPE_ACTIEF.slice(0, 5).map((a) => ({ ...a, actief: true })), ...SCOPE_GEARCHIVEERD.slice(0, 1)],
}

/** Veldgebruikers-mock (VeldwerkersPanel haalt /uren/beheer/veldgebruikers): koppelingen mét tarieven,
 * dossier-samenvatting en de kantoor-only correctie-⚠. */
const VELDGEBRUIKERS = [
  {
    gebruiker_id: '66666666-0000-0000-0000-000000000066',
    naam: 'Milan Kowalczyk-Nieuwenhuis',
    e_mail: 'milan.kowalczyk-nieuwenhuis@steigerbouw-montage.nl',
    rol: 'zzper',
    status: 'actief',
    projecten: [
      { administratie_id: ADMIN_3, administratie_naam: 'Universal Steigerbouw B.V.', project_id: 'p1', project_naam: '26049 Hoofddorp (Dura Vermeer)', bron: 'planning' },
      { administratie_id: ADMIN_3, administratie_naam: 'Universal Steigerbouw B.V.', project_id: 'p2', project_naam: '26051 Amsterdam (BAM)', bron: 'weekstaat' },
    ],
    zzpers: [],
    crediteuren: [
      { administratie_id: ADMIN_3, administratie_naam: 'Universal Steigerbouw B.V.', vendor_id: 'v1', vendor_naam: 'Kowalczyk Montage & Steigerbouw', uurtarief: '42.50', autoboeken_ingeschakeld: true },
    ],
    uren_afwijking_aantal: 2,
    uren_afwijking_som: '3.5',
    dossiers: [
      { administratie_id: ADMIN_3, administratie_naam: 'Universal Steigerbouw B.V.', aantal_verplicht: 6, aantal_aanwezig: 4, aantal_ontbrekend: 2, aantal_verlopen: 0, aantal_verloopt_binnenkort: 1, aantal_ter_controle: 0, compleet: false, geblokkeerd: false },
    ],
  },
  {
    gebruiker_id: '77777777-0000-0000-0000-000000000077',
    naam: 'Karin Steenbergen-van Dijk',
    e_mail: 'k.steenbergen@detacheringsbureau-bouw.nl',
    rol: 'detacheerder',
    status: 'actief',
    projecten: [],
    zzpers: [
      { gebruiker_id: '66666666-0000-0000-0000-000000000066', naam: 'Milan Kowalczyk-Nieuwenhuis', uurtarief: '51.00' },
      { gebruiker_id: '99999999-0000-0000-0000-000000000099', naam: 'Thijs van den Heuvel', uurtarief: null },
    ],
    crediteuren: [
      { administratie_id: ADMIN_3, administratie_naam: 'Universal Steigerbouw B.V.', vendor_id: 'v2', vendor_naam: 'Detacheringsbureau Bouw & Techniek B.V.', uurtarief: null, autoboeken_ingeschakeld: false },
    ],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    dossiers: [],
  },
  {
    gebruiker_id: '88888888-0000-0000-0000-000000000088',
    naam: 'Stefan Bouwmeester',
    e_mail: 's.bouwmeester@universal-steigers.nl',
    rol: 'uitvoerder',
    status: 'actief',
    projecten: [
      { administratie_id: ADMIN_3, administratie_naam: 'Universal Steigerbouw B.V.', project_id: 'p1', project_naam: '26049 Hoofddorp (Dura Vermeer)', bron: 'planning' },
    ],
    zzpers: [],
    crediteuren: [],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    dossiers: [],
  },
  {
    gebruiker_id: '99999999-0000-0000-0000-000000000099',
    naam: 'Thijs van den Heuvel',
    e_mail: 't.vandenheuvel@zzp-steigers.nl',
    rol: 'zzper',
    status: 'uitgenodigd',
    projecten: [],
    zzpers: [],
    crediteuren: [],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    dossiers: [],
  },
]

const APPARATEN_STANDAARD = [
  {
    id: 'app-1',
    apparaat_naam: 'iPhone van R.',
    is_dev_stub: false,
    aangemaakt_op: '2026-08-11T10:00:00Z',
    laatst_gebruikt_op: '2026-08-15T09:00:00Z',
    ingetrokken_op: null,
  },
]

/** Brede variant: toestel mét platform + gekoppeld + laatst gebruikt én een oude passkey "niet meer gebruikt". */
const APPARATEN_BREED = [
  {
    id: 'toestel-1',
    apparaat_naam: 'iPhone 15 Pro van Hendrik-Jan',
    is_dev_stub: false,
    aangemaakt_op: '2026-09-08T10:00:00Z',
    laatst_gebruikt_op: '2026-09-10T12:00:00Z',
    ingetrokken_op: null,
    soort: 'toestel',
    platform: 'ios',
    niet_meer_gebruikt_op: null,
  },
  {
    id: 'passkey-oud',
    apparaat_naam: 'iPhone (oud)',
    is_dev_stub: false,
    aangemaakt_op: '2026-08-11T10:00:00Z',
    laatst_gebruikt_op: '2026-08-30T12:00:00Z',
    ingetrokken_op: null,
    soort: 'passkey',
    platform: null,
    niet_meer_gebruikt_op: '2026-09-08T08:00:00Z',
  },
]

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

const echteFetch = window.fetch.bind(window)
window.fetch = (invoer: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = typeof invoer === 'string' ? invoer : invoer instanceof URL ? invoer.toString() : invoer.url
  if (url === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken() }))
  if (url.startsWith('/auth/gebruikers')) return Promise.resolve(jsonResponse({ gebruikers: BREED ? GEBRUIKERS_BREED : GEBRUIKERS }))
  if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: ADMINISTRATIES }))
  if (url === '/uren/beheer/veldgebruikers') return Promise.resolve(jsonResponse(BREED ? VELDGEBRUIKERS : []))
  // Rechten-switches: in de brede variant álle toggles aan (Demi + Anne-Marie).
  if (url === '/uren/beheer/module-recht' || url === '/uren/beheer/veldwerkerbeheer-recht') {
    return Promise.resolve(
      jsonResponse({ gebruiker_ids: BREED ? ['bbbbbbbb-0000-0000-0000-00000000000b', '11111111-0000-0000-0000-000000000011'] : [] }),
    )
  }
  if (url.includes('/apparaten')) return Promise.resolve(jsonResponse({ apparaten: BREED ? APPARATEN_BREED : APPARATEN_STANDAARD }))
  return echteFetch(invoer, init)
}

if (params.has('donker')) {
  document.documentElement.classList.add('dark')
  document.body.classList.add('dark')
}

// ?meet=1 — meetstand (alleen dev): natuurlijke max-content-breedte per kolom. Table-layout auto +
// nowrap op alle cellen; de <col>-breedtes en de tabel-min-width worden losgelaten zodat de inhoud
// zelf de kolommen bepaalt. Uitlezen op een venster breder dan de som (bv. 4000 px).
if (MEET) {
  const stijl = document.createElement('style')
  stijl.textContent = `
    .gebruikers-tabel { table-layout: auto !important; min-width: 0 !important; width: auto !important; }
    .gebruikers-tabel col { width: auto !important; }
    .gebruikers-tabel th, .gebruikers-tabel td { white-space: nowrap !important; min-width: 0 !important; }
    .gebruikers-tabel .chips-regel { flex-wrap: nowrap !important; }
    .gebruikers-tabel .cel-detail { white-space: normal !important; }
    .gebruikers-tabel .apparaat-rij .apparaat-chip { flex-shrink: 0; }
    .gebruikers-tabel .gebruiker-email, .gebruikers-tabel .apparaat-rij .apparaat-chip { overflow: visible !important; text-overflow: clip !important; }
    .gebruikers-tabel .naam-met-avatar { white-space: nowrap; }
  `
  document.head.appendChild(stijl)
}

// Probes (patroon C9 verzamelbak-rijhoogtes): meetbare feiten i.p.v. oogschatting.
window.setTimeout(() => {
  if (SCOPE) {
    // Scope-dialoog (blok 2 nachtrun 10/11-09): rijen zichtbaar in de lijst + interne horizontale overloop van de
    // dialooginhoud. De Radix-overlay is zelf een scroll-container, dus de pagina-badge ziet die overloop niet —
    // daarom hier expliciet, mét dezelfde "OVERFLOW —"-tekst waar de sweep op grep't.
    const lijst = document.querySelector<HTMLElement>('[data-testid="scope-lijst-rijen"]')
    const dialoog = document.querySelector<HTMLElement>('[role="dialog"]')
    const rijen = lijst ? Math.floor(lijst.clientHeight / SCOPELIJST_RIJHOOGTE_PX) : -1
    const scrollx = dialoog ? dialoog.scrollWidth - dialoog.clientWidth : -1
    const lijstScrollx = lijst ? lijst.scrollWidth - lijst.clientWidth : -1
    const dialoogBreedte = dialoog ? Math.round(dialoog.getBoundingClientRect().width) : -1
    const dialoogRechts = dialoog ? Math.round(dialoog.getBoundingClientRect().right) : -1
    document.body.dataset.scopeDialoog = `rijen=${rijen};scrollx=${scrollx};lijstScrollx=${lijstScrollx};dialoogBreedte=${dialoogBreedte};dialoogRechts=${dialoogRechts};viewport=${window.innerWidth}`
    if (scrollx > 0 || lijstScrollx > 0 || dialoogRechts > window.innerWidth || !dialoog) {
      const melding = document.createElement('div')
      melding.setAttribute('data-harnas-badge', '')
      melding.style.cssText = 'position:fixed;right:8px;bottom:8px;z-index:999;padding:4px 10px;border-radius:6px;font-size:12px;font-weight:700;color:#fff;background:#b42318'
      melding.textContent = dialoog
        ? `OVERFLOW — scope-dialoog scrollWidth ${dialoog.scrollWidth} / viewport ${window.innerWidth} (lijst ${lijstScrollx}, rechts ${dialoogRechts})`
        : 'OVERFLOW — scope-dialoog niet gevonden (render mislukt)'
      document.body.appendChild(melding)
    }
  }
  const tabellen = Array.from(document.querySelectorAll<HTMLTableElement>('.gebruikers-tabel'))
  document.body.dataset.gebruikersKolombreedtes = tabellen
    .map((t) =>
      Array.from(t.querySelectorAll<HTMLTableCellElement>('thead th'))
        .map((th) => `${th.textContent?.trim() || 'acties'}=${th.offsetWidth}`)
        .join(';'),
    )
    .join('|')
  document.body.dataset.gebruikersChipregels = tabellen
    .map((t) => Math.max(0, ...Array.from(t.querySelectorAll<HTMLElement>('.chips-regel')).map((c) => c.offsetHeight)))
    .join('|')
  document.body.dataset.gebruikersTabelscroll = Array.from(document.querySelectorAll<HTMLElement>('.tabel-scroll'))
    .map((s) => s.scrollWidth - s.clientWidth)
    .join('|')
}, 1500)

const START = GROEP
  ? `/gebruikers?groep=${encodeURIComponent(GROEP)}`
  : SCOPE && SCOPE_VARIANT === 'accordeur'
    ? '/gebruikers?groep=accordeurs'
    : '/gebruikers'

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
              <a className="nav-item actief">Gebruikers</a>
            </nav>
            <div className="main">
              <div className="content">
                <Routes>
                  <Route path="/gebruikers" element={<GebruikersScreen />} />
                </Routes>
                {SCOPE > 0 && SCOPE_VARIANT !== 'accordeur' && (
                  <ScopeModal gebruiker={SCOPE_DEMI} administraties={ADMINISTRATIES} onSluiten={() => undefined} onGewijzigd={() => undefined} />
                )}
                {SCOPE > 0 && SCOPE_VARIANT === 'accordeur' && (
                  <div hidden>
                    <AccordeurAdministraties
                      gebruiker={SCOPE_ACCORDEUR}
                      administraties={ADMINISTRATIES}
                      naamPerAdministratie={new Map(ADMINISTRATIES.map((a) => [a.id, a.naam]))}
                      onGewijzigd={() => undefined}
                      initieelToevoegen
                    />
                  </div>
                )}
              </div>
            </div>
          </div>
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>
    <OverflowBadge />
  </StrictMode>,
)
