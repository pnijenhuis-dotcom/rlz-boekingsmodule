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
import { Profiler, StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { WerkvoorraadScreen } from '../werkvoorraad/WerkvoorraadScreen'
import { ProjectenKantoorbreedScreen } from '../projecten/ProjectenKantoorbreedScreen'
import { MeerwerkScreen } from '../meerwerk/MeerwerkScreen'
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
// Opdracht 19-09: tab "Afsluiten? (N)" (?projecten=1&tab=afsluiten) — breedste realistische rij: lange projectnaam, vier
// reden-chips, laatste activiteit mét bedrag + boekstuk, open posten mét drie delen, "Niet afsluiten…" + "Openen →".
const AFSLUIT_KANDIDATEN = {
  rijen: [
    {
      administratie_id: ADMIN_1,
      administratie_naam: 'Universal Steigerbouw B.V.',
      project_id: '44444444-0000-0000-0000-000000000001',
      naam: 'Afgesloten 25017 Kudo Arnhem-Kronenburg fase 2 (Kudo Bouw & Ontwikkeling)',
      redenen: ['stil', 'eindfactuur', 'naam_afgesloten', 'looptijd_verstreken'],
      reden_tekst: 'geen activiteit sinds 2026-03-01 (202 dagen, venster 6 mnd) · eindfactuur geboekt (VF-2026-0412) · naam zegt afgesloten, status actief · looptijd tot 2026-06-30 verstreken',
      laatste_activiteit: { soort: 'verkoop', datum: '2026-03-01', bedrag: '48250.00', boekstuk: 'VF-2026-0412 Eindfactuur fase 2' },
      stil_dagen: 202,
      stil_maanden: 6,
      open_posten: { inkoop_niet_geboekt: 2, inkoop_niet_geboekt_bedrag: '1834.50', verplichting_open: 1, uren_niet_gekeurd: 3, let_op: true },
      looptijd_tot: '2026-06-30',
      uitstel: null,
    },
    {
      administratie_id: ADMIN_1,
      administratie_naam: 'Universal Steigerbouw B.V.',
      project_id: '44444444-0000-0000-0000-000000000002',
      naam: '25157 Harderwijk (Wessels)',
      redenen: ['stil'],
      reden_tekst: 'geen activiteit sinds 2026-03-30 (173 dagen, venster 6 mnd)',
      laatste_activiteit: { soort: 'verkoop', datum: '2026-03-30', bedrag: '3120.00', boekstuk: 'VF-2026-0301' },
      stil_dagen: 173,
      stil_maanden: 6,
      open_posten: { inkoop_niet_geboekt: 0, inkoop_niet_geboekt_bedrag: '0', verplichting_open: 0, uren_niet_gekeurd: 0, let_op: false },
      looptijd_tot: null,
      uitstel: null,
    },
  ],
  totaal: 2,
  pagina: 1,
  per_pagina: 50,
  tellers: { kandidaten: 2, uitgesteld: 1, administraties: 1, per_reden: { stil: 2, eindfactuur: 1, naam_afgesloten: 1, looptijd_verstreken: 1 }, let_op: 1 },
  redenen: ['stil', 'eindfactuur', 'naam_afgesloten', 'looptijd_verstreken'],
  reden_labels: { stil: 'geen activiteit', eindfactuur: 'eindfactuur geboekt', naam_afgesloten: 'naam zegt afgesloten', looptijd_verstreken: 'looptijd verstreken' },
  stil_maanden: null,
}

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

// Bug 18-09: Beoordelen › Urenstaten (?beoordelen=1) — breedste realistische rijen: lange projectnaam, namens-regel,
// 14 staten zoals de casus Universal; kolomminima uit meerwerk/beoordelenKolommen.ts.
const BEOORDELEN_WEEKSTATEN = {
  laatste_keuring_op: null,
  items: Array.from({ length: 14 }, (_, i) => ({
    weekstaat_id: `ws-${String(i + 1).padStart(2, '0')}`,
    administratie_id: ADMIN_1,
    administratie_naam: 'Universal Steigerbouw B.V.',
    zzper_id: `zz-${i % 4}`,
    zzper_naam: ['Mustafa Sanli-Yildirim', 'Raif Yücetaş', 'Hasan Ucan', 'Vladimir Ponchev'][i % 4],
    project_id: `pr-${i % 3}`,
    project_naam: ['26129 Hilversum, Larenseweg 125 (Huvanco)', '26030 Scherpenzeel, Orangerie 21 (Davelaar bouw)', '25162 Groesbeek stempels (Janssen-Groesbeek)'][i % 3],
    jaar: 2026,
    weeknummer: 37,
    totaal_uren: '38.5',
    totaal_m2: i % 2 === 0 ? '142.25' : '0',
    ingediend_op: '2026-09-15T07:41:00Z',
    ingediend_namens: i % 5 === 0,
    ingediend_door_naam: i % 5 === 0 ? 'Detacheerder Personeelsdiensten Oost B.V.' : null,
  })),
}
const BEOORDELEN_STAND = {
  meerwerk_te_beoordelen: 0,
  meerwerk_nog_doorbelasten: 0,
  meerwerk_te_lang_niet_doorbelast: 0,
  urenstaten_wachten_op_keuring: 14,
  dossier_veldwerkers_met_signaal: 0,
  dossier_ter_controle: 0,
  dossier_geblokkeerd: 0,
}


// ---------------------------------------------------------------------------------------------------------------
// Blok 7 feedbackrun A 25-09 (FV-18 "scherm loopt vast bij wisselen tabblad" — EERST REPRODUCEREN): productie-achtige
// lijstgrootte + meetlus in de pagina zelf, zodat headless Chrome (scripts/tabwissel_meting.mjs, CDP, échte klok — geen
// --virtual-time-budget: daaronder staat performance.now() stil tijdens een lange taak) een reproduceerbare meting doet.
//   ?docs=<N>          N ≥ 2 → N gegenereerde documenten voor ADMIN_1 (mix van statussen + chips/signalen zoals Universal
//                      Steigerbouw: te controleren, klaar om te boeken, vragen, ter accordering, IBAN, mislukt, signalen).
//   ?tabwissel=<K>     ná de eerste render K × wisselen te_controleren ↔ klaar_om_te_boeken; per wissel de tijd tot de lijst
//                      opnieuw gerenderd is (rAF ×2 ná de klik) én de fetches; uitkomst als data-attributen op <body>.
//   ?latency=<ms>      vertraging van élk gemockt antwoord (maakt "geen abort van lopende fetches" meetbaar).
// Fetch-telling (altijd aan): gestart / afgerond / afgebroken (AbortSignal gehonoreerd) / open (gestart − afgerond − afgebroken).
const TABWISSEL_PARAMS = new URLSearchParams(window.location.search)
const DOCS_AANTAL = Number(TABWISSEL_PARAMS.get('docs') ?? '0')
const MOCK_LATENCY_MS = Number(TABWISSEL_PARAMS.get('latency') ?? '0')
// ?poll=1: elke 50e rij staat in extractie_wachtrij (en elke 75e op wordt_geboekt) → de lijst pollt elke 3 s (EXTRACTIE_POLL_MS),
// zoals in productie zodra er ook maar één document in de wachtrij of bij de achtergrond-schrijver staat.
const POLL_ACTIEF = TABWISSEL_PARAMS.get('poll') === '1'

const GENERATOR_LEVERANCIERS = [
  'Universal Nederland B.V.', 'Floor Bouwliftenservice', 'Hoogwerkservice Hardinxveld B.V.', 'Huvanco Verhuur- en Handelmaatschappij B.V.',
  'Steigertekening.nl bv', 'Universal Verkoop B.V.', 'Scafom-rux Nederland B.V.', 'Metselbedrijf Ben Kuijer', 'Argos Packaging Systems',
  'Damitech B.V.', 'ABS trading', 'H.T.I. Verhuur Wijchen', 'G.J. Rijksen en Zoon', 'Exact Software Nederland B.V.', 'DCTE B.V.',
]
// Verdeling ≈ Universal Steigerbouw (veel te controleren, een flinke tab klaar om te boeken, ~10 % bij de klant).
const GENERATOR_STATUSSEN = [
  'te_controleren', 'te_controleren', 'te_controleren', 'te_controleren', 'klaar_om_te_boeken', 'klaar_om_te_boeken', 'klaar_om_te_boeken',
  'ter_accordering', 'vraag_open', 'wacht_op_iban_accordering', 'handmatig_afmaken', 'boeken_mislukt',
]
function genereerDocumenten(n: number) {
  return Array.from({ length: n }, (_, i) => {
    const status = POLL_ACTIEF && i % 50 === 0 ? 'extractie_wachtrij' : POLL_ACTIEF && i % 75 === 0 ? 'wordt_geboekt' : GENERATOR_STATUSSEN[i % GENERATOR_STATUSSEN.length]
    const leverancier = GENERATOR_LEVERANCIERS[(i * 7) % GENERATOR_LEVERANCIERS.length]
    const dag = String(1 + (i % 28)).padStart(2, '0')
    const maand = String(1 + (i % 9)).padStart(2, '0')
    const id = `bbbbbbbb-1111-0000-0000-${String(i + 1).padStart(12, '0')}`
    return {
      id,
      bestandsnaam: `${leverancier.split(' ')[0]} - RLZ-2080${String(140000 + i)} - 2026-${maand}-${dag}.${i % 5 === 0 ? 'xml' : 'pdf'}`,
      status,
      bron: i % 3 === 0 ? 'upload' : 'email',
      soort: i % 23 === 0 ? 'verplichting' : 'inkoopfactuur',
      mogelijk_duplicaat_van:
        i % 7 === 0 ? { document_id: `bbbbbbbb-1111-0000-0000-${String(i).padStart(12, '0')}`, bestandsnaam: `kopie ${i}.pdf`, aangemaakt_op: '2026-08-01T09:00:00Z' } : null,
      toegewezen_aan: i % 4 === 0 ? '11111111-0000-0000-0000-000000000002' : null,
      aangemaakt_op: `2026-${maand}-${dag}T09:${String(i % 60).padStart(2, '0')}:00Z`,
      laatst_gewijzigd_op: `2026-${maand}-${dag}T10:00:00Z`,
      afwijzing: null,
      leverancier,
      totaalbedrag: ((i * 137.53) % 9000 + 12.5).toFixed(2),
      factuurdatum: `2026-${maand}-${dag}`,
      automatisch_geboekt: false,
      duplicaatsignaal: i % 9 === 0 ? { uitkomst: 'mogelijk_duplicaat', aantal_treffers: 1, berekend_op: '2026-09-20T06:00:00Z' } : null,
      verplichting_match: i % 11 === 0 ? { uitkomst: i % 22 === 0 ? 'binnen' : 'buiten', offertenummer: 'S00642', overschrijding_excl: '1250.00' } : null,
      factuurmatch: i % 13 === 0 ? { uitkomst: 'afwijking', verschil_bedrag: '412.00', tarief_ontbreekt: false } : null,
      accordeur_aan_de_beurt: status === 'ter_accordering' ? { naam: 'Sophia Gerritsen', laag: 2 } : null,
      klant_akkoord_compleet: false,
      samengevoegde_exemplaren: i % 17 === 0 ? 2 : 0,
      afgevoerde_exemplaren: i % 17 === 0 ? 1 : 0,
      duplicaat_werkvoorraad_van: i % 19 === 0 ? { document_id: id, bestandsnaam: `ouder ${i}.pdf`, aangemaakt_op: '2026-07-01T09:00:00Z' } : null,
    }
  })
}
const DOCUMENTEN_GEGENEREERD =
  DOCS_AANTAL >= 2
    ? {
        documenten: genereerDocumenten(DOCS_AANTAL),
        afgehandeld: { verwijderd: 3, afgewezen: 2, samengevoegd: 40, afgevoerd_duplicaat: 12, geboekt: 900, gesplitst: 0, geaccordeerd: 0, totaal: 957 },
      }
    : null

const fetchTelling = { gestart: 0, afgerond: 0, afgebroken: 0, perUrl: new Map<string, number>(), echt: [] as string[] }
declare global {
  interface Window {
    __tabwissel?: Record<string, unknown>
    __fetchTelling?: typeof fetchTelling
  }
}
window.__fetchTelling = fetchTelling

/** Mock-antwoord mét optionele latency én honorering van `init.signal` (AbortError, zoals een échte fetch). */
function mockAntwoord(maak: () => Response, init?: RequestInit): Promise<Response> {
  return new Promise<Response>((resolve, reject) => {
    const signaal = init?.signal
    const afbreken = () => {
      fetchTelling.afgebroken += 1
      reject(new DOMException('The operation was aborted.', 'AbortError'))
    }
    const klaar = () => {
      if (signaal?.aborted) return
      signaal?.removeEventListener('abort', afbreken)
      fetchTelling.afgerond += 1
      resolve(maak())
    }
    if (signaal?.aborted) {
      afbreken()
      return
    }
    signaal?.addEventListener('abort', afbreken, { once: true })
    if (MOCK_LATENCY_MS > 0) window.setTimeout(klaar, MOCK_LATENCY_MS)
    else klaar()
  })
}

const echteFetch = window.fetch.bind(window)
window.fetch = (invoer: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const url = String(invoer)
  fetchTelling.gestart += 1
  const pad = url.replace(/\?.*$/, '')
  fetchTelling.perUrl.set(pad, (fetchTelling.perUrl.get(pad) ?? 0) + 1)
  const mock = (body: unknown) => mockAntwoord(() => jsonResponse(body), init)
  if (url.includes('/uren/kantoor/weekstaten?')) return mock((BEOORDELEN_WEEKSTATEN))
  if (url.includes('/uren/kantoor/meerwerk')) return mock(([]))
  if (url.includes('/uren/kantoor/stand')) return mock((BEOORDELEN_STAND))
  if (url.endsWith('/auth/administraties')) return mock(({ administraties: ADMINISTRATIES }))
  if (url.includes('/projecten/kantoorbreed')) return mock((PROJECTEN_KANTOORBREED))
  if (url.includes('/projecten/afsluit-kandidaten')) return mock((AFSLUIT_KANDIDATEN))
  if (url.endsWith('/werkvoorraad/overzicht')) return mock((WERKVOORRAAD_OVERZICHT))
  if (url.endsWith('/bank/overzicht')) return mock((BANK_OVERZICHT))
  if (url.includes('/doorbelasting/') && url.endsWith('/spiegel-taken')) {
    // Eén open spiegel-taak bij Kempen Facilities → de extra kolom "Spiegel-taken" rendert mee.
    return mock((url.includes(ADMIN_1) ? [{ id: 'taak' }] : []))
  }
  if (url.endsWith('/verzamelbak')) return mock((VERZAMELBAK))
  if (url.includes('/documenten')) {
    // Blok 8 feedbackrun A (FV-20, 25-09), variant ?alles=1: de "Alles"-weergave — server-side groep=alles mét alle
    // statussen (ook geboekt/verwijderd, grijs) én een totaal > 200 zodat de paginabalk (Vorige/Volgende) meet.
    if (PARAMS.has('alles') && url.includes('groep=alles')) {
      return Promise.resolve(
        jsonResponse({
          ...DOCUMENTEN,
          documenten: [
            ...DOCUMENTEN.documenten,
            {
              ...DOCUMENTEN.documenten[0],
              id: 'bbbbbbbb-0000-0000-0000-000000000031',
              bestandsnaam: 'Universal Nederland B.V - RLZ-2080143037 - 2026-08-01.xml',
              status: 'geboekt',
              mogelijk_duplicaat_van: null,
              geboekt_in_rlz: { systeem: 'rlz', boekstuknummer: 'RLZ-25-00003231', memoriaal_boekstuknummer: null, vindplaats_hint: null },
            },
            {
              ...DOCUMENTEN.documenten[0],
              id: 'bbbbbbbb-0000-0000-0000-000000000032',
              bestandsnaam: 'exact-online-abonnement-september-2026-herzonden-kopie-administratie.pdf',
              status: 'ter_accordering',
              mogelijk_duplicaat_van: null,
              accordeur_aan_de_beurt: { gebruiker_id: 'dddddddd-0000-0000-0000-000000000009', naam: 'S. Bakker-van der Hoogenband', laag: 2 },
            },
          ],
          groepen: { kantoor: 6, wachten: 1, afgehandeld: 527, alles: 534 },
          totaal: 534,
          limit: 200,
          offset: 0,
        }),
      )
    }
    return mock((DOCUMENTEN_GEGENEREERD ?? DOCUMENTEN))
  }
  if (url.endsWith('/medewerkers')) return mock((MEDEWERKERS))
  // Klantpagina = standen (IA-verbouwing 15-08): bank per rekening + open vragen.
  if (url.includes('/rekeningen')) {
    return mock(
      ({
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
  // Blok 7 (25-09): de twee accordering-leesroutes van de documentenlijst gemockt — vóór 25-09 vielen ze door naar de
  // échte fetch (vite gaf HTML → apiJson-fout, stil gevangen) en telden ze in de meting als "open".
  if (url.endsWith('/accordering/instellingen')) return mock(({ ingeschakeld: true, lagen: [] }))
  if (url.endsWith('/accordering/vervallen-meldingen')) return mock(([]))
  if (url.includes('/vragen')) {
    return mock(
      ({
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
  fetchTelling.echt.push(url)
  return echteFetch(invoer, init)
}

const PARAMS = new URLSearchParams(window.location.search)
// IA-verbouwing 15-08: ?klant=1 = klantpagina (standen), ?docs=1 = documenten-deelscherm.
// C5 (07-09): ?projecten=1 = Inzicht › Projecten kantoorbreed.
const START_URL = PARAMS.has('beoordelen')
  ? `/meerwerk?administratie=${ADMIN_1}&tab=urenstaten`
  : PARAMS.has('projecten')
  ? (PARAMS.get('tab') === 'afsluiten' ? '/projecten?tab=afsluiten' : '/projecten')
  : PARAMS.has('alles')
    ? `/?administratie=${ADMIN_1}&sectie=documenten&status=__alles`
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


// Blok 7 (25-09): React-commits tellen (Profiler om de Routes) — renders per wissel zijn een meetgetal, geen gevoel.
const profiler = { commits: 0, totaalMs: 0, duren: [] as number[] }
function onRender(_id: string, _fase: string, actualDuration: number) {
  profiler.commits += 1
  profiler.totaalMs += actualDuration
  profiler.duren.push(actualDuration)
}

const TABWISSEL_AANTAL = Number(TABWISSEL_PARAMS.get('tabwissel') ?? '0')
if (TABWISSEL_AANTAL > 0) {
  const wachtOp = (test: () => boolean, timeoutMs = 60000) =>
    new Promise<void>((resolve, reject) => {
      const start = performance.now()
      const tik = () => {
        if (test()) resolve()
        else if (performance.now() - start > timeoutMs) reject(new Error('tabwissel: wachten verlopen'))
        else requestAnimationFrame(tik)
      }
      tik()
    })
  const tweeFrames = () => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())))
  const statusKnop = (label: string) =>
    Array.from(document.querySelectorAll<HTMLButtonElement>('.lijst-werkbalk .segment[aria-label="Filter op status"] button')).find((b) =>
      (b.textContent ?? '').startsWith(label),
    )
  const langeTaken: number[] = []
  if ('PerformanceObserver' in window) {
    try {
      new PerformanceObserver((lijst) => {
        for (const e of lijst.getEntries()) langeTaken.push(e.duration)
      }).observe({ type: 'longtask', buffered: true })
    } catch {
      // longtask niet ondersteund → alleen de eigen klok
    }
  }
  const run = async () => {
    await wachtOp(() => document.querySelector('table.documenten-tabel') !== null && statusKnop('Klaar om te boeken') !== undefined)
    await tweeFrames()
    const fetchVoor = { ...fetchTelling }
    const commitsVoor = profiler.commits
    const tijden: number[] = []
    const rijenPerWissel: number[] = []
    for (let i = 0; i < TABWISSEL_AANTAL; i++) {
      const doel = i % 2 === 0 ? 'Klaar om te boeken' : 'Te controleren'
      const knop = statusKnop(doel)
      if (!knop) throw new Error(`tabwissel: knop "${doel}" ontbreekt`)
      const t0 = performance.now()
      knop.click()
      await wachtOp(() => statusKnop(doel)?.classList.contains('actief') === true)
      await tweeFrames()
      tijden.push(performance.now() - t0)
      rijenPerWissel.push(document.querySelectorAll('table.documenten-tabel tbody tr').length - 1)
    }
    // Trailing fetches (polling/effect-lus) krijgen 1,5 s de tijd om zichtbaar te worden.
    await new Promise((r) => window.setTimeout(r, 1500))
    const max = Math.max(...tijden)
    const gem = tijden.reduce((a, b) => a + b, 0) / tijden.length
    const geheugen = (performance as unknown as { memory?: { usedJSHeapSize: number } }).memory
    const uit = {
      wissels: TABWISSEL_AANTAL,
      docs: DOCS_AANTAL,
      latency: MOCK_LATENCY_MS,
      maxMs: Math.round(max),
      gemMs: Math.round(gem),
      tijden: tijden.map((t) => Math.round(t)),
      rijen: rijenPerWissel,
      fetchGestartTijdens: fetchTelling.gestart - fetchVoor.gestart,
      fetchOpen: fetchTelling.gestart - fetchTelling.afgerond - fetchTelling.afgebroken,
      fetchAfgebroken: fetchTelling.afgebroken,
      fetchTotaal: fetchTelling.gestart,
      fetchEcht: fetchTelling.echt.slice(0, 10),
      commitDuur: profiler.duren.slice(-40).map((d) => Math.round(d)),
      fetchPerUrl: Object.fromEntries(fetchTelling.perUrl),
      commitsTijdens: profiler.commits - commitsVoor,
      commitsTotaal: profiler.commits,
      renderMsTotaal: Math.round(profiler.totaalMs),
      langeTaken: langeTaken.length,
      langsteTaakMs: Math.round(Math.max(0, ...langeTaken)),
      heapMb: geheugen ? Math.round((geheugen.usedJSHeapSize / 1048576) * 10) / 10 : null,
    }
    window.__tabwissel = uit
    const b = document.body.dataset
    b.tabwisselMaxMs = String(uit.maxMs)
    b.tabwisselGemMs = String(uit.gemMs)
    b.tabwisselFetchTijdens = String(uit.fetchGestartTijdens)
    b.fetchOpen = String(uit.fetchOpen)
    b.tabwisselCommits = String(uit.commitsTijdens)
    b.tabwisselJson = JSON.stringify(uit)
    b.tabwisselKlaar = 'ja'
  }
  run().catch((err: unknown) => {
    document.body.dataset.tabwisselKlaar = 'fout'
    document.body.dataset.tabwisselFout = err instanceof Error ? err.message : String(err)
  })
}

const ZONDER_STRICT = TABWISSEL_PARAMS.get('strict') === '0'
const Wortel = ZONDER_STRICT ? ({ children }: { children: ReactNode }) => <>{children}</> : StrictMode
createRoot(document.getElementById('root')!).render(
  <Wortel>
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
            <Profiler id="werkvoorraad" onRender={onRender}>
            <Routes>
              <Route path="/" element={<WerkvoorraadScreen />} />
              <Route path="/projecten" element={<ProjectenKantoorbreedScreen />} />
              <Route path="/meerwerk" element={<MeerwerkScreen />} />
            </Routes>
            </Profiler>
          </div>
        </div>
      </div>
      <OverflowBadge />
    </MemoryRouter>
  </Wortel>,
)
