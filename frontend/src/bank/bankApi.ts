import { apiJson, apiPostJson } from '../api/client'

// DTO's spiegelen backend/app/bank/schemas.py — bedragen reizen als string (Decimal), nooit als
// float: geldbedragen worden hier alleen getoond en teruggestuurd, nooit berekend.

export interface BankKlantDto {
  administratie_id: string
  naam: string
  open_mutaties: number
  oudste_open_datum: string | null
  rekeningen: string[]
  laatste_sync_op: string | null
  ooit_gesynchroniseerd: boolean
}

export interface BankOverzichtDto {
  klanten: BankKlantDto[]
}

export interface LaatsteImportDto {
  datum: string | null
  bron: string | null
  type: string | null
  bestandsnaam: string | null
}

export interface RekeningDto {
  id: string
  naam: string | null
  iban: string | null
  rekening_type: number | null
  is_kas: boolean
  saldo: string | null
  saldo_datum: string | null
  open_mutaties: number
  heeft_aanlevering: boolean
  laatste_import: LaatsteImportDto | null
}

export interface RekeningenDto {
  rekeningen: RekeningDto[]
  laatste_sync_op: string | null
  ooit_gesynchroniseerd: boolean
  heeft_bankaanlevering: boolean
}

export interface OpenPostDto {
  id: string
  bedrag: string | null
  referentie: string | null
  referentie2: string | null
  rlz_document_id: string | null
}

export interface BoekRegelDto {
  ledger_id: string
  netto_bedrag: string
  btw_bedrag: string | null
  taxrate_id: string | null
  project_id: string | null
  omschrijving: string | null
}

export interface VoorstelDto {
  soort: 'exacte_match' | 'deel_match' | 'vaste_regel' | 'rlz_voorstel' | 'handmatig'
  kleur: 'groen' | 'oranje'
  bron: string
  reden: string
  payment_item_id: string | null
  open_post: OpenPostDto | null
  regel_id: string | null
  regels: BoekRegelDto[]
}

export interface AfletterOpdrachtDto {
  id: string
  status: string
  payment_item_id: string | null
  klaargezet_op: string
}

export interface RegelVoorstelDto {
  tegenpartij_sleutel: string
  ledger_id: string
  taxrate_id: string | null
  aantal_boekingen: number
}

export interface MutatieDto {
  id: string
  boekdatum: string | null
  bedrag: string | null
  open_bedrag: string | null
  tegenpartij_naam: string | null
  omschrijving: string | null
  tegenrekening_iban: string | null
  voorstel: VoorstelDto
  afletter_opdracht: AfletterOpdrachtDto | null
  regel_voorstel: RegelVoorstelDto | null
}

export interface MutatiesDto {
  mutaties: MutatieDto[]
}

export interface BankSyncResultaatDto {
  rekeningen_bijgewerkt: number
  mutaties_nieuw: number
  mutaties_bijgewerkt: number
  open_ververst: number
  open_posten_bijgewerkt: number
  afletteren_geverifieerd: number
  vastly_gemeld: number
  automatisch_geboekt: number
  automatisch_fouten: string[]
}

export interface DirectBoekenRegelInputDto {
  ledger_id: string
  netto_bedrag: string
  btw_bedrag: string | null
  taxrate_id: string | null
  project_id: string | null
  omschrijving: string | null
}

export interface DirectBoekenResultaatDto {
  boeking_id: string
  rlz_boekstuknummer: string | null
  al_eerder_geboekt: boolean
  vaste_regel_aangemaakt: boolean
}

export function haalBankOverzicht(): Promise<BankOverzichtDto> {
  return apiJson<BankOverzichtDto>('/bank/overzicht')
}

export function haalRekeningen(administratieId: string): Promise<RekeningenDto> {
  return apiJson<RekeningenDto>(`/administraties/${administratieId}/bank/rekeningen`)
}

export function haalMutaties(administratieId: string, rekeningId: string): Promise<MutatiesDto> {
  return apiJson<MutatiesDto>(`/administraties/${administratieId}/bank/rekeningen/${rekeningId}/mutaties`)
}

export function synchroniseerBank(administratieId: string): Promise<BankSyncResultaatDto> {
  return apiJson<BankSyncResultaatDto>(`/administraties/${administratieId}/bank/sync`, { method: 'POST' })
}

export function zetAfletterenKlaar(
  administratieId: string,
  mutatieId: string,
  paymentItemId: string,
): Promise<{ opdracht_id: string; uitkomst: string }> {
  return apiPostJson(`/administraties/${administratieId}/bank/mutaties/${mutatieId}/afletteren-klaarzetten`, {
    payment_item_id: paymentItemId,
  })
}

export function trekAfletterenIn(administratieId: string, opdrachtId: string): Promise<void> {
  return apiJson(`/administraties/${administratieId}/bank/afletter-opdrachten/${opdrachtId}/intrekken`, {
    method: 'POST',
  })
}

export function boekDirect(
  administratieId: string,
  mutatieId: string,
  payload: {
    regels: DirectBoekenRegelInputDto[]
    omschrijving: string | null
    bron: 'handmatig' | 'vaste_regel'
    vaste_regel_opslaan: boolean
  },
): Promise<DirectBoekenResultaatDto> {
  return apiPostJson(`/administraties/${administratieId}/bank/mutaties/${mutatieId}/direct-boeken`, payload)
}
