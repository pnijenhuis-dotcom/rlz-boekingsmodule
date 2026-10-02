/** Tijdlijn-notitie "Verdelen over projecten" (punt 5 "Boeken prettig 1" 02-10, backend
 * `boekvoorstel.VERDELEN_LEEGGEMAAKT_SLEUTEL`): de medewerker klikte "Verdelen over projecten" terwijl regels al een
 * project droegen — die projecten zijn leeggemaakt en het hele bedrag loopt via de projectverdeling. Pure leeslogica
 * los van React, zelfde patroon als kopDoorgezetTijdlijn.ts. */

export const VERDELEN_LEEGGEMAAKT_SLEUTEL = 'verdelen_leeggemaakt'

interface VerdelenLeeggemaaktNotitie {
  regels?: unknown
  sleutel?: unknown
}

export function isVerdelenLeeggemaaktNotitie(detail: Record<string, unknown>): boolean {
  return (
    VERDELEN_LEEGGEMAAKT_SLEUTEL in detail &&
    typeof detail[VERDELEN_LEEGGEMAAKT_SLEUTEL] === 'object' &&
    detail[VERDELEN_LEEGGEMAAKT_SLEUTEL] !== null
  )
}

const SLEUTEL_TEKST: Record<string, string> = {
  omzet_maand: 'pro rato omzet (maand van de factuurdatum)',
  omzet_jaar: 'pro rato omzet (heel jaar)',
  vaste_regels: 'vaste regels per project',
}

/** "Verdelen over projecten: project van 2 regels leeggemaakt — het hele bedrag verdeeld via pro rato omzet (…)". */
export function verdelenLeeggemaaktTijdlijnTekst(detail: Record<string, unknown>): string {
  const n = detail[VERDELEN_LEEGGEMAAKT_SLEUTEL] as VerdelenLeeggemaaktNotitie
  const aantal = typeof n.regels === 'number' ? `${n.regels} ${n.regels === 1 ? 'regel' : 'regels'}` : 'de regels'
  const sleutel = typeof n.sleutel === 'string' ? SLEUTEL_TEKST[n.sleutel] ?? n.sleutel : null
  return `Verdelen over projecten: project van ${aantal} leeggemaakt — het hele bedrag verdeeld via de projectverdeling${
    sleutel ? ` (${sleutel})` : ''
  }`
}
