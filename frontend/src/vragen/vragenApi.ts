import { apiJson, apiPostJson } from '../api/client'
import type { EigenaarDto, MedewerkersLijstDto, VraagDto, VraagLijstDto } from '../api/types'

/** Dunne wrappers rond de PART A-endpoints (backend/app/documenten/vragen.py + beheer): alle
 * vraag-verkeer op één plek, zodat schermen en tests dezelfde routes delen. */

export function haalVragenOp(
  administratieId: string,
  opties: { status?: 'open' | 'beantwoord' | 'ingetrokken'; documentId?: string } = {},
): Promise<VraagLijstDto> {
  const params = new URLSearchParams()
  if (opties.status) params.set('vraag_status', opties.status)
  if (opties.documentId) params.set('document_id', opties.documentId)
  const query = params.toString()
  return apiJson<VraagLijstDto>(`/administraties/${administratieId}/vragen${query ? `?${query}` : ''}`)
}

export function stelVraag(
  administratieId: string,
  documentId: string,
  invoer: { vraag_tekst: string; toegewezen_aan: string | null },
): Promise<VraagDto> {
  return apiPostJson<VraagDto>(`/administraties/${administratieId}/documenten/${documentId}/vraag`, invoer)
}

export function beantwoordVraag(administratieId: string, vraagId: string, antwoordTekst: string): Promise<VraagDto> {
  return apiPostJson<VraagDto>(`/administraties/${administratieId}/vragen/${vraagId}/beantwoorden`, {
    antwoord_tekst: antwoordTekst,
  })
}

export function trekVraagIn(administratieId: string, vraagId: string, reden: string | null): Promise<VraagDto> {
  return apiPostJson<VraagDto>(`/administraties/${administratieId}/vragen/${vraagId}/intrekken`, { reden })
}

export function haalMedewerkersOp(administratieId: string): Promise<MedewerkersLijstDto> {
  return apiJson<MedewerkersLijstDto>(`/administraties/${administratieId}/medewerkers`)
}

export function haalEigenaarOp(administratieId: string): Promise<EigenaarDto> {
  return apiJson<EigenaarDto>(`/administraties/${administratieId}/eigenaar`)
}
