import { apiJson, apiPostJson } from '../api/client'
import type {
  OmzetBoekenResponseDto,
  OmzetBronInstellingenDto,
  OmzetBronInstellingenWaarden,
  OmzetVoorstelDto,
  OmzetVoorstelInputDto,
  OmzetVoorstelMetChecksDto,
  TochInkoopfactuurResponseDto,
  VerkoopCategorieDto,
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

/** Peter 16-09 (Van Boxtel): de medewerker kiest de RLZ-categorie (uit de gesynchroniseerde keuzelijst) — mens wint
 * voor dit document én wordt de default van de administratie (audit oud→nieuw, tijdlijn). */
export function zetVerkoopCategorie(
  administratieId: string,
  categorieId: string,
  documentId: string | null,
): Promise<VerkoopCategorieDto> {
  return apiJson<VerkoopCategorieDto>(`/administraties/${administratieId}/omzet/verkoop-categorie`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ categorie_id: categorieId, document_id: documentId }),
  })
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

/** Terugweg (Peter 19-09): automatisch getypeerd kassarapport is tóch een inkoopfactuur — verplichte reden. */
export function tochInkoopfactuur(
  administratieId: string,
  documentId: string,
  reden: string,
): Promise<TochInkoopfactuurResponseDto> {
  return apiPostJson<TochInkoopfactuurResponseDto>(
    `/administraties/${administratieId}/omzet/documenten/${documentId}/toch-inkoopfactuur`,
    { reden },
  )
}
