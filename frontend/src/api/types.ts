export interface AdministratieDto {
  id: string
  naam: string
}

export interface MijnAdministratiesResponseDto {
  administraties: AdministratieDto[]
}

export interface DuplicaatReferentieDto {
  document_id: string
  bestandsnaam: string
  aangemaakt_op: string
}

export interface DocumentListItemDto {
  id: string
  bestandsnaam: string
  status: string
  bron: string
  mogelijk_duplicaat_van: DuplicaatReferentieDto | null
  toegewezen_aan: string | null
  aangemaakt_op: string
  laatst_gewijzigd_op: string
}

export interface DocumentListResponseDto {
  documenten: DocumentListItemDto[]
}

export interface DocumentGebeurtenisDto {
  van_status: string | null
  naar_status: string
  actor_id: string
  detail: Record<string, unknown> | null
  tijdstip: string
}

export interface DocumentDetailDto {
  id: string
  administratie_id: string | null
  bestandsnaam: string
  status: string
  bron: string
  mogelijk_duplicaat_van: DuplicaatReferentieDto | null
  toegewezen_aan: string | null
  aangemaakt_op: string
  laatst_gewijzigd_op: string
  veldvoorstel: Record<string, unknown> | null
  tijdlijn: DocumentGebeurtenisDto[]
}

export interface UploadResponseDto {
  document_id: string
  status: string
  mogelijk_duplicaat_van: DuplicaatReferentieDto | null
}

export interface DocumentActieResponseDto {
  document_id: string
  status: string
}

export interface TokenPaarResponseDto {
  access_token: string
  token_type: string
}

export interface UitnodigingAccepterenResponseDto {
  totp_setup_token: string
  otpauth_uri: string
  secret: string
}

export interface GrootboekOptieDto {
  ledger_id: string
  code: string
  naam: string
  soort: number
}

export interface GrootboekLijstDto {
  rekeningen: GrootboekOptieDto[]
}

export interface TaxrateOptieDto {
  id: string
  naam: string | null
  /** Fractie als string, bv. "0.2100" voor 21% (Decimal-serialisatie, zie api/client.ts). Null
   * als RLZ geen percentage teruggaf voor deze btw-code. */
  percentage: string | null
}

export interface TaxrateLijstDto {
  btw_codes: TaxrateOptieDto[]
}

export interface VendorOptieDto {
  id: string
  naam: string | null
}

export interface VendorLijstDto {
  crediteuren: VendorOptieDto[]
}

export interface ProjectOptieDto {
  id: string
  naam: string | null
}

export interface ProjectLijstDto {
  projecten: ProjectOptieDto[]
}

export interface BoekvoorstelRegelDto {
  ledger_id: string | null
  taxrate_id: string | null
  project_id: string | null
  netto_bedrag: string | null
  btw_bedrag: string | null
  omschrijving: string | null
}

export interface BoekvoorstelDto {
  document_id: string
  vendor_id: string | null
  referentie: string | null
  factuurdatum: string | null
  totaalbedrag: string | null
  rlz_boekstuknummer: string | null
  opgeslagen: boolean
  regels: BoekvoorstelRegelDto[]
}

export interface CheckResultaatDto {
  naam: string
  ok: boolean
  melding: string
}

export interface CheckRapportDto {
  geblokkeerd: boolean
  resultaten: CheckResultaatDto[]
}

export interface BoekvoorstelMetChecksDto {
  boekvoorstel: BoekvoorstelDto
  checks: CheckRapportDto
}

export interface BoekenResponseDto {
  document_id: string
  status: string
  rlz_document_id: string
  rlz_boekstuknummer: string | null
}

export interface ProjectVerplichtDto {
  verplicht: boolean
}

export interface BoekenIngeschakeldDto {
  ingeschakeld: boolean
}

export interface AdministratieInstellingenDto {
  id: string
  naam: string
  boeken_ingeschakeld: boolean
  project_verplicht: boolean
  ai_extractie_ingeschakeld: boolean
}

export interface AdministratieInstellingenLijstDto {
  administraties: AdministratieInstellingenDto[]
}
