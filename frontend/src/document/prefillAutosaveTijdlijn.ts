/** Tijdlijn-notitie van de prefill-autosave bij het openen (blok A10 07-09, backend
 * `boekvoorstel.persisteer_prefill_bij_openen`): het voorstel uit geheugen/template/default is server-side
 * opgeslagen zodat checks en doorbelasten-blok zien wat de mens ziet. Pure leeslogica los van React
 * (zelfde patroon als materiaal/miniVoorraadTijdlijn.ts) zodat de tekst direct unit-testbaar is. */

export const PREFILL_AUTOSAVE_SLEUTEL = 'boekvoorstel_prefill'

interface PrefillSnapshot {
  triggers?: unknown
  regels?: unknown
  veldvoorstel_bron?: unknown
}

export function isPrefillAutosaveNotitie(detail: Record<string, unknown>): boolean {
  return PREFILL_AUTOSAVE_SLEUTEL in detail && typeof detail[PREFILL_AUTOSAVE_SLEUTEL] === 'object' && detail[PREFILL_AUTOSAVE_SLEUTEL] !== null
}

const BRON_LABEL: Record<string, string> = {
  geheugen: 'regel-geheugen',
  geheugen_seed: 'historie (nog niet bevestigd)',
  geheugen_conflict: 'regel-geheugen (wisselend)',
  leverancier_geheugen: 'leverancier-geheugen',
  standaard: 'standaard btw van de administratie',
  template: 'leverancier-template',
}

/** "Voorstel automatisch vooringevuld uit leverancier-geheugen en standaard btw — 2 regels opgeslagen". */
export function prefillAutosaveTijdlijnTekst(detail: Record<string, unknown>): string {
  const snapshot = detail[PREFILL_AUTOSAVE_SLEUTEL] as PrefillSnapshot
  const triggers = Array.isArray(snapshot.triggers) ? snapshot.triggers.filter((t): t is string => typeof t === 'string') : []
  const bronnen = new Set<string>()
  for (const trigger of triggers) {
    const bron = trigger.split(':').pop()?.trim() ?? ''
    if (bron in BRON_LABEL) bronnen.add(BRON_LABEL[bron])
  }
  const aantal = Array.isArray(snapshot.regels) ? snapshot.regels.length : 0
  const uit = bronnen.size > 0 ? ` uit ${[...bronnen].join(' en ')}` : ''
  const regels = aantal === 1 ? '1 regel' : `${aantal} regels`
  return `Voorstel automatisch vooringevuld${uit} — ${regels} opgeslagen; controleer en pas aan waar nodig`
}
