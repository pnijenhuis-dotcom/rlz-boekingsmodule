// Instellingen v3 (mockup instellingen-v3.html = bouwnorm, akkoord Peter 01-09, iteratie 2):
// twee-paneel met een vaste linker settings-nav in drie groepen + een DETERMINISTISCHE
// zoek-registry (naam + synoniemen + doel-route, geen AI). Dit bestand is de ENE bron voor:
//  - de nav-groepen en -items (rol×sectie-matrix fail-closed, ontwerpnotitie ⑦);
//  - de tabs van de administratie-detailpagina (ontwerpnotitie ③);
//  - de zoek-registry (ontwerpnotitie ⑥) — élk nav-item en élke detailpagina-tab MOET hier een
//    registry-entry hebben; de guard-test instellingenRegistry.test.ts is rood zolang dat niet zo
//    is (zelfde discipline als de copy-instroommarker).
// Schaalregel (ontwerpnotitie ⑧): een nieuwe module = een nav-regel en/of een tab hier — nooit
// meer een tegel.

/** Rol-vlag: `beheerder` = Beheerder-only tenzij een expliciete uitzondering in `zichtbaar`. */
export interface NavItem {
  pad: InstellingenSectie
  titel: string
  uitleg: string
  /** Beheerder-only (default true voor beheer-secties). */
  beheerder: boolean
  /** Extern doel buiten /instellingen (Gebruikers & toegang → /gebruikers). */
  extern?: string
  /** Expliciete rol-uitzondering (spiegel van backend-poorten) — fail-closed: niet genoemd = dicht. */
  rollen?: readonly string[]
}

export interface NavGroep {
  titel: string
  items: readonly NavItem[]
}

export type InstellingenSectie =
  | 'administraties'
  | 'accordering'
  | 'autoboeken'
  | 'doorbelasting'
  | 'boeken'
  | 'intake-ai'
  | 'gebruikers'
  | 'veldwerkers'
  | 'beveiliging'
  | 'materiaal'

export const NAV_GROEPEN: readonly NavGroep[] = [
  {
    titel: 'Administraties',
    items: [
      {
        pad: 'administraties',
        titel: 'Administraties',
        uitleg: 'Per administratie: eigenaar, IBAN-accordeurs, modules, boeken, AI-extractie — mét bulkbediening.',
        beheerder: true,
      },
      {
        pad: 'accordering',
        titel: 'Klant-accordering',
        uitleg: 'Goedkeuring door klanten: lagen, apparaten, staande goedkeuringen — over alle administraties.',
        beheerder: true,
      },
      {
        pad: 'autoboeken',
        titel: 'Autoboeken',
        uitleg: 'Automatisch boeken per leverancier: kandidaten, actief, heroverwegen (opt-in blijft een menselijk besluit).',
        beheerder: true,
      },
      {
        pad: 'doorbelasting',
        titel: 'Doorbelasting',
        uitleg: 'Kempen-doorbelasting: toggle, provisie, whitelist doelentiteiten, opruimlijst.',
        beheerder: true,
      },
    ],
  },
  {
    titel: 'Platform',
    items: [
      {
        pad: 'boeken',
        titel: 'Boeken platformbreed',
        uitleg: 'De poort boven alle administraties (noodstop): aan = boeken kan, uit = boeken staat plat.',
        beheerder: true,
      },
      {
        pad: 'intake-ai',
        titel: 'Intake-AI & kosten',
        uitleg: 'AVG-gate voor de verzamelbak-AI, de maandelijkse AI-kostengrens en de extractie-tellers.',
        beheerder: true,
      },
    ],
  },
  {
    titel: 'Kantoor',
    items: [
      {
        pad: 'gebruikers',
        titel: 'Gebruikers & toegang',
        uitleg: 'Medewerkers, accordeurs en veldwerkers uitnodigen, rollen en scope, blokkeren.',
        beheerder: true,
        extern: '/gebruikers',
      },
      {
        pad: 'veldwerkers',
        titel: 'Veldwerkers',
        uitleg: "Koppelingen (detacheerder ↔ ZZP'er, crediteur), tarieven en ZZP-dossiers — kantoorbreed, administratie als filter.",
        // Veldwerkers-run 14-09: de backend opent /uren/beheer/veldgebruikers óók voor houders van het recht
        // 'veldwerkerbeheer' (per gebruiker, niet per rol). De rol×sectie-matrix kan een recht niet uitdrukken,
        // dus hier Beheerder-only (fail-closed); recht-houders bereiken de pagina via het Shell-nav-item, dat het
        // recht wél kent (`auth/rollen.ts::toontVeldwerkersNav`). Het scherm toont een 403 leesbaar.
        beheerder: true,
        extern: '/veldwerkers',
      },
      {
        pad: 'beveiliging',
        titel: 'Beveiliging',
        uitleg: 'Passkeys van jezelf en van medewerkers (apparaat-kill-switch).',
        beheerder: false,
      },
      {
        pad: 'materiaal',
        titel: 'Materiaalcatalogus',
        uitleg: 'Leveranciers, catalogus (verpakking, m²-lengte), bestel-mailadres, crediteur-koppeling — bij Uren & meerwerk óf een Odoo-koppeling (productbrug).',
        beheerder: true,
        // Besluit Peter 31-08 (spiegel van backend `require_beheerder_of_bp`): B+P bereikt de catalogus.
        rollen: ['boekhouding_projecten'],
      },
    ],
  },
] as const

