/** Tijdlijn-notitie "automatisch geboekt zonder AI-toets" (blok 4 vervolgrun 10-09 avond, besluit Peter 10-09; backend
 * `documenten/autoboeken.py` zet `zonder_ai_toets` + `ai_toets_oorzaak` in het GEBOEKT-overgang-detail): de
 * AI-plausibiliteitstoets viel technisch uit (AVG-gate uit, geen API-key, kostengrens bereikt, AI-fout/timeout) en de
 * automatische boeking liep door omdat de deterministische controles groen waren. Pure leeslogica los van React (zelfde
 * patroon als accorderingOvergeslagenTijdlijn.ts) zodat de tekst direct unit-testbaar is. */

import { aiToetsOorzaakLabel } from '../bank/VoorstelKaart'

export const ZONDER_AI_TOETS_SLEUTEL = 'zonder_ai_toets'

export function isZonderAiToetsNotitie(detail: Record<string, unknown>): boolean {
  return detail[ZONDER_AI_TOETS_SLEUTEL] === true
}

/** Blok 3.2 vervolgrun 10-09 avond: de toets stond platformbreed UIT (bewuste opt-out) — GEBOEKT-detail `ai_toets_uit`. */
export const AI_TOETS_UIT_SLEUTEL = 'ai_toets_uit'

export function isAiToetsUitNotitie(detail: Record<string, unknown>): boolean {
  return detail[AI_TOETS_UIT_SLEUTEL] === true
}

/** "Automatisch geboekt met de AI-toets platformbreed uit (Instellingen › Boeken) — alleen de vaste controles liepen." */
export function aiToetsUitTijdlijnTekst(): string {
  return 'Automatisch geboekt met de AI-toets platformbreed uit (Instellingen › Boeken) — alleen de vaste controles liepen.'
}

/** "Automatisch geboekt zónder AI-toets — de toets viel technisch uit (AI staat uit (AVG-gate)); controleer steekproefsgewijs." */
export function zonderAiToetsTijdlijnTekst(detail: Record<string, unknown>): string {
  const oorzaak = typeof detail.ai_toets_oorzaak === 'string' ? detail.ai_toets_oorzaak : null
  return `Automatisch geboekt zónder AI-toets — de toets viel technisch uit (${aiToetsOorzaakLabel(oorzaak)}); controleer steekproefsgewijs.`
}
