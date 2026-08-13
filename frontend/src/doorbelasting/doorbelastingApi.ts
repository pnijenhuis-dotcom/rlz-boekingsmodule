import { ApiError, apiFetch, apiJson, apiPostJson } from '../api/client'
import type {
  BoekenIngeschakeldDto,
  DoorbelastingBoekResultaatDto,
  DoorbelastingInstellingDto,
  DoorbelastingInstellingInputDto,
  DoorbelastingMappingDto,
  DoorbelastingMappingWijzigingDto,
  DoorbelastingRunDto,
  DoorbelastingVerdeelRegelInputDto,
  SpiegelDoelGbsInputDto,
  SpiegelTaakDto,
} from '../api/types'

/** Alle doorbelasting-verkeer op één plek (zelfde patroon als verkoopApi.ts/instellingenApi.ts),
 * met absolute, door de dev-proxy gedekte paden — de guard-test doorbelastingApi.test.ts toetst
 * élk pad hier tegen de proxy-prefixen (frontend/proxy-prefixes.json bevat `/doorbelasting`). */

const PUT_JSON = { method: 'PUT', headers: { 'Content-Type': 'application/json' } }

/** Toggle per administratie (GET: iedere gescoopte medewerker — bepaalt of de actie
 * "Doorbelasten…" bestaat; PUT: Beheerder-only). */
export function haalDoorbelastingToggleOp(administratieId: string): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>(`/administraties/${administratieId}/doorbelasting-instelling`)
}

export function zetDoorbelastingToggle(
  administratieId: string,
  ingeschakeld: boolean,
): Promise<BoekenIngeschakeldDto> {
  return apiJson<BoekenIngeschakeldDto>(`/administraties/${administratieId}/doorbelasting-instelling`, {
    ...PUT_JSON,
    body: JSON.stringify({ ingeschakeld }),
  })
}

/** Bron-configuratie (provisie-%, vlak btw-tarief, omzet-GB's) — Beheerder-only. */
export function haalDoorbelastingInstellingOp(administratieId: string): Promise<DoorbelastingInstellingDto> {
  return apiJson<DoorbelastingInstellingDto>(`/doorbelasting/${administratieId}/instelling`)
}

export function zetDoorbelastingInstelling(
  administratieId: string,
  invoer: DoorbelastingInstellingInputDto,
): Promise<DoorbelastingInstellingDto> {
  return apiJson<DoorbelastingInstellingDto>(`/doorbelasting/${administratieId}/instelling`, {
    ...PUT_JSON,
    body: JSON.stringify(invoer),
  })
}

/** Mapping-whitelist doelentiteit ↔ customer-GUID (lezen: scope; wijzigen: Beheerder-only). */
export function haalDoorbelastingMappingsOp(administratieId: string): Promise<DoorbelastingMappingDto[]> {
  return apiJson<DoorbelastingMappingDto[]>(`/doorbelasting/${administratieId}/mappings`)
}

export function wijzigDoorbelastingMapping(
  administratieId: string,
  mappingId: string,
  wijziging: DoorbelastingMappingWijzigingDto,
): Promise<DoorbelastingMappingDto> {
  return apiJson<DoorbelastingMappingDto>(`/doorbelasting/${administratieId}/mappings/${mappingId}`, {
    ...PUT_JSON,
    body: JSON.stringify(wijziging),
  })
}

/** Read-only leesroute voor het documentdetail (fix 2026-08-13): de bestaande run van dit
 * document, of null als er (nog) geen is (backend geeft 404) — louter openen van een geboekt
 * document maakt niets aan; de POST hieronder is de expliciete gebruikersactie. */
export async function haalDoorbelastingRunVoorDocumentOp(
  administratieId: string,
  documentId: string,
): Promise<DoorbelastingRunDto | null> {
  try {
    return await apiJson<DoorbelastingRunDto>(`/doorbelasting/${administratieId}/documenten/${documentId}/run`)
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null
    throw err
  }
}

/** Get-or-create: geeft de bestaande niet-gestorneerde run terug of maakt een concept-run aan
 * (backend `start_of_haal_run`) — uitsluitend vanuit de expliciete klik "Doorbelasten…"
 * (het reviewscherm), nooit als leesroute. */
export function startDoorbelastingRun(administratieId: string, documentId: string): Promise<DoorbelastingRunDto> {
  return apiPostJson<DoorbelastingRunDto>(
    `/doorbelasting/${administratieId}/documenten/${documentId}/run`,
    {},
  )
}

export function haalDoorbelastingRunOp(administratieId: string, runId: string): Promise<DoorbelastingRunDto> {
  return apiJson<DoorbelastingRunDto>(`/doorbelasting/${administratieId}/runs/${runId}`)
}

/** Vervangt de verdeling van een concept-run; de server berekent de netto-delen bindend
 * (grootste-rest) en geeft de volledige verse run-staat terug. */
export function slaDoorbelastingVerdelingOp(
  administratieId: string,
  runId: string,
  regels: DoorbelastingVerdeelRegelInputDto[],
): Promise<DoorbelastingRunDto> {
  return apiJson<DoorbelastingRunDto>(`/doorbelasting/${administratieId}/runs/${runId}/verdeling`, {
    ...PUT_JSON,
    body: JSON.stringify({ regels }),
  })
}

/** Boekt de run per doelentiteit. Bewust de rauwe Response (zelfde patroon als verkoop/omzet):
 * BoekenGeblokkeerdDoorChecks (409) stuurt het verse CheckRapport mee in detail.checks — een
 * object dat de generieke apiJson/ApiError-afhandeling niet kan uitpakken. */
export function boekDoorbelastingRun(administratieId: string, runId: string): Promise<Response> {
  return apiFetch(`/doorbelasting/${administratieId}/runs/${runId}/boeken`, { method: 'POST' })
}

/** Open spiegel-taken van een administratie (bron-kant geboekt, doel nog niet onboarded). */
export function haalSpiegelTakenOp(administratieId: string): Promise<SpiegelTaakDto[]> {
  return apiJson<SpiegelTaakDto[]>(`/doorbelasting/${administratieId}/spiegel-taken`)
}

/** GB-toewijzing voor een open spiegel-taak (gaten-scan-fix 2026-08-13): de verdeling is
 * bevroren zodra er geboekt is, maar de doel-kosten-GB's en de provisie-GB zijn juist pas
 * kiesbaar ná onboarding van de doel-administratie — eerst deze PUT, dan spiegel-boeken. */
export function zetSpiegelDoelGbs(
  administratieId: string,
  boekingId: string,
  invoer: SpiegelDoelGbsInputDto,
): Promise<void> {
  return apiJson<void>(`/doorbelasting/${administratieId}/boekingen/${boekingId}/doel-gbs`, {
    ...PUT_JSON,
    body: JSON.stringify(invoer),
  })
}

export function boekSpiegelAlsnog(
  administratieId: string,
  boekingId: string,
): Promise<DoorbelastingBoekResultaatDto> {
  return apiPostJson<DoorbelastingBoekResultaatDto>(
    `/doorbelasting/${administratieId}/boekingen/${boekingId}/spiegel-boeken`,
    {},
  )
}

/** Storno van een deelboeking (actie 19 beide kanten) — reden verplicht (≥5 tekens). */
export function stornoDoorbelastingBoeking(
  administratieId: string,
  boekingId: string,
  reden: string,
): Promise<DoorbelastingBoekResultaatDto> {
  return apiPostJson<DoorbelastingBoekResultaatDto>(
    `/doorbelasting/${administratieId}/boekingen/${boekingId}/storno`,
    { reden },
  )
}