export const NAV_ITEMS: readonly NavItem[] = NAV_GROEPEN.flatMap((g) => g.items)

/** Alle sectiepaden (ook de externe) — voor route-validatie en de redirect-sweep. */
export const SECTIE_PADEN: ReadonlySet<string> = new Set(NAV_ITEMS.map((i) => i.pad))

/** Oude sectie-URL's (D2 25-08 sectiekaarten + eerdere hash-/query-deep-links) die sinds v3 een
 * ander doel hebben. Alles hier redirect — niets 404't (ontwerpnotitie ⑤). */
export const OUDE_SECTIE_REDIRECTS: Readonly<Record<string, string>> = {
  // Crediteuren-dubbelsignalering is een inzichtscherm, geen instelling → Inzicht-menu.
  crediteuren: '/crediteuren',
  // Externe kaart: het eigen scherm.
  gebruikers: '/gebruikers',
}

/** Rol×sectie-matrix, fail-closed (verzamelrun 31-08 blok B, ongewijzigd in v3): een beheer-item
 * is Beheerder-only tenzij het item de rol expliciet noemt — élk nieuw item of onbekende rol valt
 * dus automatisch dicht. Beveiliging (eigen passkeys) is er voor élke kantoorrol. */
export function zichtbareNavItems(rol: string | null): NavItem[] {
  return NAV_ITEMS.filter((k) => {
    if (!k.beheerder) return true
    if (rol === 'beheerder') return true
    return rol !== null && (k.rollen ?? []).includes(rol)
  })
}

/** Zichtbare groepen — een lege groep krijgt geen kop (ontwerpnotitie ⑦). */
export function zichtbareNavGroepen(rol: string | null): NavGroep[] {
  const zichtbaar = new Set(zichtbareNavItems(rol).map((i) => i.pad))
  return NAV_GROEPEN.map((g) => ({ titel: g.titel, items: g.items.filter((i) => zichtbaar.has(i.pad)) })).filter(
    (g) => g.items.length > 0,
  )
}

/** /instellingen zonder sectie → het eerste zichtbare NIET-externe item van de rol (ontwerpnotitie
 * ①): Beheerder → Administraties, Boekhouding → Beveiliging, B+P → Materiaalcatalogus
 * (Gebruikers & toegang is extern en telt niet als landing). */
export function eersteSectieVoor(rol: string | null): InstellingenSectie {
  const items = zichtbareNavItems(rol).filter((i) => !i.extern)
  if (rol === 'boekhouding_projecten') {
    const materiaal = items.find((i) => i.pad === 'materiaal')
    if (materiaal) return materiaal.pad
  }
  return items[0]?.pad ?? 'beveiliging'
}

// --- Administratie-detailpagina: tabs --------------------------------------------------------

export type DetailTab = 'algemeen' | 'boeken-ai' | 'accordering' | 'doorbelasting' | 'uren-materiaal' | 'voorraad'

