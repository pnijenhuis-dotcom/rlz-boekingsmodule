/** Tijdlijn-notitie "btw herrekend uit tarief" (opdracht Peter 18-09, backend `boekvoorstel._btw_herrekend_notities`,
 * sleutel `btw_herrekend`): per regel van/naar tarief + btw-bedrag; `in_kosten` = 0 % mét de factuur-btw in de kosten.
 * Pure leeslogica los van React, zelfde patroon als kopOmschrijvingTijdlijn.ts. */

export const BTW_HERREKEND_SLEUTEL = 'btw_herrekend'

interface BtwHerrekendRegel {
  regel?: unknown
  /** 'tarief' (18-09) | 'netto' (FV-09, 25-09); ontbreekt = oude notitie = tarief. */
  aanleiding?: unknown
  btw_van?: unknown
  btw_naar?: unknown
  netto_van?: unknown
  netto_naar?: unknown
  in_kosten?: unknown
}

export function isBtwHerrekendNotitie(detail: Record<string, unknown>): boolean {
  return BTW_HERREKEND_SLEUTEL in detail && Array.isArray(detail[BTW_HERREKEND_SLEUTEL])
}

function euro(w: unknown): string {
  if (typeof w !== 'string' && typeof w !== 'number') return '—'
  const n = Number(w)
  return Number.isFinite(n) ? `€ ${n.toFixed(2).replace('.', ',')}` : '—'
}

/** "Btw herrekend uit tarief — regel 1: btw € 20,24 → € 0,00 (btw in de kosten: netto € 96,36 → € 116,60)" of, bij een
 * nettowijziging (FV-09, 25-09): "Btw herrekend — regel 1: netto € 96,36 → € 100,00, btw € 20,24 → € 21,00 (netto
 * gewijzigd)". Een notitie mét beide aanleidingen splitst in twee zinnen. */
export function btwHerrekendTijdlijnTekst(detail: Record<string, unknown>): string {
  const regels = detail[BTW_HERREKEND_SLEUTEL] as BtwHerrekendRegel[]
  const nettoRegels = regels.filter((r) => r.aanleiding === 'netto')
  const tariefRegels = regels.filter((r) => r.aanleiding !== 'netto')
  const zinnen: string[] = []
  if (tariefRegels.length > 0) {
    const delen = tariefRegels.map((r) => {
      const basis = `regel ${typeof r.regel === 'number' ? r.regel : '?'}: btw ${euro(r.btw_van)} → ${euro(r.btw_naar)}`
      return r.in_kosten ? `${basis} (btw in de kosten: netto ${euro(r.netto_van)} → ${euro(r.netto_naar)})` : basis
    })
    zinnen.push(`Btw herrekend uit tarief — ${delen.join('; ')}`)
  }
  if (nettoRegels.length > 0) {
    const delen = nettoRegels.map(
      (r) =>
        `regel ${typeof r.regel === 'number' ? r.regel : '?'}: netto ${euro(r.netto_van)} → ${euro(r.netto_naar)}, btw ${euro(r.btw_van)} → ${euro(r.btw_naar)} (netto gewijzigd)`,
    )
    zinnen.push(`Btw herrekend — ${delen.join('; ')}`)
  }
  return zinnen.join(' · ')
}
