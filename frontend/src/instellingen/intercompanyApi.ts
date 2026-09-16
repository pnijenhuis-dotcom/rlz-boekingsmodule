import { apiJson } from '../api/client'

/** Intercompany-relaties + rekening-courant-koppelingen (blok A opdracht 16-09) — Beheerder-only routes onder
 * `/intercompany/…`. De relaties worden AFGELEID (kvk > btw > naam, doorbelasting-mapping = bevestigd); de Beheerder
 * corrigeert alleen (bevestigen / uitsluiten mét reden / terug naar afgeleid). */

export type IcStatus = 'afgeleid' | 'bevestigd' | 'uitgesloten'

export interface IntercompanyRelatieDto {
  id: string
  administratie_a_id: string
  administratie_a_naam: string
  entity_in_a: string
  entity_naam: string | null
  administratie_b_id: string
  administratie_b_naam: string
  richting: 'crediteur' | 'debiteur'
  basis: 'kvk' | 'btw' | 'naam' | 'doorbelasting'
  status: IcStatus
  bron: 'afgeleid' | 'mens'
  reden: string | null
  gewijzigd_op: string | null
  actief: boolean
}

export interface RcKoppelingDto {
  id: string
  administratie_a_id: string
  administratie_a_naam: string
  rekening_a: string
  rekening_a_code: string | null
  rekening_a_naam: string | null
  administratie_b_id: string
  administratie_b_naam: string
  rekening_b: string | null
  rekening_b_code: string | null
  rekening_b_naam: string | null
  basis: 'naam' | 'afkorting' | 'mens'
  status: IcStatus
  bron: 'afgeleid' | 'mens'
  reden: string | null
  gewijzigd_op: string | null
  actief: boolean
}

export interface IdentiteitDto {
  administratie_id: string
  administratie_naam: string
  naam: string | null
  kvk: string | null
  btw: string | null
  bron: string
  afkortingen: string[]
  gelezen_op: string | null
}

export interface AfleidenResultaatDto {
  identiteiten: Record<string, number>
  identiteit_meldingen: string[]
  relaties: { relaties_nieuw: number; relaties_bijgewerkt: number; relaties_ongewijzigd: number; [k: string]: unknown }
  rc_koppelingen: { koppelingen_nieuw: number; koppelingen_bijgewerkt: number; zonder_tegenrekening: number; [k: string]: unknown }
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export function haalIntercompanyRelaties(): Promise<{ relaties: IntercompanyRelatieDto[] }> {
  return apiJson('/intercompany/relaties')
}

export function zetIntercompanyRelatieStatus(id: string, status: IcStatus, reden: string | null): Promise<IntercompanyRelatieDto> {
  return apiJson(`/intercompany/relaties/${id}`, { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify({ status, reden }) })
}

export function haalRcKoppelingen(): Promise<{ koppelingen: RcKoppelingDto[]; identiteiten: IdentiteitDto[] }> {
  return apiJson('/intercompany/rc-koppelingen')
}

export function zetRcKoppelingStatus(id: string, status: IcStatus, reden: string | null): Promise<RcKoppelingDto> {
  return apiJson(`/intercompany/rc-koppelingen/${id}`, { method: 'PUT', headers: JSON_HEADERS, body: JSON.stringify({ status, reden }) })
}

export function zetAfkortingen(administratieId: string, afkortingen: string[]): Promise<IdentiteitDto> {
  return apiJson(`/intercompany/identiteit/${administratieId}/afkortingen`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ afkortingen }),
  })
}

export function intercompanyAfleiden(): Promise<AfleidenResultaatDto> {
  return apiJson('/intercompany/afleiden', { method: 'POST' })
}
