import { apiJson } from '../api/client'
import type { ArchiefResponseDto, ZoekResponseDto } from '../api/types'

/** Globaal zoeken over boekingen (incl. archief), accorderingshistorie, vragen en audit
 * (mockup #zoeken, backend/app/zoeken/router.py). Het pad staat bewust als los letterlijk
 * '/zoeken' vóór het query-deel: de proxydekking-guard (src/api/proxyDekking.test.ts) toetst
 * het letterlijke pad-argument tegen proxy-prefixes.json en kent geen querystrings. */
export function zoek(term: string): Promise<ZoekResponseDto> {
  return apiJson<ZoekResponseDto>('/zoeken' + `?term=${encodeURIComponent(term)}`)
}

/** Geboekte documenten van één administratie (archief, bewaarplicht 7 jaar). */
export function haalArchiefOp(administratieId: string): Promise<ArchiefResponseDto> {
  return apiJson<ArchiefResponseDto>(`/administraties/${administratieId}/archief`)
}
