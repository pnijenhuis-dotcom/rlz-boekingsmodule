import { apiJson, apiPostJson } from '../api/client'
import type {
  EigenaarDto,
  MedewerkersLijstDto,
  OpenVragenLijstDto,
  OpenVragenTellersDto,
  VraagDto,
  VraagLijstDto,
} from '../api/types'

/** Dunne wrappers rond de PART A-endpoints (backend/app/documenten/vragen.py + beheer): alle
 * vraag-verkeer op één plek, zodat schermen en tests dezelfde routes delen. */

export function haalVragenOp(
  administratieId: string,
  opties: { status?: 'open' | 'beantwoord' | 'ingetrokken' | 'afgehandeld'; documentId?: string } = {},
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

/** Bijdrage in de dialoog (besluit Peter 25-08): de vraag blijft open, "aan de beurt" wisselt. */
export function plaatsBericht(administratieId: string, vraagId: string, tekst: string): Promise<VraagDto> {
  return apiPostJson<VraagDto>(`/administraties/${administratieId}/vragen/${vraagId}/berichten`, { tekst })
}

/** "Afgehandeld" — uitsluitend de vraagsteller (server: 403 voor ieder ander); optioneel slotbericht. */
export function handelVraagAf(administratieId: string, vraagId: string, slotbericht: string | null): Promise<VraagDto> {
  return apiPostJson<VraagDto>(`/administraties/${administratieId}/vragen/${vraagId}/afhandelen`, { slotbericht })
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

/** Kantoorbreed (design-ronde 03-09 blok B2, mockup inzicht-kantoorbreed.html ④): één server-side lijst
 * over álle administraties in scope — vervangt de N+1-fan-out per administratie. Filters zijn filters op de
 * scope-set (administratie leeg = alle), paginering 25, oudste eerst. */
export type OpenVragenToegewezen = 'alle' | 'mij'

export interface OpenVragenFilters {
  pagina?: number
  administratieId?: string | null
  toegewezen?: OpenVragenToegewezen
  ouderDanDagen?: number | null
  q?: string
}

export function openVragenQuery(filters: OpenVragenFilters): string {
  const params = new URLSearchParams({ pagina: String(filters.pagina ?? 1) })
  if (filters.administratieId) params.set('administratie_id', filters.administratieId)
  if (filters.toegewezen && filters.toegewezen !== 'alle') params.set('toegewezen', filters.toegewezen)
  if (filters.ouderDanDagen != null) params.set('ouder_dan_dagen', String(filters.ouderDanDagen))
  if (filters.q?.trim()) params.set('q', filters.q.trim())
  return params.toString()
}

export function haalOpenVragenKantoorbreedOp(filters: OpenVragenFilters = {}): Promise<OpenVragenLijstDto> {
  // Literal-prefix `/vragen` vóór de interpolatie: de proxy-dekkingstest (proxyDekking.test.ts) leest het pad tot `${`.
  const query = openVragenQuery(filters)
  return apiJson<OpenVragenLijstDto>(`/vragen${query ? `?${query}` : ''}`)
}

/** Lichte stand voor de KPI-kaart "Open vragen" — zelfde definitie als de lijst (B2.3). */
export function haalOpenVragenStandOp(): Promise<OpenVragenTellersDto> {
  return apiJson<OpenVragenTellersDto>('/vragen/stand')
}
