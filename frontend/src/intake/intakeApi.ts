import { apiFetch, apiJson, apiPostJson } from '../api/client'

export interface SplitsSegmentDto {
  start_pagina: number
  eind_pagina: number
  tenaamstelling: string | null
  leverancier: string | null
  factuurnummer: string | null
  zekerheid: number
}

export interface VerzamelbakItemDto {
  document_id: string
  bestandsnaam: string
  soort: string
  bron: string
  afzender_hint: string | null
  tenaamstelling: string | null
  suggestie_administratie_id: string | null
  suggestie_bron: string | null
  aangemaakt_op: string
  splitsing_id: string | null
  splitsing_voorstel: SplitsSegmentDto[] | null
}

export interface VerzamelbakLijstDto {
  items: VerzamelbakItemDto[]
}

export interface IntakeBijlageResultaatDto {
  bestandsnaam: string
  uitkomst: string
  document_id: string | null
  detail: string | null
}

export interface IntakeVerwerkResponseDto {
  bericht_id: string | null
  al_eerder_verwerkt: boolean
  bijlagen: IntakeBijlageResultaatDto[]
}

export function haalVerzamelbakOp(): Promise<VerzamelbakLijstDto> {
  return apiJson<VerzamelbakLijstDto>('/verzamelbak')
}

export interface VerzamelbakBestand {
  /** Object-URL van de blob (Authorization-header vereist — een kale <object src> kan niet). */
  url: string
  contentType: string
}

/** Bestand van een verzamelbak-document (D1, besluit 25-08): lazy — pas bij hover/klik. */
export async function haalVerzamelbakBestandBlob(documentId: string): Promise<VerzamelbakBestand> {
  const resp = await apiFetch(`/verzamelbak/${documentId}/bestand`)
  if (!resp.ok) throw new Error(`Bestand niet te laden (${resp.status})`)
  const blob = await resp.blob()
  return { url: URL.createObjectURL(blob), contentType: blob.type }
}

export function verwerkEml(bestand: File): Promise<IntakeVerwerkResponseDto> {
  const formData = new FormData()
  formData.append('bestand', bestand)
  return apiJson<IntakeVerwerkResponseDto>('/intake/eml', { method: 'POST', body: formData })
}

export function wijsToe(documentId: string, administratieId: string): Promise<unknown> {
  return apiPostJson(`/verzamelbak/${documentId}/toewijzen`, { administratie_id: administratieId })
}

export function hoortNietBijOns(documentId: string, reden: string): Promise<unknown> {
  return apiPostJson(`/verzamelbak/${documentId}/hoort-niet-bij-ons`, { reden })
}

export function bevestigSplitsing(
  splitsingId: string,
  delen: { start_pagina: number; eind_pagina: number; tenaamstelling: string | null }[],
): Promise<unknown> {
  return apiPostJson(`/intake/splitsingen/${splitsingId}/bevestigen`, { delen })
}

export function wijsSplitsingAf(splitsingId: string, reden: string | null): Promise<unknown> {
  return apiPostJson(`/intake/splitsingen/${splitsingId}/afwijzen`, { reden })
}
