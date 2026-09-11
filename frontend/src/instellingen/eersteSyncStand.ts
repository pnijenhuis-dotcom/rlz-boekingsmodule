// Eerste sync ná groene probe: 403 = herproberen (blok 3 run 11-09 middag; bevinding Peter Baard / Box Beheer /
// Kempen B.V.). RLZ zet de rechten van een verse API-koppeling met vertraging door: de backend zet zo'n run op
// `rechten_onderweg` (mét `pogingen` + `volgende_poging_op`) en herprobeert zelf (5, 15, 60 min, daarna elk uur,
// max 24 u). Deze helpers vertalen die stand naar de chip "RLZ zet rechten door — opnieuw over N min" (tooltip =
// het letterlijke RLZ-antwoord); ná 24 u is de run gewoon `fout` en geldt het bestaande sync-fout-pad.
import type { EersteSyncRunDto } from '../api/types'

export const RECHTEN_ONDERWEG = 'rechten_onderweg'

export function isRechtenOnderweg(run: EersteSyncRunDto | null | undefined): boolean {
  return run?.status === RECHTEN_ONDERWEG
}

/** Hele minuten tot `volgende_poging_op` (afgerond naar boven, nooit negatief); null zonder tijdstip. */
export function minutenTotVolgendePoging(run: EersteSyncRunDto | null | undefined, nu: Date = new Date()): number | null {
  if (!run?.volgende_poging_op) return null
  const doel = new Date(run.volgende_poging_op).getTime()
  if (Number.isNaN(doel)) return null
  return Math.max(0, Math.ceil((doel - nu.getTime()) / 60_000))
}

/** Chip-/regeltekst voor een wachtende run. */
export function rechtenOnderwegTekst(run: EersteSyncRunDto | null | undefined, nu: Date = new Date()): string {
  const minuten = minutenTotVolgendePoging(run, nu)
  if (minuten === null) return 'RLZ zet rechten door — wordt opnieuw geprobeerd'
  if (minuten === 0) return 'RLZ zet rechten door — opnieuw zo dadelijk'
  return `RLZ zet rechten door — opnieuw over ${minuten} min`
}

/** Het letterlijke RLZ-antwoord van het eerste wachtende/rode onderdeel (tooltip); terugval = de stand-tekst. */
export function rlzAntwoordVan(run: EersteSyncRunDto | null | undefined): string | null {
  const stand = Object.values(run?.onderdelen ?? {}).find((s) => s.status === RECHTEN_ONDERWEG || s.status === 'fout')
  return stand?.rlz_melding ?? stand?.fout ?? null
}

/** Tooltip van de chip: RLZ-antwoord + poging-teller (bijv. `… · poging 2, volgende om 12:15`). */
export function rechtenOnderwegTooltip(run: EersteSyncRunDto | null | undefined): string {
  const antwoord = rlzAntwoordVan(run)
  const delen: string[] = []
  if (antwoord) delen.push(`RLZ zegt: ${antwoord}`)
  if (run?.pogingen) delen.push(`poging ${run.pogingen}`)
  if (run?.volgende_poging_op) {
    const t = new Date(run.volgende_poging_op)
    if (!Number.isNaN(t.getTime())) delen.push(`volgende poging ${t.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' })}`)
  }
  delen.push('na 24 uur zonder resultaat wordt de sync rood')
  return delen.join(' · ')
}
