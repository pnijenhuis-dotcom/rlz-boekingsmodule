import { apiJson, apiPostJson } from '../api/client'
import type {
  LeverancierProRatoDto,
  ProjectverdelingDto,
  ProjectverdelingHerverdeelResultaatDto,
  ProjectverdelingInputDto,
  ProjectverdelingInstellingenDto,
  ProjectverdelingSignaalLijstDto,
} from '../api/types'

/** Alle projectverdeling-verkeer op één plek (blok C 04-09; zelfde patroon als doorbelastingApi.ts). De
 * proxy-dekking-guard (api/proxyDekking.test.ts) toetst élk pad hier tegen frontend/proxy-prefixes.json
 * (`/administraties` + `/projectverdeling`). */

const PUT_JSON = { method: 'PUT', headers: { 'Content-Type': 'application/json' } }

export function haalProjectverdelingOp(administratieId: string, documentId: string): Promise<ProjectverdelingDto> {
  return apiJson<ProjectverdelingDto>(`/administraties/${administratieId}/documenten/${documentId}/projectverdeling`)
}

export function slaProjectverdelingOp(
  administratieId: string,
  documentId: string,
  invoer: ProjectverdelingInputDto,
): Promise<ProjectverdelingDto> {
  return apiJson<ProjectverdelingDto>(`/administraties/${administratieId}/documenten/${documentId}/projectverdeling`, {
    ...PUT_JSON,
    body: JSON.stringify(invoer),
  })
}

export function herverdeelProjectverdeling(
  administratieId: string,
  documentId: string,
  reden: string,
): Promise<ProjectverdelingHerverdeelResultaatDto> {
  return apiPostJson<ProjectverdelingHerverdeelResultaatDto>(
    `/administraties/${administratieId}/documenten/${documentId}/projectverdeling/herverdelen`,
    { reden },
  )
}

export function haalLeveranciersProRato(administratieId: string): Promise<{ leveranciers: LeverancierProRatoDto[] }> {
  return apiJson(`/administraties/${administratieId}/leveranciers-projectverdeling`)
}

export function zetLeverancierProRato(
  administratieId: string,
  vendorId: string,
  ingeschakeld: boolean,
): Promise<LeverancierProRatoDto> {
  return apiJson<LeverancierProRatoDto>(
    `/administraties/${administratieId}/leveranciers/${vendorId}/projectverdeling-instelling`,
    { ...PUT_JSON, body: JSON.stringify({ ingeschakeld }) },
  )
}

export function haalProjectverdelingInstellingenOp(administratieId: string): Promise<ProjectverdelingInstellingenDto> {
  return apiJson<ProjectverdelingInstellingenDto>(`/administraties/${administratieId}/projectverdeling-instellingen`)
}

export function zetProjectverdelingInstellingen(
  administratieId: string,
  invoer: { drempel_pct?: string; wachtweken?: number },
): Promise<ProjectverdelingInstellingenDto> {
  return apiJson<ProjectverdelingInstellingenDto>(`/administraties/${administratieId}/projectverdeling-instellingen`, {
    ...PUT_JSON,
    body: JSON.stringify(invoer),
  })
}

export function haalHercontroleSignalenOp(pagina = 1): Promise<ProjectverdelingSignaalLijstDto> {
  return apiJson<ProjectverdelingSignaalLijstDto>(`/projectverdeling/hercontrole-signalen?pagina=${pagina}`)
}

/** Lege omzetstand = actie (UX-norm): de bestaande projectcijfers-sync van de administratie starten. */
export function startProjectcijfersSync(administratieId: string): Promise<unknown> {
  return apiPostJson(`/projecten/${administratieId}/cijfers-sync`, {})
}
