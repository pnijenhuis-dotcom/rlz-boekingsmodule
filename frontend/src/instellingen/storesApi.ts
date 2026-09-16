import { apiJson } from '../api/client'

/** Store → administratie, PLATFORMBREED (Peter 16-09 avond: Sunshine Island = eigen BV; migratie 0151). De "Store Used"
 * uit een zonnestudio-dagstaat bepaalt in welke administratie de dagstaat (en de kascheck van dezelfde dag) landt —
 * ongeacht mailbox/tenaamstelling. Lezen = kantoorrol (de verzamelbak-rij linkt hierheen), koppelen/wijzigen = Beheerder.
 * Eén rij per store (unieke naam): verhuizen = dezelfde rij; ontkoppelen = actief=false, nooit verwijderen. */

export interface OmzetStoreDto {
  id: string
  store_naam: string
  store_norm: string
  administratie_id: string
  administratie_naam: string
  actief: boolean
  bron: 'mens' | 'migratie' | string
  gewijzigd_op: string | null
}

export interface OmzetStoresDto {
  stores: OmzetStoreDto[]
  doel_pad: string
}

export const STORES_DOEL_PAD = '/instellingen/boeken#stores'

export function haalStores(): Promise<OmzetStoresDto> {
  return apiJson<OmzetStoresDto>('/instellingen/omzet/stores')
}

export function koppelStore(store: string, administratieId: string): Promise<OmzetStoreDto> {
  return apiJson<OmzetStoreDto>('/instellingen/omzet/stores', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ store, administratie_id: administratieId }),
  })
}

export function wijzigStore(id: string, body: { administratie_id?: string; actief?: boolean }): Promise<OmzetStoreDto> {
  return apiJson<OmzetStoreDto>(`/instellingen/omzet/stores/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
