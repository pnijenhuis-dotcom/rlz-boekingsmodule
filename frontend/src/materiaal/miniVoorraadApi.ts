// Mini-voorraad speciale producten (opdracht Peter 06-09, mockup mini-voorraad.html ①–⑧ = norm) —
// spiegelt backend/app/mini_voorraad/schemas.py (CONTRACT_F). Kernbesluit ⑧: MENS-MANIPULATIE
// ONMOGELIJK — geen enkele call hier muteert een stand; de stand is Σ van append-only mutaties die
// elk aan een brondocument (instroom/storno) of een geregistreerde gebeurtenis (beschadiging mét
// verplicht project) hangen. Aantallen als string (Decimal) — de client formatteert alleen.
import { apiJson } from '../api/client'

export type MutatieSoort = 'instroom' | 'storno' | 'uitstroom' | 'beschadiging'
export type ProductFilter = 'alle' | 'nieuw' | 'gearchiveerd'

export interface MiniProductDto {
  id: string
  administratie_id: string
  vendor_id: string
  leverancier_naam: string | null
  artikelcode: string | null
  /** LETTERLIJK de factuurtekst — óók de match-sleutel (⑦); nooit te wijzigen. */
  omschrijving: string
  /** Alleen via "Naam bevestigen" — verandert de weergave, nooit een aantal. */
  weergavenaam: string | null
  eenheid: string | null
  nieuw_controleren: boolean
  gearchiveerd: boolean
  /** Decimal als string, max 3 decimalen ("96", "12.5"). */
  stand: string
  laatste_mutatie_op: string | null
  aangemaakt_op: string
}

export interface ProductLijstDto {
  items: MiniProductDto[]
  totaal: number
  pagina: number
  per_pagina: number
  nieuw_controleren: number
  ingeschakeld: boolean
}

export interface MutatieDto {
  id: string
  soort: MutatieSoort
  /** Getekend: instroom +, storno/uitstroom/beschadiging −. */
  aantal: string
  datum: string
  document_id: string | null
  document_referentie: string | null
  document_leverancier: string | null
  boek_cyclus: number | null
  project_id: string | null
  project_naam: string | null
  gemeld_door_naam: string | null
  toelichting: string | null
  aangemaakt_op: string
}

export interface LogLijstDto {
  items: MutatieDto[]
  totaal: number
  pagina: number
  per_pagina: number
}

export interface StandDto {
  ingeschakeld: boolean
  producten: number
  nieuw_controleren: number
}

/** Materiaallijst-item (F5, planning/transport): read-only weergave mét stand — eigen leesroute
 * `GET /mini-voorraad/{aid}/materiaallijst` (de catalogus-DTO is niet uitgebreid; backend-keuze 06-09). */
export interface MateriaallijstItemDto {
  id: string
  naam: string
  eenheid: string | null
  mini_voorraad_stand: string | null
  leverancier_naam?: string | null
  artikelcode?: string | null
}

export interface MateriaallijstDto {
  categorie: string
  items: MateriaallijstItemDto[]
}

export const PER_PAGINA = 25

export const SOORT_LABEL: Record<MutatieSoort, string> = {
  instroom: 'instroom',
  storno: 'storno',
  uitstroom: 'uitstroom',
  beschadiging: 'beschadiging',
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export function haalStand(administratieId: string): Promise<StandDto> {
  return apiJson(`/mini-voorraad/${administratieId}/stand`)
}

export function haalProducten(
  administratieId: string,
  params: { pagina: number; q?: string; filter?: ProductFilter },
): Promise<ProductLijstDto> {
  const p = new URLSearchParams()
  p.set('pagina', String(params.pagina))
  p.set('filter', params.filter ?? 'alle')
  if (params.q) p.set('q', params.q)
  return apiJson(`/mini-voorraad/${administratieId}/producten?${p.toString()}`)
}

export function haalLog(administratieId: string, productId: string, pagina = 1): Promise<LogLijstDto> {
  return apiJson(`/mini-voorraad/${administratieId}/producten/${productId}/log?pagina=${pagina}`)
}

/** Wijzigt uitsluitend de WEERGAVENAAM (vlag "nieuw — controleer" gaat uit); de factuurtekst blijft de sleutel. */
export function bevestigNaam(administratieId: string, productId: string, weergavenaam: string): Promise<MiniProductDto> {
  return apiJson(`/mini-voorraad/${administratieId}/producten/${productId}/naam-bevestigen`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ weergavenaam }),
  })
}

/** Beheerder — archiveren, nooit verwijderen (⑥); de stand en het log blijven. */
export function archiveerProduct(administratieId: string, productId: string, reden: string): Promise<MiniProductDto> {
  return apiJson(`/mini-voorraad/${administratieId}/producten/${productId}/archiveren`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ reden }),
  })
}

export function dearchiveerProduct(administratieId: string, productId: string): Promise<MiniProductDto> {
  return apiJson(`/mini-voorraad/${administratieId}/producten/${productId}/dearchiveren`, { method: 'POST' })
}

/** Beschadiging = gebeurtenisregistratie (wie/waar/wanneer): project VERPLICHT; de server toetst het
 * project tegen de actieve project_cache van de administratie (422 leesbaar). Aantal > 0 als string;
 * de server slaat 'm negatief op. */
export function meldBeschadiging(
  administratieId: string,
  body: { product_id: string; aantal: string; project_id: string; datum: string; toelichting: string | null },
): Promise<MutatieDto> {
  return apiJson(`/mini-voorraad/${administratieId}/beschadigingen`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  })
}

/** Mini-producten mét stand > 0 voor de Materiaallijst-dialoog (planning/transport). Best-effort bij de
 * aanroeper: opt-in uit = 409, dat blokkeert niets. */
export function haalMateriaallijst(administratieId: string): Promise<MateriaallijstItemDto[]> {
  return apiJson<MateriaallijstDto>(`/mini-voorraad/${administratieId}/materiaallijst`).then((d) => d.items)
}

/** Weergavenaam als er een bevestigde is, anders de letterlijke factuurtekst. */
export function productNaam(p: { weergavenaam: string | null; omschrijving: string }): string {
  return p.weergavenaam?.trim() ? p.weergavenaam : p.omschrijving
}

/** Decimal-string → nl-NL, max 3 decimalen, zonder overbodige nullen ("96", "12,5"). */
export function aantalTekst(waarde: string | null | undefined): string {
  if (waarde === null || waarde === undefined || waarde === '') return '—'
  const n = Number(waarde)
  if (!Number.isFinite(n)) return waarde
  return n.toLocaleString('nl-NL', { maximumFractionDigits: 3 })
}

/** Getekend aantal voor het log: "+24" / "−4" (typografisch minteken). */
export function getekendAantal(waarde: string): string {
  const n = Number(waarde)
  if (!Number.isFinite(n)) return waarde
  const abs = Math.abs(n).toLocaleString('nl-NL', { maximumFractionDigits: 3 })
  return n < 0 ? `−${abs}` : `+${abs}`
}

/** Deep-link naar het controlescherm van het bron-document (bestaand pad, zelfde vorm als het
 * duplicaat-spoor in DocumentDetailScreen). */
export function documentPad(administratieId: string, documentId: string): string {
  return `/documenten/${administratieId}/${documentId}`
}
