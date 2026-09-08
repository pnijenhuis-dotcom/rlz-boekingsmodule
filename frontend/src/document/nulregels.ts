/** Tariefstaffel-regels in het AI-veldvoorstel (blok 4 bundel 08-09, casus Spot Services 2026-608): de leverancier
 * drukt zijn tariefkaart mee (aantal 0, bedrag 0, btw 0) — als BRON bewaard, als boekingsregel ruis. De server markeert
 * élke gelezen regel (`tariefstaffel`, backend/app/documenten/veldvoorstel_regels.py) en filtert ze uit de
 * server-prefill; déze spiegel filtert ze uit de client-side splitsing uit het veldvoorstel (splitsen ná een
 * samengevoegde opslag) en houdt de AI-zekerheidsscores per regel uitgelijnd. Oudere veldvoorstellen zonder vlag
 * krijgen hetzelfde predicaat. Negatieve regels (korting/credit) blijven. */

import type { AiRegelVoorstel, AiVoorstel } from './aiVoorstel'

function getal(waarde: string | null | undefined): number | null {
  if (waarde == null) return null
  let tekst = String(waarde).trim().replace(/\s/g, '')
  if (!tekst) return null
  if (tekst.includes(',')) tekst = tekst.replace(/\./g, '').replace(',', '.')
  const n = Number(tekst)
  return Number.isFinite(n) ? n : null
}

function hoeveelheid(waarde: string | null | undefined): number | null {
  if (waarde == null) return null
  const kop = String(waarde).trim().match(/^[-\d.,]+/)
  return kop ? getal(kop[0]) : null
}

export function isTariefstaffelRegel(regel: AiRegelVoorstel): boolean {
  if (typeof regel.tariefstaffel === 'boolean') return regel.tariefstaffel
  const netto = getal(regel.netto_bedrag)
  if (netto === null || netto !== 0) return false
  const btw = getal(regel.btw_bedrag)
  if (btw !== null && btw !== 0) return false
  const aantal = hoeveelheid(regel.hoeveelheid)
  return aantal === null || aantal === 0
}

export interface BoekbareAiRegel {
  regel: AiRegelVoorstel
  /** AI-zekerheid van déze regel (index-uitgelijnd op de volledige regelset van het veldvoorstel). */
  zekerheid: number | null
}

/** De regels die een boekingsregel worden, mét hun zekerheid. Louter nulregels = alles blijft staan (nooit stil leeg). */
export function boekbareAiRegels(ai: AiVoorstel): BoekbareAiRegel[] {
  const alle = ai.regels.map((regel, i) => ({ regel, zekerheid: ai.regel_zekerheid[i] ?? null }))
  const boekbaar = alle.filter((x) => !isTariefstaffelRegel(x.regel))
  return boekbaar.length > 0 ? boekbaar : alle
}

/** Aantal weggelaten tariefstaffel-regels (voor de uitlegregel "N tariefregels zonder bedrag weggelaten"). */
export function aantalTariefstaffels(ai: AiVoorstel): number {
  return ai.regels.length - boekbareAiRegels(ai).length
}
