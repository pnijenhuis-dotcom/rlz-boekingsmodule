// Afdelingen binnen een administratie (bouwrun 28-08 blok A, mockup afdelingen.html). Alle paden
// absoluut onder /administraties (bestaande proxy-prefix). Lezen = administratie-scope (het
// controlescherm), schrijven = Beheerder-only (Instellingen › Administraties).
import { apiFetch, apiJson } from '../api/client'

export interface RouteLaagDto {
  volgnummer: number
  accordeur_gebruiker_id: string
  accordeur_naam: string | null
  bedrag_drempel: string | null
}

export interface AfdelingDto {
  id: string
  naam: string
  /** Terugval "Algemeen": volgt de accorderingsroute van de administratie, niet archiveerbaar. */
  is_terugval: boolean
  actief: boolean
  /** Eigen route (leeg bij de terugval). */
  route: RouteLaagDto[]
  staande_goedkeuringen: number
  gearchiveerd_op: string | null
}

export interface AfdelingenLijstDto {
  ingeschakeld: boolean
  afdelingen: AfdelingDto[]
}

export interface AfdelingRouteDto {
  afdeling_id: string
  lagen: RouteLaagDto[]
  rondes_vervallen: number
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export function haalAfdelingen(administratieId: string): Promise<AfdelingenLijstDto> {
  return apiJson(`/administraties/${administratieId}/afdelingen`)
}

export function zetAfdelingenInstelling(administratieId: string, ingeschakeld: boolean): Promise<{ ingeschakeld: boolean }> {
  return apiJson(`/administraties/${administratieId}/afdelingen-instelling`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ ingeschakeld }),
  })
}

export function maakAfdelingAan(administratieId: string, naam: string): Promise<AfdelingDto> {
  return apiJson(`/administraties/${administratieId}/afdelingen`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ naam }),
  })
}

export async function archiveerAfdeling(administratieId: string, afdelingId: string): Promise<void> {
  await apiFetch(`/administraties/${administratieId}/afdelingen/${afdelingId}/archiveren`, { method: 'POST' })
}

export function zetAfdelingRoute(
  administratieId: string,
  afdelingId: string,
  lagen: { volgnummer: number; accordeur_gebruiker_id: string; bedrag_drempel: string | null }[],
): Promise<AfdelingRouteDto> {
  return apiJson(`/administraties/${administratieId}/afdelingen/${afdelingId}/accordering/route`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ lagen }),
  })
}

/** Leesbare samenvatting van een route (mockup: "Laag 1 · R. de Groot → Laag 2 · P. Kempen > € 5.000"). */
export function routeSamenvatting(lagen: RouteLaagDto[]): string {
  return lagen
    .map((laag) => {
      const naam = laag.accordeur_naam ?? 'onbekende accordeur'
      const drempel = laag.bedrag_drempel ? ` > € ${Number(laag.bedrag_drempel).toLocaleString('nl-NL')}` : ''
      return `Laag ${laag.volgnummer} · ${naam}${drempel}`
    })
    .join(' → ')
}
