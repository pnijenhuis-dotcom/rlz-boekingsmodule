import { apiJson } from '../api/client'
import type {
  AdministratieInstellingenLijstDto,
  BoekenIngeschakeldDto,
  LeverancierAutoboekenDto,
  LeverancierAutoboekenLijstDto,
} from '../api/types'

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

export function haalIntakeAiInstellingOp(): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>('/instellingen/intake-ai')
}

export function zetIntakeAiInstelling(ingeschakeld: boolean): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>('/instellingen/intake-ai', {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

/** AI-kostenmeter (besluit 2026-08-14): verbruik/limiet van de lopende kalendermaand
 * (Europe/Amsterdam). Bedragen als string — Decimal-precisie uit de backend, nooit float. */
export interface AiKostenStatusDto {
  maand: string
  verbruik_eur: string
  limiet_eur: string
  percentage: number
  waarschuwing_80: boolean
  limiet_bereikt: boolean
  geblokkeerd: boolean
}

export function haalAiKostenStatusOp(): Promise<AiKostenStatusDto> {
  return apiJson<AiKostenStatusDto>('/instellingen/ai-kosten')
}

export function zetAiKostenLimiet(maandlimietEur: string): Promise<AiKostenStatusDto> {
  return apiJson<AiKostenStatusDto>('/instellingen/ai-kosten-limiet', {
    ...PUT_JSON,
    body: JSON.stringify({ maandlimiet_eur: maandlimietEur }),
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

/** Autoboeken-opt-in per leverancier (lezen: iedere medewerker binnen de scope). */
export function haalLeveranciersAutoboeken(administratieId: string): Promise<LeverancierAutoboekenLijstDto> {
  return apiJson<LeverancierAutoboekenLijstDto>(`/administraties/${administratieId}/leveranciers-autoboeken`)
}

/** Autoboeken-opt-in zetten (Beheerder-only — backend geeft 403 voor andere rollen). */
export function zetLeverancierAutoboeken(
  administratieId: string,
  vendorId: string,
  ingeschakeld: boolean,
): Promise<LeverancierAutoboekenDto> {
  return apiJson<LeverancierAutoboekenDto>(
    `/administraties/${administratieId}/leveranciers/${vendorId}/autoboeken-instelling`,
    {
      ...PUT_JSON,
      body: JSON.stringify({ ingeschakeld }),
    },
  )
}

export function zetEigenaar(administratieId: string, eigenaarGebruikerId: string | null): Promise<unknown> {
  return apiJson(`/administraties/${administratieId}/eigenaar`, {
    ...PUT_JSON,
    body: JSON.stringify({ eigenaar_gebruiker_id: eigenaarGebruikerId }),
  })
}
