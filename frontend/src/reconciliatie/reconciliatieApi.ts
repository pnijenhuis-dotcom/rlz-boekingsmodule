// Inzicht › Reconciliatie (opdracht 06-09) — spiegelt backend/app/reconciliatie/schemas.py.
// De dagelijkse reconciliatie-alles-run vergelijkt onze eigen boekingen met de werkelijke stand in
// Reeleezee; dit scherm maakt de uitkomst kantoorbreed zichtbaar mét precies één handeling per rij.
// De client formatteert alleen — tellers, sortering en paginering komen van de server.
import { apiJson } from '../api/client'

export type RunStatus = 'wachtend' | 'bezig' | 'klaar' | 'fout'
export type RunBron = 'scheduler' | 'cli' | 'handmatig'
export type MailStatus = 'niet_nodig' | 'verzonden' | 'mislukt' | 'niet_geconfigureerd'

/** Stand per controleblok binnen één run (bank | documenten | omzet | doorbelasting, + 'run' bij crash). */
export interface BlokStandDto {
  status: 'ok' | 'actie' | 'fout'
  exit_code: number | null
  gecontroleerd: number
  afwijkingen: number
  geaccepteerd: number
  uitgesloten: number
  let_op: number
  fouten: number
  foutmelding: string | null
}

/** Tellers over één venster (etmaal of week): verwacht / gedaan / overgeslagen per reden-categorie. */
export interface AutomatiseringVensterDto {
  verwacht: number
  gedaan: number
  /** categorie-sleutel → aantal; vaste categorieën (bv. geen_eigenaar) staan er ook als 0 in. */
  overgeslagen: Record<string, number>
}

export interface HardeVoorwaardeDto {
  categorie: string
  aantal: number
  administratie_id: string | null
  voorbeeld: string | null
}

/** Eén automatisering (herstelrun 07-09 blok C — spiegelt app/reconciliatie/automatiseringen.py). */
export interface AutomatiseringTellerDto {
  sleutel: string
  label: string
  stand: 'aan' | 'uit' | 'deels' | 'altijd' | 'op_aanvraag'
  stand_detail: string | null
  bron: string
  dag: AutomatiseringVensterDto
  week: AutomatiseringVensterDto
  harde_voorwaarden: HardeVoorwaardeDto[]
  /** Zeven dagen aan + kandidaten, maar 0 gedaan en 0 overgeslagen = "stil" (LET-OP-bevinding). */
  stil: boolean
}

export interface AutomatiseringenDto {
  venster_uren: number
  stil_dagen: number
  berekend_op: string
  tellers: AutomatiseringTellerDto[]
}

/** samenvatting = blokstanden per blok + (sinds 07-09) de tellers per automatisering onder één vaste sleutel. */
export interface SamenvattingDto {
  [blok: string]: BlokStandDto | AutomatiseringenDto | undefined
  automatiseringen?: AutomatiseringenDto
}

export interface ReconciliatieRunDto {
  run_id: string
  status: RunStatus
  bron: RunBron
  aangevraagd_op: string
  gestart_op: string | null
  afgerond_op: string | null
  exit_code: number | null
  samenvatting: SamenvattingDto | null
  fout_reden: string | null
  mail_status: MailStatus | null
  mail_detail: string | null
}

export type BevindingSoort = 'afwijking' | 'let_op' | 'fout' | 'geaccepteerd' | 'uitgesloten' | 'gezien'
/** Facet in de URL: 'aandacht' (default) = afwijking + fout + let-op. */
export type SoortFacet = 'aandacht' | BevindingSoort | 'alle'
/** 'rlz_dubbel' (blok 6, 08-09) = periodieke toets "mogelijk dubbel geboekt in RLZ" — handeling ligt in Reeleezee. */
export type BevindingBlok = 'bank' | 'documenten' | 'omzet' | 'doorbelasting' | 'run' | 'automatisering' | 'rlz_dubbel'

export interface BevindingDto {
  id: string
  run_id: string
  blok: BevindingBlok
  soort: BevindingSoort
  /** null = administratie-loze blokfout (bv. de run zelf viel om). */
  administratie_id: string | null
  administratie_naam: string | null
  vingerafdruk: string
  /** Letterlijk de CLI-regel (technisch, mét GUID's) — alleen nog zichtbaar in de uitklap "details". */
  tekst: string
  /** Leesbare laag (07-09, blok A8): korte titel met namen, één zin "wat is er", één zin "wat doe je". */
  titel: string
  wat: string
  doe: string
  /** Technische sleutels (vingerafdruk, record-id's, ruwe regel) voor de uitklap — nooit in titel/wat/doe. */
  details: { label: string; waarde: string }[]
  sinds: string
  nieuw: boolean
  acceptatie: { reden: string; geaccepteerd_op: string; geaccepteerd_door_naam: string | null } | null
  gezien: { reden: string; gezien_op: string; vervalt_op: string; gezien_door_naam: string | null } | null
  detail: Record<string, unknown> | null
  doel_pad: string | null
}

export interface BevindingenTellersDto {
  afwijkingen: number
  let_op: number
  fouten: number
  geaccepteerd: number
  uitgesloten: number
  gezien: number
  administraties: number
}

export interface BevindingenLijstDto {
  rijen: BevindingDto[]
  totaal: number
  pagina: number
  per_pagina: number
  administraties_in_selectie: number
  tellers: BevindingenTellersDto
  facetten: {
    soort: Record<string, number>
    administraties: { administratie_id: string; naam: string; aantal: number }[]
  }
  laatste_run: ReconciliatieRunDto | null
}

