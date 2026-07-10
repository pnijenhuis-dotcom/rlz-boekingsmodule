/** Vorm van het AI-veldvoorstel zoals de backend-controlelaag het in de document-tijdlijn zet
 * (backend/app/extractie/controle.py::bouw_veldvoorstel). De AI levert alléén voorstellen met
 * zekerheidsscores; alle cijfers zijn door de backend deterministisch geparst en getoetst. */

export interface AiRegelVoorstel {
  omschrijving: string | null
  netto_bedrag: string | null
  btw_bedrag: string | null
  hoeveelheid: string | null
  taxrate_id: string | null
}

export interface AiControle {
  regelsom: string | null
  regelsom_wijkt_af: boolean | null
  onparseerbaar: string[]
  lage_zekerheid: string[]
  bsn_verwijderd: number
  /** True = de regelset is mogelijk incompleet (chunking kreeg het niet aantoonbaar compleet) —
   * bij projectadministraties komt zo'n voorstel er überhaupt niet (handmatig_afmaken). */
  onvolledig: boolean
}

export interface AiVoorstel {
  bron: 'ai'
  leverancier_naam: string | null
  factuurnummer: string | null
  factuurdatum: string | null
  vervaldatum: string | null
  valuta: string | null
  totaal_excl: string | null
  totaal_incl: string | null
  btw_bedrag: string | null
  regelaantal: number
  regels: AiRegelVoorstel[]
  zekerheid: Record<string, number>
  /** Eén zekerheidsscore per regel (compact schema, 2026-07-10). */
  regel_zekerheid: number[]
  zekerheid_drempel: number
  vendor_suggestie: { vendor_id: string; match: 'exact' | 'fuzzy' } | null
  controle: AiControle
}

export function alsAiVoorstel(veldvoorstel: Record<string, unknown> | null | undefined): AiVoorstel | null {
  if (!veldvoorstel || veldvoorstel.bron !== 'ai') return null
  return veldvoorstel as unknown as AiVoorstel
}

export function zekerheidPct(score: number): string {
  return `${Math.round(score * 100)}%`
}
