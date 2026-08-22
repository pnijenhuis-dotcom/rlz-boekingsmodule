// Datalaag tegenboek-pad (mockup tegenboek-mockup.html, akkoord Peter 22-08) — spiegelt
// backend/app/documenten/schemas.py (tegenboek-sectie). Bedragen als string (Decimal),
// nooit berekend in de client.

import { apiJson, apiPostJson } from '../api/client'
import type { TegenboekenResponseDto, TegenboekToetsDto } from '../api/types'

export function haalTegenboekToetsOp(administratieId: string, documentId: string): Promise<TegenboekToetsDto> {
  return apiJson(`/administraties/${administratieId}/documenten/${documentId}/tegenboek-toets`)
}

export function voerTegenboekingUit(
  administratieId: string,
  documentId: string,
  payload: { soort: 'volledig' | 'vervang'; reden: string },
): Promise<TegenboekenResponseDto> {
  return apiPostJson(`/administraties/${administratieId}/documenten/${documentId}/tegenboeken`, payload)
}
