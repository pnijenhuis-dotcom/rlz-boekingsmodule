export interface AdministratieDto {
  id: string
  naam: string
}

export interface MijnAdministratiesResponseDto {
  administraties: AdministratieDto[]
}

export interface DocumentListItemDto {
  id: string
  bestandsnaam: string
  status: string
  bron: string
  mogelijk_duplicaat_van: string | null
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
  mogelijk_duplicaat_van: string | null
  toegewezen_aan: string | null
  aangemaakt_op: string
  laatst_gewijzigd_op: string
  veldvoorstel: Record<string, unknown> | null
  tijdlijn: DocumentGebeurtenisDto[]
}

export interface UploadResponseDto {
  document_id: string
  status: string
  mogelijk_duplicaat_van: string | null
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
