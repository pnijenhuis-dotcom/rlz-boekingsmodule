import { apiPostJson } from '../api/client'
import type { DocumentVerplaatsResponseDto } from '../api/types'

/** "Verplaats naar andere administratie…" (addendum kantoor-run 27-08 punt 5, herstel foute
 * toewijzing). Statuslijst = spiegel van app/documenten/verplaatsen.py::VERPLAATSBARE_STATUSSEN —
 * de backend blijft de waarheid (409 mét uitleg); de UI legt vooraf uit waarom het niet kan. */
export const VERPLAATS_STATUSSEN = new Set([
  'te_controleren',
  'handmatig_afmaken',
  'klaar_om_te_boeken',
  'vraag_open',
  'afgewezen',
])

/** null = verplaatsen mag; anders de uitleg (zelfde strekking als de server-409). */
export function redenNietVerplaatsbaar(status: string, soort: string): string | null {
  if (soort !== 'inkoopfactuur') return 'Alleen inkoopfacturen kunnen verplaatst worden.'
  if (VERPLAATS_STATUSSEN.has(status)) return null
  switch (status) {
    case 'geboekt':
      return 'Geboekt — draai de boeking eerst terug (storno in RLZ of "Tegenboeken…"), daarna kan het document verplaatst worden.'
    case 'ter_accordering':
      return 'Ligt bij de klant ter accordering — trek de accordering eerst in.'
    case 'wacht_op_iban_accordering':
      return 'Er loopt een IBAN-accordering — rond die eerst af.'
    case 'boeken_mislukt':
      return 'Laatste boekpoging mislukt — herstel eerst naar "te controleren".'
    case 'ontvangen':
    case 'extractie_wachtrij':
    case 'extractie_bezig':
      return 'De extractie loopt nog — wacht tot het document te controleren is.'
    case 'niet_toegewezen':
      return 'Staat in de verzamelbak — wijs het dáár toe.'
    case 'verwijderd':
      return 'Verwijderd — herstel het document eerst.'
    case 'gesplitst':
      return 'Gesplitst brondocument — verplaats de losse delen.'
    default:
      return `Verplaatsen is niet mogelijk vanuit status ${status}.`
  }
}

export function verplaatsDocument(
  administratieId: string,
  documentId: string,
  doelAdministratieId: string,
): Promise<DocumentVerplaatsResponseDto> {
  return apiPostJson<DocumentVerplaatsResponseDto>(`/administraties/${administratieId}/documenten/${documentId}/verplaats`, {
    doel_administratie_id: doelAdministratieId,
  })
}
