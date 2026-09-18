/** Tijdlijn-notitie "route" bij het aanbieden ter accordering (Peter 18-09, migratie 0164 — backend
 * `accordering.service.bied_ter_accordering_aan` schrijft `route_omschrijving` in het overgangsdetail zodra een
 * leveranciersroute gold): "route: gewoon + extra laag Sophia ná de laatste laag (leveranciersroute Route Q)" of
 * "route: leveranciersroute Route Q". Pure leeslogica los van React (patroon accorderingOvergeslagenTijdlijn.ts). */

export const ROUTE_OMSCHRIJVING_SLEUTEL = 'route_omschrijving'

export function isAccorderingRouteNotitie(detail: Record<string, unknown>): boolean {
  const d = detail[ROUTE_OMSCHRIJVING_SLEUTEL]
  return typeof d === 'string' && d.trim().length > 0
}

export function accorderingRouteTijdlijnTekst(detail: Record<string, unknown>): string {
  const tekst = String(detail[ROUTE_OMSCHRIJVING_SLEUTEL] ?? '').trim()
  // Eerste letter hoofdletter voor de tijdlijnregel; de rest letterlijk zoals de server 'm formuleerde.
  return tekst.charAt(0).toUpperCase() + tekst.slice(1)
}
