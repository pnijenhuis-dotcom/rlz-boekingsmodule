// Activa / MVA fase 1 (ontwerp docs/ONTWERP_ACTIVA_MVA.md, akkoord Peter 21-09; CONTRACT_A 21-09).
// Het activaregister leeft in RLZ (`FixedAssets`) — kernprincipe 1: nooit een tweede register in de module. De
// module DETECTEERT bij het boeken dat een regel op een activarekening (`is_activa`) een activum wordt, VULT het
// activum voor (aanschafwaarde = regelnetto, datum = factuurdatum, categorie + termijn uit de rekeningnaam en de
// administratie-instelling) en maakt het ná boeken aan (autoboek-patroon: opt-in per administratie, default UIT).
// Fiscale regels worden GETOETST en gesignaleerd, nooit zelf gerekend (ontwerp §3). Bedragen komen als string
// (Decimal) binnen; de client formatteert alleen. Spiegelt backend/app/activa/router.py (schemas).
import { apiJson, apiPostJson } from '../api/client'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export type KoppelingStatus = 'gepland' | 'aangemaakt' | 'overgeslagen' | 'mislukt' | 'beoordelen'
export type KoppelingHerkomst = 'mens' | 'automatisch'
export type GrensBron = 'rlz' | 'instelling'

/** Categoriecode uit `backend/app/activa/categorie.py` — pure code, geen eigen lijst hier (de labels reizen mee). */
export type ActivaCategorie =
  | 'gebouwen'
  | 'inventaris'
  | 'vervoermiddelen'
  | 'computers_software'
  | 'machines'
  | 'steigermateriaal'
  | 'onbekend'

export interface ActivaSignaalDto {
  code: string
  tekst: string
}

export interface ActivumKoppelingDto {
  id: string
  status: KoppelingStatus
  herkomst: KoppelingHerkomst
  rlz_fixed_asset_id: string | null
  rlz_receipt_number: string | null
  reden: string | null
  door: string | null
  gewijzigd_op: string | null
}

export interface ActivaKandidaatDto {
  regel_volgnummer: number
  ledger_id: string
  ledger_code: string
  ledger_naam: string
  omschrijving: string
  aanschafwaarde: string
  aanschafdatum: string | null
  categorie: ActivaCategorie | string
  categorie_label: string
  termijn_maanden: number
  methode_naam: string
  restwaarde: string
  afschrijving_ledger_id: string | null
  afschrijving_ledger_code: string | null
  /** Herkomst van de voorvulling (BUG 24-09): `koppeling` (vastgelegd), `instelling` (per categorie), `conventie`
   * (kostenrekening 4xxx mét dezelfde omschrijving ná "Afschrijving…", Peter 24-09), of null = leeg → de combobox is verplicht, de knop staat uit. */
  afschrijving_bron?: 'koppeling' | 'instelling' | 'conventie' | string | null
  signalen: ActivaSignaalDto[]
  koppeling: ActivumKoppelingDto | null
}

export interface ActivaOnderGrensDto {
  regel_volgnummer: number
  ledger_code: string
  ledger_naam: string
  netto: string
  tekst: string
}

export interface LedgerOptieDto {
  ledger_id: string
  code: string
  naam: string
}

export interface ActivaVoorstelDto {
  administratie_id: string
  document_id: string
  document_geboekt: boolean
  grens: string
  grens_bron: GrensBron
  automatisch_ingeschakeld: boolean
  register_leesbaar: boolean | null
  register_fout: string | null
  kandidaten: ActivaKandidaatDto[]
  onder_grens: ActivaOnderGrensDto[]
  afschrijving_ledger_opties: LedgerOptieDto[]
}

export interface ActivaCategorieDto {
  code: ActivaCategorie | string
  label: string
  default_maanden: number
}

export interface ActivaKoppelingTellersDto {
  gepland: number
  aangemaakt: number
  overgeslagen: number
  mislukt: number
  beoordelen: number
}

export interface ActivaInstellingDto {
  automatisch_aanmaken_ingeschakeld: boolean
  activeringsgrens: string
  grens_rlz: string | null
  grens_rlz_gelezen_op: string | null
  effectieve_grens: string
  grens_bron: GrensBron
  termijnen: Record<string, number>
  afschrijving_ledgers: Record<string, string>
  register_leesbaar: boolean | null
  register_geprobeerd_op: string | null
  register_fout: string | null
  categorieen: ActivaCategorieDto[]
  mva_rekeningen: LedgerOptieDto[]
  afschrijving_ledger_opties: LedgerOptieDto[]
  koppelingen_tellers: ActivaKoppelingTellersDto
}

