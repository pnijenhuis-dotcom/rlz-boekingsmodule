/** Vorm van het AI-veldvoorstel zoals de backend-controlelaag het in de document-tijdlijn zet
 * (backend/app/extractie/controle.py::bouw_veldvoorstel). De AI levert alléén voorstellen met
 * zekerheidsscores; alle cijfers zijn door de backend deterministisch geparst en getoetst. */

export interface AiRegelVoorstel {
  omschrijving: string | null
  netto_bedrag: string | null
  btw_bedrag: string | null
  hoeveelheid: string | null
  taxrate_id: string | null
  /** 'factuur' als de btw-code deterministisch uit netto/btw is afgeleid (punt 3, 26-08). */
  btw_bron?: string | null
  /** Blok 10 07-09: project-/werknummer van de opdrachtgever op déze regel zoals gelezen (ruw; de server matcht). */
  project_tekst?: string | null
  /** Blok 4 08-09: tariefstaffel-regel (aantal 0, bedrag 0, btw 0) — bron ja, boekingsregel nee (nulregels.ts). */
  tariefstaffel?: boolean
}

export interface AiControle {
  regelsom: string | null
  /** 'incl' (Σnetto+Σbtw vs incl-totaal) | 'excl' (Σnetto vs excl-totaal) — C3 26-08: exact de
   * netto+btw=incl-logica van de boekingsregels-toets; null = niets te toetsen. */
  regelsom_basis?: 'incl' | 'excl' | null
  regelsom_wijkt_af: boolean | null
  /** Bugfix 04-09 (Huvanco): waarom er níét getoetst is — 'btw_per_regel_ontbreekt' (alleen incl gelezen,
   * btw per regel leeg: nooit stil Σnetto vs incl), 'netto_ontbreekt', 'geen_totaal'; null = wél getoetst. */
  regelsom_reden?: 'btw_per_regel_ontbreekt' | 'netto_ontbreekt' | 'geen_totaal' | null
  onparseerbaar: string[]
  lage_zekerheid: string[]
  bsn_verwijderd: number
  /** True = de regelset is mogelijk incompleet (chunking kreeg het niet aantoonbaar compleet) —
   * bij projectadministraties komt zo'n voorstel er überhaupt niet (handmatig_afmaken). */
  onvolledig: boolean
}

/** Herkomst van het veldvoorstel: 'ai' (Claude-extractie) of 'template' (deterministische terugval —
 * geleerd template van de leverancier, lokale code, geen AI; best-practice-besluit 2, 31-08). */
export type VeldvoorstelBron = 'ai' | 'template'

export interface TemplateHerkomst {
  id: string
  sleutel_soort: 'btw_nummer' | 'kvk_nummer' | 'administratie_vendor'
  versie: number
  herkend_op: 'btw_nummer' | 'kvk_nummer' | 'iban' | 'naam'
  velden: Record<string, string>
  btw_percentage: string
}

