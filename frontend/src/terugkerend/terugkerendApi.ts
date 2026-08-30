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
