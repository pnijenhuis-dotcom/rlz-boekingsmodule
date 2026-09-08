/** Tijdlijn-notitie "klant-accordering overgeslagen" (blok 4 bundel 08-09, backend
 * `accordering.service.registreer_accordering_overgeslagen`): de leverancier draagt in deze administratie de
 * intercompany-vlag, dus het document ging niet naar de klant-accordeur maar direct de boekstap in. Pure leeslogica
 * los van React (zelfde patroon als prefillAutosaveTijdlijn.ts) zodat de tekst direct unit-testbaar is. */

export const ACCORDERING_OVERGESLAGEN_SLEUTEL = 'accordering_overgeslagen'

interface OvergeslagenDetail {
  reden?: unknown
  leverancier_naam?: unknown
  vendor_id?: unknown
}

export function isAccorderingOvergeslagenNotitie(detail: Record<string, unknown>): boolean {
  const d = detail[ACCORDERING_OVERGESLAGEN_SLEUTEL]
  return typeof d === 'object' && d !== null
}

/** "Intercompany — klant-accordering overgeslagen (leveranciersregel): Universal Nederland B.V." */
export function accorderingOvergeslagenTijdlijnTekst(detail: Record<string, unknown>): string {
  const d = detail[ACCORDERING_OVERGESLAGEN_SLEUTEL] as OvergeslagenDetail
  const reden = typeof d.reden === 'string' && d.reden ? d.reden : 'leveranciersregel'
  const redenLabel = reden === 'intercompany' ? 'Intercompany' : reden
  const naam = typeof d.leverancier_naam === 'string' && d.leverancier_naam ? d.leverancier_naam : null
  const vendor = typeof d.vendor_id === 'string' && d.vendor_id ? d.vendor_id : null
  const wie = naam ?? vendor
  return `${redenLabel} — klant-accordering overgeslagen (leveranciersregel)${wie ? `: ${wie}` : ''}`
}
