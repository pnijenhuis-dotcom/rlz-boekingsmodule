import { apiJson } from '../api/client'
import type { GroepDto } from '../api/types'

/** Groepssaldi debiteuren/crediteuren (Peter 16-09): de NACHTELIJKE stand per groep uit `GET /groepen/{id}/saldi` —
 * bedragen als string (cent-exact), RLS op de cache = scope van de lezer ("N van M administraties in je scope"). */
export interface GroepSaldoRijDto {
  administratie_id: string
  naam: string
  status: 'ok' | 'geen_rekening' | 'ongeldig' | 'fout' | 'overgeslagen' | string
  detail: string | null
  debiteuren: string | null
  debiteuren_ic: string | null
  debiteuren_zonder_ic: string | null
  crediteuren: string | null
  crediteuren_ic: string | null
  crediteuren_zonder_ic: string | null
  debiteuren_rekening: string | null
  crediteuren_rekening: string | null
}

export interface GroepSaldoTotalenDto {
  debiteuren: string
  debiteuren_ic: string
  debiteuren_zonder_ic: string
  crediteuren: string
  crediteuren_ic: string
  crediteuren_zonder_ic: string
  aantal_geldig: number
}

export interface GroepSaldiDto {
  groep: GroepDto
  datum: string
  bron: 'stand' | 'live' | string
  aantal_leden: number
  aantal_in_scope: number
  zonder_stand: number
  rijen: GroepSaldoRijDto[]
  totalen: GroepSaldoTotalenDto
}

export function haalGroepSaldiOp(groepId: string): Promise<GroepSaldiDto> {
  return apiJson<GroepSaldiDto>(`/groepen/${encodeURIComponent(groepId)}/saldi`)
}

/** "1150.25" → "€ 1.150,25"; null → "—". Puur, geen afronding (de server levert cent-exact). */
export function euro(bedrag: string | null | undefined): string {
  if (bedrag == null || bedrag === '') return '—'
  const n = Number(bedrag)
  if (!Number.isFinite(n)) return bedrag
  return `€ ${n.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}
