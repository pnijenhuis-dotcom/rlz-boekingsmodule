import { apiJson, apiPostJson } from '../api/client'
import type { CheckRapportDto, WaarborgVoorstelDto } from '../api/types'

export function haalWaarborgVoorstelOp(administratieId: string, documentId: string): Promise<WaarborgVoorstelDto> {
  return apiJson<WaarborgVoorstelDto>(
    `/administraties/${administratieId}/waarborg/documenten/${documentId}/voorstel`,
  )
}

export function slaWaarborgTegenrekeningOp(
  administratieId: string,
  documentId: string,
  tegenrekeningLedgerId: string | null,
): Promise<WaarborgVoorstelDto> {
  return apiJson<WaarborgVoorstelDto>(
    `/administraties/${administratieId}/waarborg/documenten/${documentId}/tegenrekening`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tegenrekening_ledger_id: tegenrekeningLedgerId }),
    },
  )
}

export function voerWaarborgChecksUit(administratieId: string, documentId: string): Promise<CheckRapportDto> {
  return apiPostJson<CheckRapportDto>(
    `/administraties/${administratieId}/waarborg/documenten/${documentId}/checks`,
    {},
  )
}