/** Minimale administratie-stand die de toon-regel van de tabs nodig heeft (zelfde regel als de
 * chips in de v2-tabel: module-tabs alleen bij opt-in; Doorbelasting alleen als bron of doel). */
export interface AdministratieTabStand {
  doorbelasting_ingeschakeld?: boolean
  doorbelasting_doel?: boolean
  uren_meerwerk_ingeschakeld?: boolean
  voorraad_ingeschakeld?: boolean
}

export interface DetailTabDef {
  pad: DetailTab
  titel: string
  zichtbaar: (a: AdministratieTabStand) => boolean
}

export const DETAIL_TABS: readonly DetailTabDef[] = [
  { pad: 'algemeen', titel: 'Algemeen', zichtbaar: () => true },
  { pad: 'boeken-ai', titel: 'Boeken & AI', zichtbaar: () => true },
  { pad: 'accordering', titel: 'Klant-accordering', zichtbaar: () => true },
  {
    pad: 'doorbelasting',
    titel: 'Doorbelasting',
    zichtbaar: (a) => Boolean(a.doorbelasting_ingeschakeld || a.doorbelasting_doel),
  },
  { pad: 'uren-materiaal', titel: 'Uren & materiaal', zichtbaar: (a) => Boolean(a.uren_meerwerk_ingeschakeld) },
  { pad: 'voorraad', titel: 'Voorraad', zichtbaar: (a) => Boolean(a.voorraad_ingeschakeld) },
] as const

export const DETAIL_TAB_PADEN: ReadonlySet<string> = new Set(DETAIL_TABS.map((t) => t.pad))

export function zichtbareTabs(a: AdministratieTabStand): DetailTabDef[] {
  return DETAIL_TABS.filter((t) => t.zichtbaar(a))
}

export function detailPad(administratieId: string, tab?: DetailTab, anker?: string): string {
  const basis = `/instellingen/administraties/${administratieId}`
  const pad = tab && tab !== 'algemeen' ? `${basis}?tab=${tab}` : basis
  return anker ? `${pad}#${anker}` : pad
}

// --- Zoek-registry (deterministisch) ------------------------------------------------------

export type RegistryDoel =
  | { soort: 'sectie'; sectie: InstellingenSectie; anker?: string }
  /** `anker` (blok A bundel 10-09): een losse instelling bínnen een tab (deep-link `…?tab=x#anker`) — de guard telt
   * alleen tab-entries zónder anker als "de" tab-entry, zoals bij secties. */
  | { soort: 'tab'; tab: DetailTab; anker?: string }

export interface RegistryEntry {
  id: string
  naam: string
  /** Waar het staat, leesbaar (mockup-kolom "waar"). */
  waar: string
  synoniemen: readonly string[]
  doel: RegistryDoel
  /** Beheerder-only entries verdwijnen uit de resultaten van andere rollen (fail-closed). */
  beheerder: boolean
}

