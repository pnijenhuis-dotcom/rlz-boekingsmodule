import { apiJson } from '../api/client'
import type { AdministratieInstellingenLijstDto, BoekenIngeschakeldDto } from '../api/types'

/** Alle instellingen-verkeer op één plek (zelfde patroon als vragenApi.ts/ibanAccorderingApi.ts),
 * met absolute, door de dev-proxy gedekte paden — de guard-test instellingenApi.test.ts toetst
 * élk pad hier tegen de proxy-prefixen in vite.config.ts. Aanleiding (browserreview 2026-07-15):
 * '/instellingen/…' ontbrak in de proxy, waardoor Vite's SPA-fallback index.html (status 200)
 * teruggaf en de hele Instellingen-pagina omviel op JSON.parse — een fetch-mock in de
 * componenttest verbergt precies dat soort URL-fouten. */

const PUT_JSON = { method: 'PUT', headers: { 'Content-Type': 'application/json' } }

export function haalInstellingenAdministratiesOp(): Promise<AdministratieInstellingenLijstDto> {
  return apiJson<AdministratieInstellingenLijstDto>('/instellingen/administraties')
}

export function haalBoekenKillSwitchOp(): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>('/instellingen/boeken-kill-switch')
}

export function zetBoekenKillSwitch(ingeschakeld: boolean): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>('/instellingen/boeken-kill-switch', {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

export function zetBoekenInstelling(administratieId: string, ingeschakeld: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/boeken-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

export function zetProjectInstelling(administratieId: string, verplicht: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/project-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ verplicht }),
  })
}

export function zetAiExtractieInstelling(administratieId: string, ingeschakeld: boolean): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/ai-extractie-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

export function zetEigenaar(administratieId: string, eigenaarGebruikerId: string | null): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/eigenaar`, {
    ...PUT_JSON,
    body: JSON.stringify({ eigenaar_gebruiker_id: eigenaarGebruikerId }),
  })
}
