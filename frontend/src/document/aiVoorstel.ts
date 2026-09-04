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
  regelaantal: number
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

export function isTemplateVoorstel(voorstel: AiVoorstel | null | undefined): boolean {
  return voorstel?.bron === 'template'
}

export function zekerheidPct(score: number): string {
  return `${Math.round(score * 100)}%`
}
