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

/** Open afwijzing bij een document (mockup: chip "Afgewezen — ter controle" mét reden en wie
 * afwees in de werkvoorraad; banner + heropenen-knop op het controlescherm). */
export interface AfwijzingInfoDto {
  id: string
  reden: string
  afgewezen_door: string
  afgewezen_op: string
  toegewezen_aan: string
  status_voor_afwijzing: string
}

export interface AfwijzingDto {
  id: string
  document_id: string
  document_status: string
  reden: string
  status: string
  status_voor_afwijzing: string
  afgewezen_door: string
  afgewezen_op: string
  toegewezen_aan: string
  heropend_door: string | null
  heropend_op: string | null
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
  afwijzing: AfwijzingInfoDto | null
}

export interface DocumentListResponseDto {
  documenten: DocumentListItemDto[]
}

export interface DocumentGebeurtenisDto {
  van_status: string | null
  naar_status: string
  actor_id: string
  /** True als de overgang door de achtergrondworker (systeem-actor) is gezet — de tijdlijn
   * toont dan herkenbaar "systeem" i.p.v. een menselijke handeling. */
  actor_is_systeem: boolean
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
  afwijzing: AfwijzingInfoDto | null
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
  /** Fix 3 (2026-07-10): effectieve samenvoeg-stand (voorkeur per crediteur, default aan),
   * of samenvoegen kan (false bij projectplicht — daar is per-regel hard) en de door de backend
   * berekende één-regel-variant voor de samengevoegde weergave. */
  regels_samenvoegen: boolean
  samenvoegen_toegestaan: boolean
  samengevoegde_regel: BoekvoorstelRegelDto | null
}

export interface GeheugenVeldVoorstelDto {
  waarde: string | null
  /** Winnend gewicht / totaal gewicht van de meegewogen stemmen (0.0 zonder voorstel). */
  confidence: number
  /** Aantal observaties dat de winnende waarde steunt (ongewogen telling). */
  telling: number
  oranje: boolean
  reden: string | null
  /** True zodra ≥1 app-observatie de winnende waarde dekt; false = uitsluitend rlz_seed →
   * altijd oranje met hint "uit historie, nog niet bevestigd" (Peters ontwerp 2026-07-14). */
  app_bevestigd: boolean
}

/** Boekingsgeheugen-voorstel (B6, backend/app/geheugen/router.py): per veld (GB/btw/project) een
 * default + confidence + oranje-vlag. Een voorstel is een default, nooit een beslissing — de
 * harde checks (incl. projectplicht) blijven onverkort blokkerend. */
export interface GeheugenVoorstelDto {
  gb: GeheugenVeldVoorstelDto
  btw: GeheugenVeldVoorstelDto
  project: GeheugenVeldVoorstelDto
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
  eigenaar_gebruiker_id: string | null
}

export interface AdministratieInstellingenLijstDto {
  administraties: AdministratieInstellingenDto[]
}

/** Eén vraag over een document (vragenworkflow PART A, backend/app/documenten/vragen.py).
 * `status_voor_vraag` is de herkomst-status: beantwoorden/intrekken zetten het document daar
 * exact naar terug. `document_status` reist mee zodat de UI een weesvraag op een verwijderd
 * document herkent (niet actief tonen). */
export interface VraagDto {
  id: string
  document_id: string
  document_bestandsnaam: string
  document_status: string
  /** Totaalbedrag uit het boekvoorstel (Decimal serialiseert als string), null zonder voorstel. */
  totaalbedrag: string | null
  vraag_tekst: string
  status: 'open' | 'beantwoord' | 'ingetrokken'
  status_voor_vraag: string
  gesteld_door: string
  gesteld_op: string
  toegewezen_aan: string
  antwoord_tekst: string | null
  beantwoord_door: string | null
  beantwoord_op: string | null
  ingetrokken_door: string | null
  ingetrokken_op: string | null
  ingetrokken_reden: string | null
}

export interface VraagLijstDto {
  vragen: VraagDto[]
}

/** Toewijsbare medewerker (vraagmodal): bewust alleen id + naam. */
export interface MedewerkerDto {
  id: string
  naam: string
}

export interface MedewerkersLijstDto {
  medewerkers: MedewerkerDto[]
}

export interface EigenaarDto {
  eigenaar_gebruiker_id: string | null
}
