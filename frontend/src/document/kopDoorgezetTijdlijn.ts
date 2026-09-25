/** Tijdlijn-notitie "kop → regels" (FV-07 feedbackrun A 25-09, backend `boekvoorstel.KOP_DOORGEZET_SLEUTEL`): de
 * medewerker koos project en/of btw-code op factuurniveau en die is naar álle regels doorgezet. Pure leeslogica los van
 * React, zelfde patroon als kopOmschrijvingTijdlijn.ts. */

export const KOP_DOORGEZET_SLEUTEL = 'kop_doorgezet'

interface KopDoorgezetNotitie {
  project?: unknown
  btw?: unknown
  project_naam?: unknown
  btw_code?: unknown
}

export function isKopDoorgezetNotitie(detail: Record<string, unknown>): boolean {
  return KOP_DOORGEZET_SLEUTEL in detail && typeof detail[KOP_DOORGEZET_SLEUTEL] === 'object' && detail[KOP_DOORGEZET_SLEUTEL] !== null
}

function regels(n: unknown): string {
  return typeof n === 'number' ? `${n} ${n === 1 ? 'regel' : 'regels'}` : 'alle regels'
}

/** "Kop → regels: project ‹naam› op 3 regels · btw ‹code› op 3 regels". */
export function kopDoorgezetTijdlijnTekst(detail: Record<string, unknown>): string {
  const n = detail[KOP_DOORGEZET_SLEUTEL] as KopDoorgezetNotitie
  const delen: string[] = []
  if (n.project) delen.push(`project ${typeof n.project_naam === 'string' ? `‹${n.project_naam}›` : ''} op ${regels(n.project)}`.replace('  ', ' '))
  if (n.btw) delen.push(`btw ${typeof n.btw_code === 'string' ? `‹${n.btw_code}›` : ''} op ${regels(n.btw)}`.replace('  ', ' '))
  return `Kop → regels: ${delen.join(' · ')}`
}
