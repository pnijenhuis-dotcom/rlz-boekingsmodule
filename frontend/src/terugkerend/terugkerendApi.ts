// Terugkerende-facturen-signaal (blok B 30-08, benchmark gap #3) — spiegelt backend/app/terugkerend/schemas.py.
// Bedragen/percentages als string (Decimal); de client formatteert alleen, rekent niets.
import { apiFetch, apiJson } from '../api/client'

export type TerugkerendStatus = 'ontbreekt' | 'op_schema' | 'gesnoozed' | 'afgemeld'

export interface TerugkerendSignaalDto {
  id: string
  vendor_id: string
  leverancier: string | null
  patroon: 'maand' | 'kwartaal'
  interval_dagen: number
  aantal_facturen: number
  laatste_datum: string
  laatste_bedrag: string | null
  laatste_document_id: string | null
  vorige_datum: string | null
  vorige_bedrag: string | null
  verwacht_op: string
  uiterlijk_op: string
  ontbreekt_sinds: string | null
  dagen_te_laat: number | null
  prijsstijging_pct: string | null
  snooze_tot: string | null
  afgemeld_op: string | null
  status: TerugkerendStatus
  berekend_op: string
}

export interface TerugkerendOverzichtDto {
  administratie_id: string
  prijsstijging_drempel_pct: string
  signalen: TerugkerendSignaalDto[]
}

export interface DocumentTerugkerendSignaalDto {
  prijsstijging_pct: string | null
  vorige_bedrag: string | null
  vorige_datum: string | null
  laatste_bedrag: string | null
  patroon: string | null
  leverancier: string | null
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export function haalTerugkerendOverzicht(administratieId: string): Promise<TerugkerendOverzichtDto> {
  return apiJson(`/administraties/${administratieId}/terugkerend`)
}

export function herberekenTerugkerend(administratieId: string): Promise<{ terugkerend: number; ontbreekt: number; prijsstijging: number; vervallen: number }> {
  return apiJson(`/administraties/${administratieId}/terugkerend/herbereken`, { method: 'POST' })
}

export async function snoozeTerugkerend(administratieId: string, vendorId: string, tot: string | null): Promise<void> {
  await apiFetch(`/administraties/${administratieId}/terugkerend/${vendorId}/snooze`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ tot }),
  })
}

export async function zetTerugkerendAfgemeld(administratieId: string, vendorId: string, afgemeld: boolean): Promise<void> {
  await apiFetch(`/administraties/${administratieId}/terugkerend/${vendorId}/afmelden`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ afgemeld }),
  })
}

export function zetTerugkerendDrempel(administratieId: string, prijsstijgingPct: string): Promise<{ prijsstijging_pct: string }> {
  return apiJson(`/administraties/${administratieId}/terugkerend-instelling`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ prijsstijging_pct: prijsstijgingPct }),
  })
}

export function haalDocumentTerugkerendSignaal(administratieId: string, documentId: string): Promise<DocumentTerugkerendSignaalDto> {
  return apiJson(`/administraties/${administratieId}/documenten/${documentId}/terugkerend-signaal`)
}

export const STATUS_LABEL: Record<TerugkerendStatus, string> = {
  ontbreekt: 'verwachte factuur ontbreekt',
  op_schema: 'op schema',
  gesnoozed: 'gesnoozed',
  afgemeld: 'afgemeld',
}

export function patroonLabel(p: TerugkerendSignaalDto['patroon'], interval: number): string {
  return `${p === 'maand' ? 'maandelijks' : 'per kwartaal'} (≈ ${interval} d)`
}

// --- kantoorbreed (design-ronde 03-09 blok B1, mockup inzicht-kantoorbreed ①②③) --------------------
// Spiegelt backend/app/terugkerend/schemas.py (KantoorLijstDto, HerberekenRunDto, ConceptMailDto).
// Eén rij = één signaal (ontbreekt óf prijsstijging) met precies één handeling.

export type KantoorSoort = 'ontbreekt' | 'prijsstijging'
export type KantoorStatus = 'aandacht' | 'gesnoozed' | 'afgemeld'
export type KantoorStatusFacet = KantoorStatus | 'alle'

export interface KantoorRijDto {
  administratie_id: string
  administratie_naam: string
  vendor_id: string
  leverancier: string | null
  soort: KantoorSoort
  status: KantoorStatus
  patroon: 'maand' | 'kwartaal'
  interval_dagen: number
  aantal_facturen: number
  laatste_datum: string
  laatste_bedrag: string | null
  laatste_document_id: string | null
  vorige_datum: string | null
  vorige_bedrag: string | null
  verwacht_op: string
  uiterlijk_op: string
  dagen_te_laat: number | null
  prijsstijging_pct: string | null
  snooze_tot: string | null
  afgemeld_op: string | null
  berekend_op: string
}

export interface KantoorLijstDto {
  rijen: KantoorRijDto[]
  totaal: number
  pagina: number
  per_pagina: number
  administraties_in_selectie: number
  tellers: { ontbrekend: number; prijsstijging: number; administraties: number }
  facetten: {
    status: Record<string, number>
    administraties: { administratie_id: string; naam: string; aantal: number }[]
  }
}

export interface HerberekenRunDto {
  run_id: string
  status: 'wachtend' | 'bezig' | 'klaar' | 'fout'
  aangevraagd_op: string
  gestart_op: string | null
  klaar_op: string | null
  aantal_administraties: number
  aantal_verwerkt: number
  aantal_fouten: number
  foutreden: string | null
  resultaat: Record<string, unknown> | null
}

export interface ConceptMailDto {
  ontvanger_e_mail: string | null
  leverancier: string | null
  administratie_naam: string
  onderwerp: string
  tekst: string
}

export function haalKantoorSignalen(params: {
  pagina: number
  q?: string
  administratieId?: string | null
  status?: KantoorStatusFacet
}): Promise<KantoorLijstDto> {
  const p = new URLSearchParams()
  p.set('pagina', String(params.pagina))
  p.set('status', params.status ?? 'aandacht')
  if (params.q) p.set('q', params.q)
  if (params.administratieId) p.set('administratie_id', params.administratieId)
  return apiJson(`/terugkerend/signalen?${p.toString()}`)
}

export function startHerberekenAlles(): Promise<HerberekenRunDto> {
  return apiJson('/terugkerend/herbereken', { method: 'POST' })
}

export function haalHerberekenStatus(runId: string): Promise<HerberekenRunDto> {
  return apiJson(`/terugkerend/herbereken/${runId}`)
}

export function haalLaatsteHerbereken(): Promise<HerberekenRunDto | null> {
  return apiJson('/terugkerend/herbereken/laatste')
}

export function haalConceptMail(administratieId: string, vendorId: string): Promise<ConceptMailDto> {
  return apiJson(`/terugkerend/${administratieId}/${vendorId}/conceptmail`)
}

export function verstuurConceptMail(
  administratieId: string,
  vendorId: string,
  invoer: { naar: string; onderwerp: string; tekst: string },
): Promise<{ verzonden_aan: string }> {
  return apiJson(`/terugkerend/${administratieId}/${vendorId}/conceptmail/versturen`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(invoer),
  })
}

export const KANTOOR_STATUS_LABEL: Record<KantoorStatusFacet, string> = {
  aandacht: 'aandacht nodig',
  gesnoozed: 'gesnoozed',
  afgemeld: 'afgemeld',
  alle: 'alle',
}
