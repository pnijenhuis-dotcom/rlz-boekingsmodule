// Pure presentatiehelpers voor het offerte-verbruik (Peter 18-09) — bewust ZONDER API-imports: de accordeur-app
// (eigen lazy chunk, geen kantoor-bundels) importeert dit óók.

/** Segmentbreedtes (in %) voor de driedelige verbruiksbalk (Peter 18-09): geboekt vol, onderweg gearceerd, de eigen
 * factuur gemarkeerd. Puur presentatie — verhoudingen van server-bedragen; samen nooit boven 100 (een overschrijding is
 * vol, het bedrag erover staat in de tekst). Onbruikbaar totaal → alles 0. */
export function verbruikSegmenten(delen: {
  geboekt: string | null | undefined
  onderweg?: string | null | undefined
  eigen?: string | null | undefined
  totaal: string | null | undefined
}): { geboekt: number; onderweg: number; eigen: number } {
  const totaal = Number(delen.totaal)
  if (!Number.isFinite(totaal) || totaal <= 0) return { geboekt: 0, onderweg: 0, eigen: 0 }
  const pct = (w: string | null | undefined): number => {
    const n = Number(w ?? 0)
    return Number.isFinite(n) && n > 0 ? (n / totaal) * 100 : 0
  }
  const geboekt = Math.min(100, pct(delen.geboekt))
  const onderweg = Math.min(100 - geboekt, pct(delen.onderweg))
  const eigen = Math.min(100 - geboekt - onderweg, pct(delen.eigen))
  return { geboekt, onderweg, eigen }
}

/** "waarvan € 20.000,00 nog niet geboekt (1 factuur ter accordering)" — dezelfde zin als de server-melding
 * (`match.onderweg_tekst`); leeg als er niets onderweg is. */
export function onderwegTekst(
  bedrag: string | null | undefined,
  aantal: number | null | undefined,
  terAccordering: number | null | undefined,
  formatBedrag: (w: string | null) => string,
): string {
  const n = aantal ?? 0
  if (n <= 0 || !bedrag || Number(bedrag) <= 0) return ''
  const stand = (terAccordering ?? 0) >= n ? 'ter accordering' : 'in behandeling'
  return `waarvan ${formatBedrag(bedrag ?? null)} nog niet geboekt (${n} ${n === 1 ? 'factuur' : 'facturen'} ${stand})`
}