export const REGISTRY: readonly RegistryEntry[] = [
  // Nav-items (één entry per item — de guard-test toetst dat).
  {
    id: 'nav-administraties',
    naam: 'Administraties — overzicht',
    waar: 'nav-item Administraties',
    synoniemen: ['administratie', 'bv', 'klant', 'toevoegen', 'archiveren', 'sync', 'webservice', 'schrijftest'],
    doel: { soort: 'sectie', sectie: 'administraties' },
    beheerder: true,
  },
  {
    id: 'nav-accordering',
    naam: 'Klant-accordering — alle administraties',
    waar: 'nav-item Klant-accordering',
    synoniemen: ['accordering', 'accordeur', 'goedkeuring', 'lagen', 'zenvoices', 'ter accordering', 'staande goedkeuring', 'apparaten'],
    doel: { soort: 'sectie', sectie: 'accordering' },
    beheerder: true,
  },
  {
    id: 'nav-autoboeken',
    naam: 'Autoboeken — kandidaten, actief, heroverwegen',
    waar: 'nav-item Autoboeken',
    synoniemen: ['autoboeken', 'automatisch boeken', 'automatisch', 'leverancier', 'kandidaat', 'kandidaten', 'opt-in', 'heroverwegen'],
    doel: { soort: 'sectie', sectie: 'autoboeken' },
    beheerder: true,
  },
  {
    id: 'nav-doorbelasting',
    naam: 'Doorbelasting — toggle, provisie, whitelist',
    waar: 'nav-item Doorbelasting',
    synoniemen: ['doorbelasting', 'doorbelasten', 'kempen', 'provisie', 'whitelist', 'doelentiteit', 'spiegel', 'intercompany'],
    doel: { soort: 'sectie', sectie: 'doorbelasting' },
    beheerder: true,
  },
  {
    id: 'nav-boeken',
    naam: 'Boeken platformbreed (noodstop)',
    waar: 'nav-item Boeken platformbreed',
    // Blok 5 (08-09): het tellersblok "Automatiseringen" staat op deze pagina (verhuisd van Inzicht › Reconciliatie).
    synoniemen: ['boeken', 'platformbreed', 'kill switch', 'noodstop', 'plat', 'boeken kan', 'automatiseringen', 'tellers'],
    doel: { soort: 'sectie', sectie: 'boeken' },
    beheerder: true,
  },
  {
    id: 'nav-boeken-stores',
    naam: 'Stores — kassarapport zonnestudio → administratie (platformbreed)',
    waar: 'Boeken platformbreed › blok Stores',
    synoniemen: ['stores', 'store', 'store used', 'zonnestudio', 'dagstaat', 'kascheck', 'sunshine island', 'elderveld', 'kassarapport', 'omzetbron'],
    doel: { soort: 'sectie', sectie: 'boeken', anker: 'stores' },
    beheerder: true,
  },
  {
    id: 'nav-intake-ai',
    naam: 'Intake-AI & kosten',
    waar: 'nav-item Intake-AI & kosten',
    synoniemen: ['intake', 'ai', 'avg', 'claude', 'kosten', 'limiet', 'maandlimiet', 'verbruik', 'template', 'extractie'],
    doel: { soort: 'sectie', sectie: 'intake-ai' },
    beheerder: true,
  },
  {
    id: 'nav-gebruikers',
    naam: 'Gebruikers & toegang',
    waar: 'nav-item Gebruikers & toegang',
    synoniemen: ['gebruikers', 'gebruiker', 'medewerker', 'uitnodigen', 'rol', 'scope', 'blokkeren', 'account', 'accounts', 'toegang'],
    doel: { soort: 'sectie', sectie: 'gebruikers' },
    beheerder: true,
  },
  {
    id: 'nav-veldwerkers',
    naam: 'Veldwerkers — koppelingen, tarieven, dossiers',
    waar: 'nav-item Veldwerkers',
    synoniemen: ['veldwerkers', 'veldwerker', 'zzp', "zzp'er", 'zzper', 'detacheerder', 'bureau', 'uitvoerder', 'dossier', 'tarief', 'tarieven', 'crediteur koppelen', 'koppeling', 'kvk'],
    doel: { soort: 'sectie', sectie: 'veldwerkers' },
    beheerder: true,
  },
  {
    id: 'nav-beveiliging',
    naam: 'Beveiliging — passkeys en apparaten',
    waar: 'nav-item Beveiliging',
    synoniemen: ['beveiliging', 'passkey', 'passkeys', 'apparaat', 'apparaten', 'kill-switch', 'webauthn', 'face id', 'inloggen'],
    doel: { soort: 'sectie', sectie: 'beveiliging' },
    beheerder: false,
  },
  {
    id: 'nav-materiaal',
    naam: 'Materiaalcatalogus',
    waar: 'nav-item Materiaalcatalogus',
    synoniemen: ['materiaal', 'catalogus', 'steiger', 'steigerbouw', 'bestelling', 'bestellen', 'transport', 'leverancier', 'm2', 'odoo', 'product', 'producten', 'productbrug'],
    doel: { soort: 'sectie', sectie: 'materiaal' },
    beheerder: true,
  },
  // Detailpagina-tabs (één entry per tab — de guard-test toetst dat). Een tab-entry × een
  // administratienaam wordt in de zoeker een administratie-specifieke treffer.
  {
    id: 'tab-algemeen',
    naam: 'Algemeen — eigenaar, IBAN-accordeurs, modules, webservice',
    waar: 'Administraties › <administratie> › tab Algemeen',
    synoniemen: ['eigenaar', 'vragen', 'iban', 'iban-accordeur', 'vastgoed', 'vastly', 'koppeling', 'webservice', 'eerste sync', 'archiveren', 'modules'],
    doel: { soort: 'tab', tab: 'algemeen' },
    beheerder: true,
  },
  {
    id: 'tab-boeken-ai',
    naam: 'Boeken & AI — boeken, AI-extractie, project verplicht, afdelingen, autoboeken',
    waar: 'Administraties › <administratie> › tab Boeken & AI',
    synoniemen: ['boeken', 'ai-extractie', 'extractie', 'project verplicht', 'projectplicht', 'afdeling', 'afdelingen', 'autoboeken', 'omzet'],
    doel: { soort: 'tab', tab: 'boeken-ai' },
    beheerder: true,
  },
  {
    id: 'tab-accordering',
    naam: 'Klant-accordering — lagen, toggle, intercompany-leveranciers',
    waar: 'Administraties › <administratie> › tab Klant-accordering',
    synoniemen: ['accordering', 'accordeur', 'goedkeuring', 'lagen', 'drempel', 'bedragdrempel', 'intercompany', 'groepsbedrijf', 'ic-leverancier', 'overslaan'],
    doel: { soort: 'tab', tab: 'accordering' },
    beheerder: true,
  },
  {
    id: 'tab-doorbelasting',
    naam: 'Doorbelasting — deze administratie',
    waar: 'Administraties › <administratie> › tab Doorbelasting',
    synoniemen: ['doorbelasting', 'doorbelasten', 'provisie', 'whitelist', 'doelentiteit'],
    doel: { soort: 'tab', tab: 'doorbelasting' },
    beheerder: true,
  },
  {
    id: 'tab-uren-materiaal',
    naam: 'Uren & materiaal — dagmax, dossier-documenttypen, catalogus',
    waar: 'Administraties › <administratie> › tab Uren & materiaal',
    synoniemen: ['uren', 'meerwerk', 'weekstaat', 'dagmax', 'dossier', 'documenttypen', 'materiaal', 'planning', 'zzp'],
    doel: { soort: 'tab', tab: 'uren-materiaal' },
    beheerder: true,
  },
  {
    id: 'tab-voorraad',
    naam: 'Voorraad — aansluiting en tolerantie',
    waar: 'Administraties › <administratie> › tab Voorraad',
    synoniemen: ['voorraad', 'aansluiting', 'telling', 'tolerantie', 'artikelgroep', 'normalisatie'],
    doel: { soort: 'tab', tab: 'voorraad' },
    beheerder: true,
  },
  // Losse instelling bínnen een tab (blok A bundel 10-09): de administratie-schakelaar "Autoboeken (leren en boeken)".
  {
    id: 'autoboeken-leren',
    naam: 'Autoboeken (leren en boeken) — schakelaar per administratie + uitzonderingen',
    waar: 'Administraties › <administratie> › tab Boeken & AI › Autoboeken',
    synoniemen: ['autoboeken', 'leren', 'leren en boeken', 'automatisch boeken', 'uitzonderen', 'uitzondering', 'vrijgeven', 'drie op rij', '3 op rij'],
    doel: { soort: 'tab', tab: 'boeken-ai', anker: 'autoboeken-leren' },
    beheerder: true,
  },
  // Omzetbronnen (besluiten Peter 16-09 blok B): stores, tegenrekening per betaalwijze, categorie/btw, combi, PSP.
  {
    id: 'omzetbronnen',
    naam: 'Omzetbronnen — stores, tegenrekening per betaalwijze, categorie/btw pilates, Stripe',
    waar: 'Administraties › <administratie> › tab Boeken & AI › Omzetbronnen',
    synoniemen: ['omzetbronnen', 'omzetbron', 'dagstaat', 'zonnestudio', 'pilates', 'store', 'stores', 'store used', 'tegenrekening', 'kruispost', 'pin onderweg', 'stripe', 'mollie', 'psp', 'combi', 'kasverschil', 'storting'],
    doel: { soort: 'tab', tab: 'boeken-ai', anker: 'omzetbronnen' },
    beheerder: true,
  },
  // 22-09 (BUG Peter, casus VGG / Studio Lacy Lion, migratie 0170): btw-plichtig per administratie.
  {
    id: 'btw-plichtig',
    naam: 'Btw-plichtig — uit = btw in de kosten, geen btw-splitsing (niet-btw-plichtige administratie)',
    waar: 'Administraties › <administratie> › tab Boeken & AI › Btw-plichtig',
    synoniemen: ['btw-plichtig', 'btw plichtig', 'niet btw-plichtig', 'vrijgesteld', 'geen btw', 'btw in de kosten', 'enabletaxreporting', 'btw-aangifte', 'verhuurder', 'vastgoedgroep'],
    doel: { soort: 'tab', tab: 'boeken-ai', anker: 'btw-plichtig' },
    beheerder: true,
  },
  // 18-09 (Peter, casus Rituals — BUA, migratie 0163): btw niet aftrekbaar per grootboekrekening.
  {
    id: 'btw-aftrek',
    naam: 'Btw niet aftrekbaar (BUA) — representatie, relatiegeschenken, kantine',
    waar: 'Administraties › <administratie> › tab Boeken & AI › Btw niet aftrekbaar',
    synoniemen: ['bua', 'niet aftrekbaar', 'aftrek uitgesloten', 'representatie', 'relatiegeschenk', 'relatiegeschenken', 'kantine', 'personeelsvoorziening', 'btw in kosten', 'fles wijn'],
    doel: { soort: 'tab', tab: 'boeken-ai', anker: 'btw-aftrek' },
    beheerder: true,
  },
  // 21-09 (Activa / MVA fase 1, akkoord Peter, migratie 0168): activum aanmaken ná boeken (opt-in), activeringsgrens,
  // termijn + afschrijvingsrekening per categorie, registerstand.
  {
    id: 'activa',
    naam: 'Activa / MVA — activum aanmaken, activeringsgrens, termijnen',
    waar: 'Administraties › <administratie> › tab Boeken & AI › Activa',
    synoniemen: ['activa', 'activum', 'mva', 'vaste activa', 'afschrijving', 'afschrijven', 'activeren', 'activeringsgrens', 'investering', 'inventaris', 'steigermateriaal', 'termijn', 'lineair', 'fixed assets'],
    doel: { soort: 'tab', tab: 'boeken-ai', anker: 'activa' },
    beheerder: true,
  },
  // Losse instellingen bínnen een sectie (deep-link mét anker).
  {
    id: 'bulk-accordering',
    naam: "Bulk: klant-accordering instellen op meerdere BV's",
    waar: 'Administraties › bulkbalk',
    synoniemen: ['bulk', 'accordering', 'meerdere', 'instellen', 'lagen'],
    doel: { soort: 'sectie', sectie: 'administraties', anker: 'bulk' },
    beheerder: true,
  },
  {
    id: 'administratie-toevoegen',
    naam: 'Administratie toevoegen (wizard)',
    waar: 'Administraties › + Administratie toevoegen',
    synoniemen: ['toevoegen', 'nieuw', 'wizard', 'aansluiten', 'onboarden', 'webservice'],
    doel: { soort: 'sectie', sectie: 'administraties', anker: 'toevoegen' },
    beheerder: true,
  },
  {
    id: 'ai-toets-facturen',
    naam: 'AI-plausibiliteitstoets vóór automatische factuurboekingen (platformbreed)',
    waar: 'Boeken platformbreed › AI-plausibiliteitstoets',
    synoniemen: ['ai-toets', 'ai toets', 'plausibiliteit', 'plausibiliteitstoets', 'autoboeken', 'poort', 'twijfel'],
    doel: { soort: 'sectie', sectie: 'boeken', anker: 'ai-toets' },
    beheerder: true,
  },
  {
    id: 'app-updates',
    naam: 'App-updates — live updates accordeur-/veldwerker-app (bundels, cohort, noodrem, toestellen)',
    waar: 'Boeken platformbreed › blok App-updates',
    synoniemen: ['app-updates', 'app updates', 'ota', 'live updates', 'bundel', 'noodrem app', 'testflight', 'app-versie', 'update nodig'],
    doel: { soort: 'sectie', sectie: 'boeken', anker: 'app-updates' },
    beheerder: true,
  },
  {
    id: 'intercompany-relaties',
    naam: 'Intercompany-relaties (afgeleid; bevestigen / uitsluiten)',
    waar: 'Boeken platformbreed › Intercompany-relaties',
    synoniemen: ['intercompany', 'ic', 'groepsmaatschappij', 'tussen onze bedrijven', 'gelieerd', 'factuurmatch', 'relaties'],
    doel: { soort: 'sectie', sectie: 'boeken', anker: 'intercompany' },
    beheerder: true,
  },
  {
    id: 'rc-koppelingen',
    naam: 'Rekening-courant-koppelingen + afkortingen per administratie',
    waar: 'Boeken platformbreed › Rekening-courant',
    synoniemen: ['rekening-courant', 'rekening courant', 'rc', 'tegenrekening', 'afkorting', 'aansluiting', 'saldo'],
    doel: { soort: 'sectie', sectie: 'boeken', anker: 'rekening-courant' },
    beheerder: true,
  },
  {
    id: 'ai-kostenlimiet',
    naam: 'AI-kosten maandlimiet',
    waar: 'Intake-AI & kosten › AI-kosten',
    synoniemen: ['limiet', 'maandlimiet', 'kosten', 'euro', 'budget', 'anthropic'],
    doel: { soort: 'sectie', sectie: 'intake-ai', anker: 'kosten' },
    beheerder: true,
  },
  {
    id: 'autoboek-drempel',
    naam: 'Autoboeken: drempel "N identieke boekingen"',
    waar: 'Autoboeken › criteria',
    synoniemen: ['drempel', 'op rij', 'identiek', 'identieke boekingen', 'criteria', 'kandidaat', 'autoboeken'],
    doel: { soort: 'sectie', sectie: 'autoboeken', anker: 'drempel' },
    beheerder: true,
  },
  {
    id: 'mijn-weekmail',
    naam: 'Weekmail (maandagochtend-digest) aan/uit',
    waar: 'Beveiliging › Weekmail',
    synoniemen: ['weekmail', 'digest', 'maandag', 'mail', 'melding', 'meldingen', 'notificatie', 'opt-out'],
    doel: { soort: 'sectie', sectie: 'beveiliging', anker: 'weekmail' },
    beheerder: false,
  },
  {
    id: 'eigen-passkeys',
    naam: 'Mijn passkeys (dit apparaat toevoegen of intrekken)',
    waar: 'Beveiliging › Mijn apparaten',
    synoniemen: ['passkey', 'mijn apparaten', 'toevoegen', 'intrekken', 'touch id', 'windows hello'],
    doel: { soort: 'sectie', sectie: 'beveiliging', anker: 'mijn' },
    beheerder: false,
  },
] as const

