import { apiJson, apiPostJson } from '../api/client'
import type {
  VerkoopBoekenResponseDto,
  VerkoopVoorstelDto,
  VerkoopVoorstelInputDto,
  VerkoopVoorstelMetChecksDto,
} from '../api/types'

export function haalVerkoopVoorstelOp(administratieId: string, documentId: string): Promise<VerkoopVoorstelDto> {
  return apiJson<VerkoopVoorstelDto>(`/administraties/${administratieId}/verkoop/documenten/${documentId}/voorstel`)
}

export function slaVerkoopVoorstelOp(
  administratieId: string,
  documentId: string,
  invoer: VerkoopVoorstelInputDto,
): Promise<VerkoopVoorstelDto> {
  return apiJson<VerkoopVoorstelDto>(`/administraties/${administratieId}/verkoop/documenten/${documentId}/voorstel`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(invoer),
  })
}

export function voerVerkoopChecksUit(
  administratieId: string,
  documentId: string,
): Promise<VerkoopVoorstelMetChecksDto> {
  return apiPostJson<VerkoopVoorstelMetChecksDto>(
    `/administraties/${administratieId}/verkoop/documenten/${documentId}/checks`,
    {},
  )
}

export function boekVerkoop(administratieId: string, documentId: string): Promise<VerkoopBoekenResponseDto> {
  return apiPostJson<VerkoopBoekenResponseDto>(
    `/administraties/${administratieId}/verkoop/documenten/${documentId}/boeken`,
    {},
  )
}
