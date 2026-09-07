// Crediteuren-dubbelen v2 → schaalbaar (design-ronde 03-09; blok B13 07-09) — spiegelt backend/app/crediteuren/schemas.py.
// Kantoorbreed; administratie is een filter, geen poort. Geen RLZ-calls: verliezers worden in de MODULE onbruikbaar,
// de RLZ-opruimlijst is een optionele CSV-export.
import { apiFetch, apiJson } from '../api/client'

export type SleutelSoort = 'btw_nummer' | 'kvk_nummer' | 'iban' | 'naam'
export type Classificatie = 'twijfel' | 'eenduidig'

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
  eenduidig: boolean
  classificatie_reden: string
}

export interface TellersDto {
  clusters: number // twijfel — mens nodig
  eenduidig: number // automatisch afhandelbaar
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

export interface ClusterDetailDto {
  administratie_id: string
  administratie_naam: string
  crediteuren: KaartDto[]
  voorkeur_suggestie: string
  eenduidig: boolean
  classificatie_reden: string
}

export interface AfhandelUitkomstDto {
  afhandeling_id: string
  voorkeur_naam: string | null
  verliezer_namen: string[]
  geheugen_verhuisd: number
  kenmerk_verhuisd: boolean
  ibans_verhuisd: number
  boekvoorstellen_hervertaald: number
  melding: string
}

export interface VoorbeeldDto {
  cluster_id: string
  voorkeur_naam: string | null
  verliezer_namen: string[]
  reden: string
  afgehandeld: boolean
  fout: string | null
}

export interface AdministratieUitkomstDto {
  administratie_id: string
  administratie_naam: string
  eenduidig: number
  twijfel: number
  afgehandeld: number
  fouten: number
  voorbeelden: VoorbeeldDto[]
}

export interface AutoRunDto {
  run_id: string
  dry_run: boolean
  eenduidig: number
  twijfel: number
  afgehandeld: number
  fouten: number
  administraties: AdministratieUitkomstDto[]
}

export interface AfhandelingRegelDto {
  id: string
  administratie_id: string
  administratie_naam: string
  bron: 'auto' | 'mens'
  voorkeur_vendor_id: string
  voorkeur_naam: string | null
  verliezers: { vendor_id: string; naam: string | null }[]
  sleutels: { soort: SleutelSoort; sleutel: string }[]
  classificatie_reden: string
  geheugen_verhuisd: number
  kenmerk_verhuisd: boolean
  ibans_verhuisd: number
  boekvoorstellen_hervertaald: number
  afgehandeld_op: string
  teruggedraaid_op: string | null
  teruggedraaid_reden: string | null
}

export interface AfhandelingenDto {
  regels: AfhandelingRegelDto[]
  actief: number
  teruggedraaid: number
}

export function haalDubbelenOp(opties: {
  pagina: number
  q: string
  administratieId: string
  sleutel: string
  classificatie?: Classificatie | ''
}): Promise<LijstDto> {
  const params = new URLSearchParams({ pagina: String(opties.pagina) })
  if (opties.q) params.set('q', opties.q)
  if (opties.administratieId) params.set('administratie_id', opties.administratieId)
  if (opties.sleutel) params.set('sleutel', opties.sleutel)
  if (opties.classificatie) params.set('classificatie', opties.classificatie)
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

export function handelClusterAf(administratieId: string, voorkeurVendorId: string, verliezerVendorIds: string[]): Promise<AfhandelUitkomstDto> {
  return apiJson<AfhandelUitkomstDto>(`/crediteuren/dubbelen/${administratieId}/afhandelen`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ voorkeur_vendor_id: voorkeurVendorId, verliezer_vendor_ids: verliezerVendorIds }),
  })
}

export function meldClusterAf(administratieId: string, vendorIds: string[], reden: string): Promise<{ afmelding_id: string }> {
  return apiJson<{ afmelding_id: string }>(`/crediteuren/dubbelen/${administratieId}/afmelden`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ vendor_ids: vendorIds, reden }),
  })
}

export function autoAfhandelen(opties: { dryRun: boolean; administratieId?: string }): Promise<AutoRunDto> {
  return apiJson<AutoRunDto>('/crediteuren/dubbelen/auto-afhandelen', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dry_run: opties.dryRun, administratie_id: opties.administratieId || null }),
  })
}

export function haalAfhandelingenOp(): Promise<AfhandelingenDto> {
  return apiJson<AfhandelingenDto>('/crediteuren/afhandelingen')
}

export function draaiAfhandelingTerug(afhandelingId: string, reden: string): Promise<AfhandelingRegelDto> {
  return apiJson<AfhandelingRegelDto>(`/crediteuren/afhandelingen/${afhandelingId}/terugdraaien`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reden }),
  })
}

/** RLZ-opruimlijst als CSV — via fetch + blob (de frontend navigeert nooit rechtstreeks naar een API-URL). */
export async function haalOpruimlijstCsvOp(): Promise<Blob> {
  const resp = await apiFetch('/crediteuren/opruimlijst.csv')
  if (!resp.ok) throw new Error(`Export mislukt (${resp.status})`)
  return resp.blob()
}