export interface ZoekAdministratie {
  id: string
  naam: string
}

export interface ZoekTreffer {
  sleutel: string
  naam: string
  waar: string
  pad: string
  /** Administratie-specifieke treffers (registry-entry × administratienaam) eerst. */
  administratie?: ZoekAdministratie
}

function normaliseer(tekst: string): string {
  return tekst
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

function tokens(tekst: string): string[] {
  return normaliseer(tekst).split(' ').filter(Boolean)
}

function entryMatcht(entry: RegistryEntry, token: string): boolean {
  const haystack = [entry.naam, ...entry.synoniemen].map(normaliseer)
  return haystack.some((h) => h.split(' ').some((w) => w.startsWith(token)) || h.includes(token))
}

function administratieMatcht(a: ZoekAdministratie, token: string): boolean {
  return tokens(a.naam).some((w) => w.startsWith(token))
}

function sectiePad(doel: Extract<RegistryDoel, { soort: 'sectie' }>): string {
  const item = NAV_ITEMS.find((i) => i.pad === doel.sectie)
  const basis = item?.extern ?? `/instellingen/${doel.sectie}`
  return doel.anker ? `${basis}#${doel.anker}` : basis
}

/** Deterministische zoeker (ontwerpnotitie ⑥): elk zoekwoord moet óf een registry-entry óf een
 * administratienaam raken. Een tab-entry mét een administratie-treffer wordt een deep-link naar
 * die detailpagina-tab ("accordering arvum" → Klant-accordering — ARVUM B.V.); zonder
 * administratie-woorden gelden alleen de secties/tabs zelf. Beheerder-only entries verdwijnen
 * voor andere rollen; een tab-treffer vereist altijd Beheerder (de detailpagina is dat). */
export function zoekInstellingen(
  query: string,
  opties: { rol: string | null; administraties: readonly ZoekAdministratie[] },
  maxResultaten = 8,
): ZoekTreffer[] {
  const woorden = tokens(query)
  if (woorden.length === 0) return []
  const isBeheerder = opties.rol === 'beheerder'
  const zichtbareSectiePaden = new Set(zichtbareNavItems(opties.rol).map((i) => i.pad))
  // Zichtbaarheid volgt de rol×sectie-matrix (zelfde bron als de nav): een sectie-entry is er
  // zodra de sectie zichtbaar is (B+P ziet zo de Materiaalcatalogus), een tab-entry alleen voor
  // de Beheerder (de detailpagina is dat). `beheerder` op de entry is documentatie + guard-test.
  const entries = REGISTRY.filter((e) => {
    if (e.doel.soort === 'sectie') return zichtbareSectiePaden.has(e.doel.sectie)
    return isBeheerder
  })

  // Administratie-woorden: elk woord dat minstens één administratie raakt.
  const administratieWoorden = isBeheerder ? woorden.filter((w) => opties.administraties.some((a) => administratieMatcht(a, w))) : []
  const entryWoorden = woorden.filter((w) => !administratieWoorden.includes(w) || entries.some((e) => entryMatcht(e, w)))

  const treffers: ZoekTreffer[] = []

  // 1) Administratie-specifieke treffers: tab-entries die álle niet-administratie-woorden raken ×
  //    administraties die álle administratie-woorden raken.
  if (administratieWoorden.length > 0) {
    const restWoorden = woorden.filter((w) => !administratieWoorden.includes(w))
    const administraties = opties.administraties.filter((a) => administratieWoorden.every((w) => administratieMatcht(a, w)))
    const tabEntries = entries.filter(
      (e) => e.doel.soort === 'tab' && (restWoorden.length === 0 || restWoorden.every((w) => entryMatcht(e, w))),
    )
    for (const a of administraties) {
      for (const e of tabEntries) {
        if (e.doel.soort !== 'tab') continue
        // Zonder verdere zoekwoorden alleen de Algemeen-tab (de landing van de detailpagina).
        if (restWoorden.length === 0 && e.doel.tab !== 'algemeen') continue
        treffers.push({
          sleutel: `${e.id}:${a.id}`,
          naam: `${e.naam.split(' — ')[0]} — ${a.naam}`,
          waar: e.waar.replace('<administratie>', a.naam),
          pad: detailPad(a.id, e.doel.tab, e.doel.anker),
          administratie: a,
        })
      }
    }
  }

  // 2) Generieke treffers: entries die álle (niet-administratie-)woorden raken.
  const generiekeWoorden = administratieWoorden.length > 0 ? woorden.filter((w) => !administratieWoorden.includes(w)) : entryWoorden
  if (generiekeWoorden.length > 0) {
    for (const e of entries) {
      if (!generiekeWoorden.every((w) => entryMatcht(e, w))) continue
      if (e.doel.soort === 'tab') {
        // Een tab zonder administratie is niet linkbaar — wel als aanwijzing waar het staat.
        treffers.push({ sleutel: e.id, naam: e.naam, waar: e.waar, pad: '/instellingen/administraties' })
        continue
      }
      treffers.push({ sleutel: e.id, naam: e.naam, waar: e.waar, pad: sectiePad(e.doel) })
    }
  }

  // Deterministische volgorde: administratie-treffers eerst, dan registry-volgorde (stabiel).
  const uniek = new Map<string, ZoekTreffer>()
  for (const t of treffers) if (!uniek.has(t.sleutel)) uniek.set(t.sleutel, t)
  return [...uniek.values()].slice(0, maxResultaten)
}