export interface ActivaInstellingBody {
  automatisch_aanmaken_ingeschakeld: boolean
  activeringsgrens: string
  termijnen: Record<string, number>
  afschrijving_ledgers: Record<string, string>
}

export interface ActivumAanmakenBody {
  afschrijving_ledger_id?: string | null
  termijn_maanden?: number | null
}

function basis(administratieId: string, documentId: string): string {
  return `/administraties/${administratieId}/documenten/${documentId}/activa-voorstel`
}

/** GET …/activa-voorstel — geen RLZ-call; leeg (geen kandidaten én geen onder_grens) = de kaart toont niets. */
export function haalActivaVoorstel(administratieId: string, documentId: string): Promise<ActivaVoorstelDto> {
  return apiJson<ActivaVoorstelDto>(basis(administratieId, documentId))
}

/** POST …/activa-voorstel/{volgnummer}/aanmaken — niet geboekt = koppeling `gepland` (aanmaken ná boeken), geboekt =
 * direct in RLZ. 422 `geen_kandidaat`, 409 `al_aangemaakt`. */
export function activumAanmaken(
  administratieId: string,
  documentId: string,
  regelVolgnummer: number,
  body: ActivumAanmakenBody = {},
): Promise<ActivaVoorstelDto> {
  return apiPostJson<ActivaVoorstelDto>(`${basis(administratieId, documentId)}/${regelVolgnummer}/aanmaken`, body)
}

/** POST …/activa-voorstel/{volgnummer}/overslaan — reden verplicht (leeg → 422), `aangemaakt` → 409. */
export function activumOverslaan(
  administratieId: string,
  documentId: string,
  regelVolgnummer: number,
  reden: string,
): Promise<ActivaVoorstelDto> {
  return apiPostJson<ActivaVoorstelDto>(`${basis(administratieId, documentId)}/${regelVolgnummer}/overslaan`, { reden })
}

export function haalActivaInstelling(administratieId: string): Promise<ActivaInstellingDto> {
  return apiJson<ActivaInstellingDto>(`/administraties/${administratieId}/activa-instelling`)
}

/** PUT …/activa-instelling (Beheerder) — upsert + audit oud→nieuw server-side. */
export function zetActivaInstelling(administratieId: string, body: ActivaInstellingBody): Promise<ActivaInstellingDto> {
  return apiJson<ActivaInstellingDto>(`/administraties/${administratieId}/activa-instelling`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  })
}

/** "Lineair N jaar" uit maanden — dezelfde vorm als de server (`methode_naam`), alleen voor de instellingen-keuzelijst. */
export function methodeNaamVoorMaanden(maanden: number): string {
  const jaren = Math.max(1, Math.ceil(maanden / 12))
  return `Lineair ${jaren} jaar`
}

/** Termijn-keuzes 1–50 jaar in maanden (contract: 12..600, veelvoud van 12). */
export const TERMIJN_OPTIES_MAANDEN: readonly number[] = Array.from({ length: 50 }, (_, i) => (i + 1) * 12)

/** Klantleesbare stand van een koppeling — één bron voor kaart en instellingen-tellers. */
export const KOPPELING_STATUS_LABEL: Record<KoppelingStatus, string> = {
  gepland: 'gepland — ná boeken',
  aangemaakt: 'aangemaakt in RLZ',
  overgeslagen: 'niet geactiveerd',
  mislukt: 'aanmaken mislukt',
  beoordelen: 'beoordelen in RLZ',
}

/** Spiegel van `service.TEKST_AFSCHRIJVING_VEREIST` (route 422; het scherm toont dezelfde zin bij een lege combobox). */
export const AFSCHRIJVING_VEREIST_TEKST = 'Kies een afschrijvingsrekening — Reeleezee vereist er één per activum'

/** Klantleesbaar label van de voorvulling-herkomst (chip op de kaart). */
export const AFSCHRIJVING_BRON_LABEL: Record<string, string> = {
  conventie: 'voorgevuld: conventie (kostenrekening zelfde omschrijving)',
  instelling: 'voorgevuld: uit de instelling',
}

export const REGISTER_NIET_LEESBAAR_TEKST =
  'activaregister in RLZ niet leesbaar — recht ontbreekt op de webservice-login (RLZ-recht "Vaste activa" zetten)'
