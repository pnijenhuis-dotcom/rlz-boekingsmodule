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

/** `bedrag` = het OPEN bedrag van de post. De kaart-specs (blok E5, 01/02-09) komen uit de bestaande
 * payment_item_cache — ontbrekend = null, de kaart laat die regel dan weg (nooit een wachtende kaart). */
export interface OpenPostDto {
  id: string
  bedrag: string | null
  referentie: string | null
  referentie2: string | null
  rlz_document_id: string | null
  tegenpartij_naam?: string | null
  documentsoort?: string | null
  boekstuknummer?: string | null
  factuurdatum?: string | null
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
  afletteren_wachtend?: number
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

// --- feedbackronde 25-08 deel 4: auto-verversing, relatie-koppeling, splitsen --------------------

export type BankSyncRunStatus = 'geen' | 'overgeslagen' | 'wachtrij' | 'bezig' | 'klaar' | 'fout'

export interface BankSyncRunResultaatDto {
  mutaties_nieuw: number
  mutaties_bijgewerkt: number
  open_ververst: number
  afletteren_geverifieerd: number
  /** Blok E3 (01/02-09): klaargezette opdrachten die vóór de verificatie wachtten — de toast meldt de
   * verificatie-uitkomst alleen als dit > 0 is. */
  afletteren_wachtend?: number
  automatisch_afgeletterd: number
  automatisch_geboekt: number
  fouten: string[]
}

/** Achtergrond-sync bij het openen van het bankscherm (besluit Peter 25-08, punt 2): de POST geeft
 *  202 + deze status terug; `overgeslagen` = laatste sync jonger dan de drempel (~5 min), geen
 *  ronde; `wachtrij`/`bezig` → pollen op de status-route tot klaar/fout/geen. */
export interface BankSyncRunDto {
  run_id: string | null
  status: BankSyncRunStatus
  overgeslagen: boolean
  laatste_sync_op: string | null
  aangevraagd_op?: string | null
  beeindigd_op?: string | null
  resultaat?: BankSyncRunResultaatDto | null
  fout_reden: string | null
}

/** `forceer` (blok E2: het ⟳-icoon als handmatige noodrem) slaat alleen de 5-minuten-drempel over. */
export function startBankSyncAchtergrond(administratieId: string, forceer = false): Promise<BankSyncRunDto> {
  return apiJson<BankSyncRunDto>(`/administraties/${administratieId}/bank/sync-achtergrond${forceer ? '?forceer=true' : ''}`, {
    method: 'POST',
  })
}

export function haalBankSyncAchtergrondStatus(administratieId: string): Promise<BankSyncRunDto> {
  return apiJson<BankSyncRunDto>(`/administraties/${administratieId}/bank/sync-achtergrond/status`)
}

export type RelatieSoort = 'crediteur' | 'debiteur'

export interface KoppelRelatieInputDto {
  relatie_soort: RelatieSoort
  entity_id: string
  omschrijving?: string | null
}

export interface RelatieBoekingDto {
  boeking_id: string
  rlz_document_id: string
  rlz_boekstuknummer: string | null
  open_restant: string | null
}

/** Derde verwerkroute (punt 3): aanbetalingsdocument op de relatie + afletteren van de mutatie.
 *  Fouten: 409 (instelling ontbreekt / al gekoppeld / bedrag past niet), 403 boeken uit,
 *  429 volumerem, 502 RLZ — de detail-tekst komt via ApiError.message terug. */
export function koppelRelatie(
  administratieId: string,
  mutatieId: string,
  payload: KoppelRelatieInputDto,
): Promise<RelatieBoekingDto> {
  return apiPostJson(`/administraties/${administratieId}/bank/mutaties/${mutatieId}/koppel-relatie`, payload)
}

export interface AanbetalingDto {
  boeking_id: string
  payment_transaction_id: string
  relatie_soort: RelatieSoort
  entity_id: string
  entity_naam: string | null
  bedrag: string
  boekdatum: string | null
  rlz_boekstuknummer: string | null
  geboekt_op: string
  status: string
}

export interface AanbetalingenDto {
  aanbetalingen: AanbetalingDto[]
}

export function haalAanbetalingen(administratieId: string): Promise<AanbetalingenDto> {
  return apiJson<AanbetalingenDto>(`/administraties/${administratieId}/bank/aanbetalingen`)
}

export function stornoAanbetaling(administratieId: string, boekingId: string, reden: string): Promise<void> {
  return apiPostJson(`/administraties/${administratieId}/bank/aanbetalingen/${boekingId}/storno`, { reden })
}

export interface DebiteurOptieDto {
  id: string
  naam: string
}

export interface DebiteurenZoekDto {
  debiteuren: DebiteurOptieDto[]
}

/** Live RLZ-zoekactie op naam (read-only, ≥ 2 tekens — korter geeft de backend een lege lijst). */
export function zoekDebiteuren(administratieId: string, zoek: string): Promise<DebiteurenZoekDto> {
  return apiJson<DebiteurenZoekDto>(
    `/administraties/${administratieId}/bank/debiteuren?zoek=${encodeURIComponent(zoek)}`,
  )
}

export type SplitsDeelSoort = 'grootboek' | 'open_post' | 'relatie'

/** Eén deel van een splitsing (punt 4). `bedrag` reist als Decimal-string mét het teken van de
 *  mutatie; de delen moeten server-side exact optellen tot het mutatiebedrag (422). */
export interface SplitsDeelInputDto {
  soort: SplitsDeelSoort
  bedrag: string
  regels?: DirectBoekenRegelInputDto[]
  payment_item_id?: string
  relatie_soort?: RelatieSoort
  entity_id?: string
  omschrijving?: string | null
}

export type SplitsingStatus = 'bezig' | 'verwerkt' | 'half_verwerkt' | 'gestorneerd'
export type SplitsDeelStatus = 'wacht' | 'verwerkt' | 'fout' | 'gestorneerd'

export interface SplitsDeelDto {
  deel_id: string
  volgnummer: number
  soort: SplitsDeelSoort
  bedrag: string
  status: SplitsDeelStatus
  fout: string | null
  bank_boeking_id: string | null
  afletter_opdracht_id: string | null
  relatie_boeking_id: string | null
}

export interface SplitsingDto {
  splitsing_id: string
  payment_transaction_id: string
  status: SplitsingStatus
  mutatie_bedrag: string
  aangemaakt_op: string | null
  delen: SplitsDeelDto[]
}

export interface SplitsingenDto {
  splitsingen: SplitsingDto[]
}

export function splitsMutatie(
  administratieId: string,
  mutatieId: string,
  delen: SplitsDeelInputDto[],
): Promise<SplitsingDto> {
  return apiPostJson(`/administraties/${administratieId}/bank/mutaties/${mutatieId}/splitsen`, { delen })
}

export function haalSplitsingen(administratieId: string, rekeningId: string): Promise<SplitsingenDto> {
  return apiJson<SplitsingenDto>(`/administraties/${administratieId}/bank/rekeningen/${rekeningId}/splitsingen`)
}

/** Half-verwerkt herstel: de delen op wacht/fout alsnog uitvoeren tegen de verse RLZ-staat. */
export function hervatSplitsing(administratieId: string, splitsingId: string): Promise<SplitsingDto> {
  return apiJson<SplitsingDto>(`/administraties/${administratieId}/bank/splitsingen/${splitsingId}/hervat`, {
    method: 'POST',
  })
}

/** Storno van één verwerkt deel (reden verplicht). Een afletter-deel is niet via de API
 *  storneerbaar → 409 mét tekst (storno actie 19 in RLZ zelf). */
export function stornoSplitsDeel(administratieId: string, deelId: string, reden: string): Promise<SplitsingDto> {
  return apiPostJson(`/administraties/${administratieId}/bank/splitsingen/delen/${deelId}/storno`, { reden })
}