export interface StandDto {
  teller: number
  afwijkingen: number
  let_op: number
  fouten: number
  laatste_run: ReconciliatieRunDto | null
}

export interface InstellingDto {
  gezien_dagen: number
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/** KPI-kaart op de werkvoorraad (best-effort: een fout hier blokkeert niets). */
export function haalStand(): Promise<StandDto> {
  return apiJson('/reconciliatie/stand')
}

export function haalBevindingen(params: {
  pagina: number
  q?: string
  administratieId?: string | null
  soort?: SoortFacet
}): Promise<BevindingenLijstDto> {
  const p = new URLSearchParams()
  p.set('pagina', String(params.pagina))
  p.set('soort', params.soort ?? 'aandacht')
  if (params.q) p.set('q', params.q)
  if (params.administratieId) p.set('administratie_id', params.administratieId)
  return apiJson(`/reconciliatie/bevindingen?${p.toString()}`)
}

function redenActie(pad: string, administratieId: string, reden: string): Promise<{ id: string }> {
  return apiJson(pad, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ administratie_id: administratieId, reden }) })
}

/** Afwijking accepteren = Beheerder-only, altijd mét inhoudelijke reden (audit). */
export function accepteerBevinding(id: string, administratieId: string, reden: string): Promise<{ id: string }> {
  return redenActie(`/reconciliatie/bevindingen/${id}/accepteren`, administratieId, reden)
}

export function trekAcceptatieIn(id: string, administratieId: string, reden: string): Promise<{ id: string }> {
  return redenActie(`/reconciliatie/bevindingen/${id}/intrekken`, administratieId, reden)
}

/** "Gezien" = tijdelijk wegleggen van een let-op-melding; vervalt vanzelf na N dagen. */
export function markeerGezien(id: string, administratieId: string, reden: string): Promise<{ id: string }> {
  return redenActie(`/reconciliatie/bevindingen/${id}/gezien`, administratieId, reden)
}

export function gezienIntrekken(id: string, administratieId: string, reden: string): Promise<{ id: string }> {
  return redenActie(`/reconciliatie/bevindingen/${id}/gezien-intrekken`, administratieId, reden)
}

/** 202 + status-poll (bank_sync_run-patroon) — Beheerder-only. */
export function startRun(): Promise<ReconciliatieRunDto> {
  return apiJson('/reconciliatie/run', { method: 'POST' })
}

export function haalRunStatus(runId: string): Promise<ReconciliatieRunDto> {
  return apiJson(`/reconciliatie/run/${runId}`)
}

export function haalLaatsteRun(): Promise<ReconciliatieRunDto | null> {
  return apiJson('/reconciliatie/run/laatste')
}

export function haalInstelling(): Promise<InstellingDto> {
  return apiJson('/reconciliatie/instelling')
}

export function zetInstelling(gezienDagen: number): Promise<InstellingDto> {
  return apiJson('/reconciliatie/instelling', {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ gezien_dagen: gezienDagen }),
  })
}

export const SOORT_FACETTEN: SoortFacet[] = [
  'aandacht',
  'afwijking',
  'let_op',
  'fout',
  'geaccepteerd',
  'uitgesloten',
  'gezien',
  'alle',
]

export const SOORT_LABEL: Record<SoortFacet, string> = {
  aandacht: 'aandacht nodig',
  afwijking: 'afwijkingen',
  let_op: 'let-op',
  fout: 'fouten',
  geaccepteerd: 'geaccepteerd',
  uitgesloten: 'uitgesloten',
  gezien: 'gezien',
  alle: 'alle',
}

export const BLOK_LABEL: Record<BevindingBlok, string> = {
  bank: 'Bank',
  documenten: 'Documenten',
  omzet: 'Omzet',
  doorbelasting: 'Doorbelasting',
  run: 'Run',
  automatisering: 'Automatisering',
  rlz_dubbel: 'Dubbel in RLZ',
}

/** Leesbare labels van de reden-categorieën (spiegel van REDEN_LABEL in automatiseringen.py). */
export const REDEN_LABEL: Record<string, string> = {
  geen_eigenaar: 'geen eigenaar/toewijzing',
  volumerem: 'volumerem bereikt',
  geldpoort: 'boeken staat uit',
  credential: 'geen werkende credential',
  api_key: 'geen API-key',
  noodrem: 'noodrem staat uit',
  harde_checks: 'harde checks blokkeren',
  mens_beoordeelt: 'mens beoordeelt',
  extractie_onvolledig: 'extractie onvolledig',
  geheugen_oranje: 'geheugen niet bevestigd',
  urenmatch: 'urenmatch niet groen',
  duplicaatsignaal: 'duplicaatsignaal',
  boekfout: 'boekfout',
  half_geboekt: 'half geboekt',
  twijfel: 'twijfel',
  fout: 'fout',
  regel_overgeslagen: 'regel overgeslagen',
  zacht_signaal: 'zacht signaal — mens beoordeelt',
  stil_7_dagen: 'zeven dagen stil',
}

export const STAND_LABEL: Record<AutomatiseringTellerDto['stand'], string> = {
  aan: 'aan',
  uit: 'uit',
  deels: 'deels aan',
  altijd: 'aan',
  op_aanvraag: 'op aanvraag',
}

export const MAIL_LABEL: Record<MailStatus, string> = {
  niet_nodig: 'niet nodig',
  verzonden: 'verzonden',
  mislukt: 'mislukt',
  niet_geconfigureerd: 'niet geconfigureerd',
}