export interface AiVoorstel {
  bron: VeldvoorstelBron
  leverancier_naam: string | null
  factuurnummer: string | null
  factuurdatum: string | null
  vervaldatum: string | null
  valuta: string | null
  totaal_excl: string | null
  totaal_incl: string | null
  btw_bedrag: string | null
  /** Letterlijke "btw verlegd"-vermelding, alleen als code die als verleggingstekst herkent. */
  btw_verlegd_vermelding?: string | null
  /** Blok 9 (07-09): voorgelezen betreft-/onderwerpregel van de factuur — voedt server-side de kop-omschrijving. */
  betreft?: string | null
  regelaantal: number
  /** Blok 10 07-09: project-/werknummer van de opdrachtgever op de factuurkop zoals gelezen (ruw; de server matcht). */
  project_tekst?: string | null
  regels: AiRegelVoorstel[]
  zekerheid: Record<string, number>
  /** Eén zekerheidsscore per regel (compact schema, 2026-07-10). */
  regel_zekerheid: number[]
  zekerheid_drempel: number
  /** Punt 14 (28-08): nummer-match wint vóór de naam — 'btw_nummer' | 'kvk_nummer' zijn de zekerste. */
  vendor_suggestie: { vendor_id: string; match: 'exact' | 'fuzzy' | 'btw_nummer' | 'kvk_nummer' | 'iban' } | null
  /** KvK-/btw-mismatch-guard (controlescherm v2 ⑥, 02-09): naam-match die bewust níét is voorgesteld. */
  vendor_waarschuwing?: {
    vendor_id: string
    naam: string
    reden: 'kvk_afwijkend' | 'btw_afwijkend'
    factuur_nummer: string
    kandidaat_nummer: string
  } | null
  iban?: string | null
  /** Alleen bij bron 'template': welk template, hoe de crediteur herkend is, herkomst per veld. */
  template?: TemplateHerkomst
  /** Punt 14: btw-/KvK-nummer van de leverancier uit de factuur (deterministisch gevalideerd). */
  btw_nummer?: string | null
  btw_nummer_geverifieerd?: boolean | null
  kvk_nummer?: string | null
  controle: AiControle
}

export function alsAiVoorstel(veldvoorstel: Record<string, unknown> | null | undefined): AiVoorstel | null {
  if (!veldvoorstel || (veldvoorstel.bron !== 'ai' && veldvoorstel.bron !== 'template')) return null
  return veldvoorstel as unknown as AiVoorstel
}

/** Deterministisch UBL-veldvoorstel (blok 3 herstelrun 08-09, backend/app/documenten/ubl.py): geen zekerheids-
 * scores (het is geen gok), wél de crediteur-identiteit rechtstreeks uit de XML — voedt de crediteur-kaart en
 * "+ Nieuwe crediteur in RLZ". `bron: 'ubl'` sinds 08-09; oudere UBL-voorstellen herken je aan `ubl_regels`. */
export interface UblVoorstel {
  bron: 'ubl'
  leverancier_naam: string | null
  factuurnummer: string | null
  kvk_nummer: string | null
  btw_nummer: string | null
  btw_nummer_geverifieerd: boolean | null
  iban: string | null
  leverancier_adres: string | null
  vendor_suggestie: { vendor_id: string; match: string } | null
}

function tekst(waarde: unknown): string | null {
  return typeof waarde === 'string' && waarde.trim() ? waarde : null
}

export function isUblVoorstel(veldvoorstel: Record<string, unknown> | null | undefined): boolean {
  if (!veldvoorstel) return false
  return veldvoorstel.bron === 'ubl' || (veldvoorstel.bron == null && Array.isArray(veldvoorstel.ubl_regels))
}

export function alsUblVoorstel(veldvoorstel: Record<string, unknown> | null | undefined): UblVoorstel | null {
  if (!veldvoorstel || !isUblVoorstel(veldvoorstel)) return null
  const suggestie = veldvoorstel.vendor_suggestie
  return {
    bron: 'ubl',
    leverancier_naam: tekst(veldvoorstel.leverancier_naam),
    factuurnummer: tekst(veldvoorstel.factuurnummer),
    kvk_nummer: tekst(veldvoorstel.kvk_nummer),
    btw_nummer: tekst(veldvoorstel.btw_nummer),
    btw_nummer_geverifieerd:
      typeof veldvoorstel.btw_nummer_geverifieerd === 'boolean' ? veldvoorstel.btw_nummer_geverifieerd : null,
    iban: tekst(veldvoorstel.iban),
    leverancier_adres: tekst(veldvoorstel.leverancier_adres),
    vendor_suggestie:
      suggestie && typeof suggestie === 'object' && 'vendor_id' in suggestie
        ? (suggestie as { vendor_id: string; match: string })
        : null,
  }
}

export function isTemplateVoorstel(voorstel: AiVoorstel | null | undefined): boolean {
  return voorstel?.bron === 'template'
}

export function zekerheidPct(score: number): string {
  return `${Math.round(score * 100)}%`
}
