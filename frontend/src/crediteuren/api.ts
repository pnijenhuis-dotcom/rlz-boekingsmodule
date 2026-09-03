// Crediteuren-dubbelen v2 (design-ronde 03-09, mockup crediteuren-dubbelen-v2.html) — spiegelt
// backend/app/crediteuren/schemas.py. Kantoorbreed; administratie is een filter, geen poort. Bedragen als
// string (Decimal); de client formatteert alleen.
import { apiJson } from '../api/client'

export type SleutelSoort = 'btw_nummer' | 'kvk_nummer' | 'iban' | 'naam'

export const SLEUTEL_LABEL: Record<SleutelSoort, string> = {
  btw_nummer: 'btw-nummer',
  kvk_nummer: 'KvK-nummer',
  iban: 'IBAN',
  naam: 'naam',
}

export interface KaartDto {
  vendor_id: string
  naam: string | null
  btw_nummer: string | null
  kvk_nummer: string | null
  ibans: string[]
  aantal_boekingen: number
  laatst_geboekt: string | null
}

export interface KlaargezetDto {
  werklijst_id: string
  voorkeur_vendor_id: string
  namen: string[]
  aangemaakt_op: string
}

export interface ClusterDto {
  cluster_id: string
  administratie_id: string
  administratie_naam: string
  soort: SleutelSoort
  sleutel: string
  sleutels: { soort: SleutelSoort; sleutel: string }[]
  chips: string[]
  crediteuren: KaartDto[]
  aantal_boekingen: number
  laatst_geboekt: string | null
  kvk_verschilt: boolean
  afmelden_primair: boolean
  voorkeur_suggestie: string
  klaargezet: KlaargezetDto | null
}

export interface TellersDto {
  clusters: number
  klaargezet: number
  administraties: number
}

export interface FacettenDto {
  administraties: { administratie_id: string; naam: string; aantal: number }[]
  sleutels: Partial<Record<SleutelSoort, number>>
}

export interface LijstDto {
  rijen: ClusterDto[]
  totaal: number
  pagina: number
  per_pagina: number
  tellers: TellersDto
  facetten: FacettenDto
}

export interface OpenPostDto {
  rlz_document_id: string
  referentie: string | null
  datum: string | null
  open_bedrag: string
}

export interface ClusterDetailDto {
  administratie_id: string
  administratie_naam: string
  crediteuren: KaartDto[]
  voorkeur_suggestie: string
  open_posten: Record<string, OpenPostDto[]>
  toets_ok: boolean
  toets_fout: string | null
}

export interface ArchiveerUitkomstDto {
  werklijst_id: string
  voorkeur_naam: string | null
  te_archiveren_namen: string[]
  geheugen_verhuisd: number
  kenmerk_verhuisd: boolean
  ibans_verhuisd: number
  al_klaargezet: boolean
  melding: string
}

export interface WerklijstRegelDto {
  id: string
  administratie_id: string
  administratie_naam: string
  voorkeur_vendor_id: string
  voorkeur_naam: string | null
  te_archiveren: { vendor_id: string; naam: string | null }[]
  status: 'open' | 'gedaan'
  aangemaakt_op: string
  gedaan_op: string | null
  gedaan_bron: string | null
  laatste_hertoets_op: string | null
  hertoets_detail: Record<string, string> | null
}

export interface WerklijstDto {
  regels: WerklijstRegelDto[]
  open: number
  gedaan: number
}

export function haalDubbelenOp(opties: { pagina: number; q: string; administratieId: string; sleutel: string }): Promise<LijstDto> {
  const params = new URLSearchParams({ pagina: String(opties.pagina) })
  if (opties.q) params.set('q', opties.q)
  if (opties.administratieId) params.set('administratie_id', opties.administratieId)
  if (opties.sleutel) params.set('sleutel', opties.sleutel)
  return apiJson<LijstDto>(`/crediteuren/dubbelen?${params.toString()}`)
}

export function haalDubbelenStandOp(): Promise<TellersDto> {
  return apiJson<TellersDto>('/crediteuren/dubbelen/stand')
}

export function haalClusterDetailOp(administratieId: string, vendorIds: string[]): Promise<ClusterDetailDto> {
  const params = new URLSearchParams()
  for (const v of vendorIds) params.append('vendor_ids', v)
  return apiJson<ClusterDetailDto>(`/crediteuren/dubbelen/${administratieId}/cluster-detail?${params.toString()}`)
}

export function archiveerCluster(administratieId: string, voorkeurVendorId: string, overigeVendorIds: string[]): Promise<ArchiveerUitkomstDto> {
  return apiJson<ArchiveerUitkomstDto>(`/crediteuren/dubbelen/${administratieId}/archiveer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ voorkeur_vendor_id: voorkeurVendorId, overige_vendor_ids: overigeVendorIds }),
  })
}

export function meldClusterAf(administratieId: string, vendorIds: string[], reden: string): Promise<{ afmelding_id: string }> {
  return apiJson<{ afmelding_id: string }>(`/crediteuren/dubbelen/${administratieId}/afmelden`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ vendor_ids: vendorIds, reden }),
  })
}

export function haalWerklijstOp(): Promise<WerklijstDto> {
  return apiJson<WerklijstDto>('/crediteuren/werklijst')
}

export function markeerWerklijstGedaan(werklijstId: string): Promise<WerklijstRegelDto> {
  return apiJson<WerklijstRegelDto>(`/crediteuren/werklijst/${werklijstId}/gedaan`, { method: 'POST' })
}
