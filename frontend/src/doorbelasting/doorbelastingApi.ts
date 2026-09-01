import { ApiError, apiFetch, apiJson, apiPostJson } from '../api/client'
import type {
  BoekenIngeschakeldDto,
  DoelProjectenDto,
  VerdeelsleutelDto,
  VerdeelsleutelInputDto,
  DoorbelastingBoekResultaatDto,
  DoorbelastingInstellingDto,
  DoorbelastingInstellingInputDto,
  DoorbelastingMappingDto,
  DoorbelastingMappingWijzigingDto,
  DoorbelastingRunDto,
  DoorbelastingVerdeelRegelInputDto,
  SpiegelDoelGbsInputDto,
  SpiegelTaakDto,
  StornoToetsDto,
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

// --- "+ Doelentiteit toevoegen" (mockup doorbelasting-doel-toevoegen.html, 01-09) ---------------

export interface KandidaatDoelDto {
  id: string
  naam: string
}

/** Vooringevulde provisie-GB: de meest voorkomende rekeningCODE van de bestaande rijen —
 * ledger-GUID's verschillen per administratie, de code is het overdraagbare gegeven. */
export interface ProvisieVoorstelDto {
  code: string
  naam: string
}

export interface KandidaatDoelenDto {
  kandidaten: KandidaatDoelDto[]
  provisie_voorstel: ProvisieVoorstelDto | null
}

export interface DebiteurMatchDto {
  customer_guid: string
  naam: string
  exact: boolean
  /** Kaartgegevens ter expliciete bevestiging (les Mantelzorgwoningen 01-09): label → waarde. */
  kaart: Record<string, string>
}

export interface DoorbelastingMappingAanmaakDto {
  doel_administratie_id: string
  doelentiteit_naam: string
  /** Gevuld = de door de mens bevestigde bestaande debiteur; null = idempotente aanmaak bij opslaan. */
  doel_customer_guid: string | null
  provisie_kosten_ledger_id: string | null
  intercompany: boolean
}

export function haalKandidaatDoelenOp(administratieId: string): Promise<KandidaatDoelenDto> {
  return apiJson<KandidaatDoelenDto>(`/doorbelasting/${administratieId}/mappings/kandidaat-doelen`)
}

export function zoekDebiteurInBron(
  administratieId: string,
  zoeknaam: string,
): Promise<{ matches: DebiteurMatchDto[] }> {
  return apiPostJson(`/doorbelasting/${administratieId}/mappings/debiteur-lookup`, { zoeknaam })
}

export function maakDoorbelastingMapping(
  administratieId: string,
  invoer: DoorbelastingMappingAanmaakDto,
): Promise<DoorbelastingMappingDto> {
  return apiPostJson(`/doorbelasting/${administratieId}/mappings`, invoer)
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

/** Default-AAN (besluit Peter 25-08, deel 2 punt 5): het controlescherm zet het vinkje
 * "Doorbelasten na boeken" standaard aan op een administratie mét toggle. De server maakt
 * alléén een klaargezette run als er voor dit document nog nooit één bestond (204 = niets
 * aangemaakt: de mens had 'm al uitgezet, of het document is niet klaarzetbaar). */
export async function zetDoorbelastingDefaultAan(
  administratieId: string,
  documentId: string,
): Promise<DoorbelastingRunDto | null> {
  const resp = await apiFetch(`/doorbelasting/${administratieId}/documenten/${documentId}/run/default`, {
    method: 'POST',
  })
  if (resp.status === 204) return null
  if (!resp.ok) throw new ApiError(resp.status, `Doorbelasten standaard aanzetten mislukt (${resp.status})`)
  return (await resp.json()) as DoorbelastingRunDto
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
/** Vinkje "Doorbelasten na boeken" weer uit (besluit 25-08): klaargezette run → vervallen (spoor blijft). */
export function laatDoorbelastingRunVervallen(administratieId: string, runId: string): Promise<DoorbelastingRunDto> {
  return apiPostJson<DoorbelastingRunDto>(`/doorbelasting/${administratieId}/runs/${runId}/vervallen`, {})
}

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

/** Aangifte-poort als leesroute (2026-08-16): per boeking van dit document of de storno-knop
 * aan mag — geblokkeerd zodra één kant (bron-verkoop óf doel-spiegel) in een ingediende
 * btw-aangifte valt. De server-side check op de POST blijft de echte poort; de UI schakelt de
 * knop uit mét melding en behandelt élke laadfout fail-closed (knop uit). */
/** Rechtsgeldige factuur-PDF van een doorbelastings-boeking (blok A 26-08): bewaarkopie van
 * RLZ's eigen render, dezelfde bytes als de bijlage op beide kanten. Fetch + blob (Authorization-
 * header); de aanroeper is eigenaar van de URL (revokeObjectURL bij opruimen). */
export async function haalDoorbelastingFactuurBlob(administratieId: string, boekingId: string): Promise<string> {
  const resp = await apiFetch(`/doorbelasting/${administratieId}/boekingen/${boekingId}/factuur`)
  if (!resp.ok) throw new Error(`Factuur-PDF ophalen mislukt (${resp.status})`)
  return URL.createObjectURL(await resp.blob())
}

export function haalStornoToetsOp(administratieId: string, documentId: string): Promise<StornoToetsDto> {
  return apiJson<StornoToetsDto>(
    `/doorbelasting/${administratieId}/documenten/${documentId}/storno-toets`,
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

// --- Opruimlijst achtergebleven RLZ-concepten (hygiëne-run 2026-08-16) ---------------------------

export interface OpruimKandidaatDto {
  concept_administratie_id: string
  kant: string // 'verkoop_bron' | 'spiegel_doel'
  rlz_id: string
  document_id: string
  referentie: string | null
  reden: string // 'gestorneerd' | 'vervallen_run'
  detail: string
}

export interface OpruimlijstDto {
  kandidaten: OpruimKandidaatDto[]
  fouten: string[]
}

/** Live scan tegen RLZ (klein volume) — Beheerder-only; de app verwijdert nooit iets in RLZ. */
export function haalOpruimlijstOp(administratieId: string): Promise<OpruimlijstDto> {
  return apiJson<OpruimlijstDto>(`/doorbelasting/${administratieId}/opruimlijst`)
}

// --- doorbelasting × projecten + verdeelsleutels (besluit Peter 25-08, deel 2 punt 2) --------

/** Projecten van de DOEL-administratie achter een whitelist-rij, mét project_verplicht en
 * contract-m² (voor de m²-basis). 403 = geen scope op het doel. */
export function haalDoelProjectenOp(administratieId: string, mappingId: string): Promise<DoelProjectenDto> {
  return apiJson<DoelProjectenDto>(`/doorbelasting/${administratieId}/mappings/${mappingId}/projecten`)
}

export function haalVerdeelsleutelsOp(administratieId: string): Promise<VerdeelsleutelDto[]> {
  return apiJson<VerdeelsleutelDto[]>(`/doorbelasting/${administratieId}/verdeelsleutels`)
}

/** Nieuwe sleutel of nieuwe versie onder een bestaande naam (append-only, server-side audit). */
export function slaVerdeelsleutelOp(administratieId: string, input: VerdeelsleutelInputDto): Promise<VerdeelsleutelDto> {
  return apiPostJson<VerdeelsleutelDto>(`/doorbelasting/${administratieId}/verdeelsleutels`, input)
}

/** Eén klik: sleutel op alle bron-regels van de run toepassen; de verse run komt terug en is
 * daarna nog aanpasbaar vóór opslaan. */
export function pasVerdeelsleutelToe(administratieId: string, runId: string, sleutelId: string): Promise<DoorbelastingRunDto> {
  return apiPostJson<DoorbelastingRunDto>(
    `/doorbelasting/${administratieId}/runs/${runId}/verdeelsleutels/${sleutelId}/toepassen`,
    {},
  )
}
