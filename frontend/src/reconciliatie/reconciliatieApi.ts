// Inzicht › Reconciliatie (opdracht 06-09) — spiegelt backend/app/reconciliatie/schemas.py.
// De dagelijkse reconciliatie-alles-run vergelijkt onze eigen boekingen met de werkelijke stand in
// Reeleezee; dit scherm maakt de uitkomst kantoorbreed zichtbaar mét precies één handeling per rij.
// De client formatteert alleen — tellers, sortering en paginering komen van de server.
import { apiJson } from '../api/client'

export type RunStatus = 'wachtend' | 'bezig' | 'klaar' | 'fout'
export type RunBron = 'scheduler' | 'cli' | 'handmatig'
export type MailStatus = 'niet_nodig' | 'verzonden' | 'mislukt' | 'niet_geconfigureerd'
/** Sinds 09-09 (bundel blok 1) draagt de run twee mailkanalen in één samengestelde waarde
 * "actie=<s>;systeem=<s>" (actie = kantoor-actiemail, systeem = beheer-systeemmail); oudere runs één kale status. */
export type MailStatusWaarde = MailStatus | string

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
  /** Blok 4 (10-09 avond, additief): vangnet-teller `ai_toets_overgeslagen` — soort boeking (bank_* | factuur_autoboeking)
   * en de server-deeplink naar de plek van de boekingen (bankscherm / documentenlijst); wint van DOEL_PAD_VOORWAARDE. */
  soort?: string | null
  doel_pad?: string | null
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
  /** Blok A bundel 10-09 (additief, sleutel-agnostisch): extra standen per automatisering. Voor `autoboek_leren`:
   * `{ lerend, actief, uitgezonderd, geactiveerd_24u, per_administratie: [...] }`. Bestaande tellers: null/ontbreekt. */
  detail?: Record<string, unknown> | null
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
  mail_status: MailStatusWaarde | null
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
  /** Blok 8 run 11-09: groepskenmerk als extra filter op de administratie-set (server-side `groep_id`). */
  groepId?: string | null
}): Promise<BevindingenLijstDto> {
  const p = new URLSearchParams()
  p.set('pagina', String(params.pagina))
  p.set('soort', params.soort ?? 'aandacht')
  if (params.q) p.set('q', params.q)
  if (params.administratieId) p.set('administratie_id', params.administratieId)
  if (params.groepId) p.set('groep_id', params.groepId)
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
  // Blok 1 bundel 08-09 — teller `bank_sync` (dagelijkse bank-sync, alle administraties).
  odoo_administratie: 'Odoo-administratie (bank niet via Reeleezee)',
  geen_credential_geregistreerd: 'geen webservice-login geregistreerd',
  geen_sync_run: 'geen bank-sync-run in het venster',
  // Blok A/B bundel 10-09 — AI-plausibiliteitstoets als poort: beide harde voorwaarde mét deeplink Intake-AI.
  avg_gate: 'AI staat uit (AVG-gate intake-AI)',
  kostengrens: 'AI-kostengrens bereikt',
  // Blok 4 (10-09 avond) — vangnet-teller `ai_toets_overgeslagen`: geboekt zónder AI-toets (technische uitval).
  ai_fout: 'AI-fout/timeout',
  zonder_ai_toets: 'geboekt zonder AI-toets — controleer steekproefsgewijs',
  // Blok 3.2 (10-09 avond) — teller `ai_toets_uit`: de platformbrede opt-out is actief (Instellingen › Boeken).
  ai_toets_uit: 'AI-toets facturen staat platformbreed uit (opt-out)',
}

/** Spiegel van DOEL_PAD in automatiseringen.py (blok 5, 08-09): waar de mens een ontbrekende harde voorwaarde
 * herstelt. Onbekende categorie → de bevinding op Inzicht › Reconciliatie (daar staat de server-deeplink). */
const DOEL_PAD_VOORWAARDE: Record<string, string> = {
  credential: '/instellingen/administraties/{aid}',
  geen_eigenaar: '/instellingen/administraties/{aid}',
  api_key: '/instellingen/intake-ai',
  avg_gate: '/instellingen/intake-ai',
  kostengrens: '/instellingen/intake-ai',
  geldpoort: '/instellingen/boeken',
  noodrem: '/instellingen/boeken',
  ai_toets_uit: '/instellingen/boeken',
  volumerem: '/instellingen/autoboeken',
  vangnet_scheduler: '/reconciliatie',
}

export function doelPadVoorVoorwaarde(categorie: string, administratieId: string | null): string {
  const pad = DOEL_PAD_VOORWAARDE[categorie] ?? '/reconciliatie?soort=let_op'
  if (!pad.includes('{aid}')) return pad
  return administratieId ? pad.replace('{aid}', administratieId) : '/instellingen/administraties'
}

/** Blok 4 (10-09 avond): een harde voorwaarde mét server-deeplink (`doel_pad`) wint van de client-spiegel. */
export function doelPadVoorHardeVoorwaarde(hv: HardeVoorwaardeDto): string {
  return hv.doel_pad?.trim() || doelPadVoorVoorwaarde(hv.categorie, hv.administratie_id)
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

const KANAAL_LABEL: Record<string, string> = { actie: 'actiemail', systeem: 'systeemmail' }

function mailLabel(s: string): string {
  return (MAIL_LABEL as Record<string, string>)[s] ?? s.replace(/_/g, ' ')
}

/** "actie=verzonden;systeem=niet_nodig" → "actiemail verzonden · systeemmail niet nodig"; een kale status
 * (run van vóór 09-09) → het bestaande label. Onbekende sleutels tonen de sleutel — nooit een crash. */
export function mailStatusTekst(waarde: MailStatusWaarde | null | undefined): string {
  if (!waarde) return ''
  if (!waarde.includes('=')) return mailLabel(waarde)
  return waarde
    .split(';')
    .map((deel) => {
      const [kanaal, status] = deel.split('=')
      if (!kanaal || !status) return null
      return `${KANAAL_LABEL[kanaal] ?? kanaal} ${mailLabel(status)}`
    })
    .filter((x): x is string => x !== null)
    .join(' · ')
}
