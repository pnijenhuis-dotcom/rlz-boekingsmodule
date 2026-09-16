import { apiJson, apiPostJson } from '../api/client'
import type {
  OmzetBoekenResponseDto,
  OmzetBronInstellingenDto,
  OmzetBronInstellingenWaarden,
  OmzetVoorstelDto,
  OmzetVoorstelInputDto,
  OmzetVoorstelMetChecksDto,
} from '../api/types'

export function haalOmzetVoorstelOp(administratieId: string, documentId: string): Promise<OmzetVoorstelDto> {
  return apiJson<OmzetVoorstelDto>(`/administraties/${administratieId}/omzet/documenten/${documentId}/voorstel`)
}

export function slaOmzetVoorstelOp(
  administratieId: string,
  documentId: string,
  invoer: OmzetVoorstelInputDto,
): Promise<OmzetVoorstelDto> {
  return apiJson<OmzetVoorstelDto>(`/administraties/${administratieId}/omzet/documenten/${documentId}/voorstel`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(invoer),
  })
}

export function voerOmzetChecksUit(
  administratieId: string,
  documentId: string,
): Promise<OmzetVoorstelMetChecksDto> {
  return apiPostJson<OmzetVoorstelMetChecksDto>(
    `/administraties/${administratieId}/omzet/documenten/${documentId}/checks`,
    {},
  )
}

export function boekOmzet(administratieId: string, documentId: string): Promise<OmzetBoekenResponseDto> {
  return apiPostJson<OmzetBoekenResponseDto>(
    `/administraties/${administratieId}/omzet/documenten/${documentId}/boeken`,
    {},
  )
}

/** Omzetbronnen (Peter 15/16-09): Beheerder-instellingen per administratie — stores, tegenrekeningen per betaalwijze,
 * categorie-mapping + btw, combi-regel, PSP. GET voor iedereen mét scope, PUT Beheerder-only (audit oud→nieuw). */
export function haalOmzetBronInstellingenOp(administratieId: string): Promise<OmzetBronInstellingenDto> {
  return apiJson<OmzetBronInstellingenDto>(`/administraties/${administratieId}/omzet/bron-instellingen`)
}

export function zetOmzetBronInstellingen(
  administratieId: string,
  waarden: OmzetBronInstellingenWaarden,
): Promise<OmzetBronInstellingenDto> {
  return apiJson<OmzetBronInstellingenDto>(`/administraties/${administratieId}/omzet/bron-instellingen`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(waarden),
  })
}
