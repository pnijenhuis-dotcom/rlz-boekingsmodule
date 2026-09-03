import { apiJson } from '../api/client'
import type { ArchiefKantoorbreedResponseDto, ArchiefResponseDto, ZoekResponseDto } from '../api/types'

/** Globaal zoeken over boekingen (incl. archief), accorderingshistorie, vragen en audit
 * (mockup #zoeken, backend/app/zoeken/router.py). Het pad staat bewust als los letterlijk
 * '/zoeken' vóór het query-deel: de proxydekking-guard (src/api/proxyDekking.test.ts) toetst
 * het letterlijke pad-argument tegen proxy-prefixes.json en kent geen querystrings. */
export function zoek(term: string): Promise<ZoekResponseDto> {
  return apiJson<ZoekResponseDto>('/zoeken' + `?term=${encodeURIComponent(term)}`)
}

export const ARCHIEF_PER_PAGINA = 25

export interface ArchiefQuery {
  pagina?: number
  perPagina?: number
  /** ISO-datum (JJJJ-MM-DD); leeg = server-default (12 maanden terug resp. vandaag). */
  van?: string
  tot?: string
  q?: string
  /** `<kolom>:<asc|desc>` (documentenlijst-conventie punt 21); leeg = boekmoment nieuwste eerst. */
  sort?: string | null
}

export function archiefParams(query: ArchiefQuery): URLSearchParams {
  const params = new URLSearchParams({ pagina: String(query.pagina ?? 1), per_pagina: String(query.perPagina ?? ARCHIEF_PER_PAGINA) })
  if (query.van) params.set('van', query.van)
  if (query.tot) params.set('tot', query.tot)
  if (query.q) params.set('q', query.q)
  if (query.sort) params.set('sort', query.sort)
  return params
}

/** Geboekte documenten van één administratie (archief, bewaarplicht 7 jaar) — sinds C1 (03-09)
 * gepagineerd mét datumvenster; de klantpagina-deeplink-route. */
export function haalArchiefOp(administratieId: string, query: ArchiefQuery = {}): Promise<ArchiefResponseDto> {
  return apiJson<ArchiefResponseDto>(`/administraties/${administratieId}/archief?${archiefParams(query).toString()}`)
}

/** Kantoorbreed geboekt archief over álle administraties in scope (B4 03-09, mockup
 * inzicht-kantoorbreed.html ⑥): administratie = facet-filter (leeg = alle), nooit poort. Het pad
 * staat als los letterlijk '/archief' vóór het query-deel — zelfde reden als `zoek()` (proxydekking-guard). */
export function haalArchiefKantoorbreedOp(query: ArchiefQuery & { administratieId?: string | null }): Promise<ArchiefKantoorbreedResponseDto> {
  const params = archiefParams(query)
  if (query.administratieId) params.set('administratie_id', query.administratieId)
  return apiJson<ArchiefKantoorbreedResponseDto>('/archief' + `?${params.toString()}`)
}
