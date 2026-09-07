/** Tijdlijn-notitie van de kop-omschrijving (blok 9 vervolgrun 07-09, backend
 * `boekvoorstel._verwerk_kop_omschrijving`): een medewerker zette de omschrijving met de hand (override — wint
 * voortaan) of maakte het veld leeg (terug naar automatisch). Pure leeslogica los van React, zelfde patroon als
 * prefillAutosaveTijdlijn.ts. */

export const KOP_OMSCHRIJVING_SLEUTEL = 'kop_omschrijving'

interface KopOmschrijvingNotitie {
  tekst?: unknown
  herkomst?: unknown
  afgeleid?: unknown
}

export function isKopOmschrijvingNotitie(detail: Record<string, unknown>): boolean {
  return (
    KOP_OMSCHRIJVING_SLEUTEL in detail &&
    typeof detail[KOP_OMSCHRIJVING_SLEUTEL] === 'object' &&
    detail[KOP_OMSCHRIJVING_SLEUTEL] !== null
  )
}

/** "Omschrijving handmatig gezet: ‹tekst› (automatisch was: ‹afgeleid›)" of
 * "Omschrijving terug naar automatisch: ‹afgeleid›". */
export function kopOmschrijvingTijdlijnTekst(detail: Record<string, unknown>): string {
  const notitie = detail[KOP_OMSCHRIJVING_SLEUTEL] as KopOmschrijvingNotitie
  const tekst = typeof notitie.tekst === 'string' && notitie.tekst ? notitie.tekst : null
  const afgeleid = typeof notitie.afgeleid === 'string' && notitie.afgeleid ? notitie.afgeleid : null
  if (tekst) {
    return `Omschrijving handmatig gezet: "${tekst}"${afgeleid ? ` (automatisch was: "${afgeleid}")` : ''}`
  }
  return `Omschrijving terug naar automatisch${afgeleid ? `: "${afgeleid}"` : ''}`
}
