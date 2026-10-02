// Punt 10 run A (Peter 02-10): DE ENE bron voor "open dit project" en "open deze meerwerkbon" — patroon van
// `werkvoorraad/format.ts::documentPad` (23-09). Nooit letterlijke `/projecten/${…}`-links elders (guard
// `projectPad.guard.test.ts`); API-paden leven in `projectenApi.ts`.

/** Kantoor-projectpagina (Inzicht › Projecten › project). `meerwerkId` = "ik kom van een meerwerkbon" → de pagina toont
 * een terugweg naar die bon. */
export function projectPad(administratieId: string, projectId: string, opties: { meerwerkId?: string } = {}): string {
  const basis = `/projecten/${administratieId}/${projectId}`
  return opties.meerwerkId ? `${basis}?meerwerk=${encodeURIComponent(opties.meerwerkId)}` : basis
}

export function projectResultaatPad(administratieId: string, projectId: string): string {
  return `/projecten/${administratieId}/${projectId}/resultaat`
}

/** De meerwerkbon = het beoordeel-zijpaneel op Beoordelen › Meerwerk (`?meerwerk=<id>` opent 'm direct). */
export function meerwerkBonPad(administratieId: string, meerwerkId: string): string {
  return `/meerwerk?administratie=${administratieId}&tab=meerwerk&meerwerk=${encodeURIComponent(meerwerkId)}`
}
