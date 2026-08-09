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
  /** Gevuld = de laatste versheid-probe faalde onverwacht; laatste_import is dan de
   *  laatst-bekende (mogelijk verouderde) waarde. */
  probe_fout: string | null
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

export interface AfletterKoppelingDto {
  rlz_document_id: string | null
  boekstuknummer: string | null
  bedrag: string | null
}

export interface AfletterOpdrachtDto {
  id: string
  status: string
  payment_item_id: string | null
  klaargezet_op: string
  /** Gevuld zodra de verificatieronde de opdracht controleerde terwijl de mutatie nog open
   *  stond — chip "wacht op verificatie" i.p.v. "klaargezet". */
  laatste_verificatie_poging_op: string | null
  geverifieerd_op: string | null
  /** false = de mens koppelde in RLZ iets anders dan het voorstel ("afwijkend gevolgd"). */
  voorstel_gevolgd: boolean | null
  /** 'api' = koppeling door de app gelegd; 'al_afgeletterd_in_rlz' = de vooraf-toets zag de
   *  mutatie al dicht in RLZ (kliktest 2026-08-09); null = sync-verificatie. */
  uitvoering: string | null
  koppelingen: AfletterKoppelingDto[]
}

export interface AfletterHistorieRegelDto {
  opdracht: AfletterOpdrachtDto
  boekdatum: string | null
  tegenpartij_naam: string | null
  bedrag: string | null
}

export interface AfletterHistorieDto {
  opdrachten: AfletterHistorieRegelDto[]
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
  automatisch_afgeletterd: number
  afletter_fouten: string[]
  vastly_gemeld: number
  automatisch_geboekt: number
  automatisch_fouten: string[]
}

/** Response van afletteren-klaarzetten én voer-uit: `afgeletterd_via_api` = koppeling direct via
 *  de API gelegd + geverifieerd; `al_afgeletterd_in_rlz` = de mutatie bleek in RLZ al afgeletterd
 *  (vooraf-toets, kliktest 2026-08-09) — geverifieerd zonder nieuwe koppeling, geen fout;
 *  `wacht_op_mens_in_rlz` = fallback ná een API-fout (`fout` gevuld, nooit stil) — de opdracht
 *  staat dan klaar voor "Nu afletteren" of de mens in de RLZ-UI. */
export interface AfletterActieResultaatDto {
  opdracht_id: string
  uitkomst: 'afgeletterd_via_api' | 'al_afgeletterd_in_rlz' | 'wacht_op_mens_in_rlz'
  fout: string | null
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

export function haalAfletterOpdrachten(administratieId: string, rekeningId: string): Promise<AfletterHistorieDto> {
  return apiJson<AfletterHistorieDto>(
    `/administraties/${administratieId}/bank/rekeningen/${rekeningId}/afletter-opdrachten`,
  )
}

export function verifieerAfletteren(
  administratieId: string,
  rekeningId: string,
): Promise<{ geverifieerd: number }> {
  return apiJson(`/administraties/${administratieId}/bank/rekeningen/${rekeningId}/verifieer-afletteren`, {
    method: 'POST',
  })
}

export function zetAfletterenKlaar(
  administratieId: string,
  mutatieId: string,
  paymentItemId: string,
): Promise<AfletterActieResultaatDto> {
  return apiPostJson(`/administraties/${administratieId}/bank/mutaties/${mutatieId}/afletteren-klaarzetten`, {
    payment_item_id: paymentItemId,
  })
}

export function voerAfletterOpdrachtUit(
  administratieId: string,
  opdrachtId: string,
): Promise<AfletterActieResultaatDto> {
  return apiJson(`/administraties/${administratieId}/bank/afletter-opdrachten/${opdrachtId}/voer-uit`, {
    method: 'POST',
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
