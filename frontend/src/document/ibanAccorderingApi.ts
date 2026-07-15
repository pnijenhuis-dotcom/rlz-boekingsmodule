import { apiJson, apiPostJson } from '../api/client'
import type { IbanAccorderingDto, IbanAccorderingLijstDto, IbanAccordeursDto } from '../api/types'

/** Dunne wrappers rond de PART A-endpoints (app/documenten/iban_accordering.py) — zelfde
 * patroon als vragenApi.ts: alle accordering-verkeer op één plek zodat schermen en tests
 * dezelfde routes delen. Het IBAN reist altijd in de body, nooit in de URL. */

export function haalAccorderingenOp(
  administratieId: string,
  opties: { status?: 'open' | 'geaccordeerd' | 'afgewezen'; documentId?: string } = {},
): Promise<IbanAccorderingLijstDto> {
  const params = new URLSearchParams()
  if (opties.status) params.set('accordering_status', opties.status)
  if (opties.documentId) params.set('document_id', opties.documentId)
  const query = params.toString()
  return apiJson<IbanAccorderingLijstDto>(
    `/administraties/${administratieId}/iban-accorderingen${query ? `?${query}` : ''}`,
  )
}

export function biedIbanAan(
  administratieId: string,
  documentId: string,
  invoer: { nieuw_iban: string; soort: 'regulier' | 'g_rekening' },
): Promise<IbanAccorderingDto> {
  return apiPostJson<IbanAccorderingDto>(
    `/administraties/${administratieId}/documenten/${documentId}/iban-accordering`,
    invoer,
  )
}

export function accordeerIban(administratieId: string, accorderingId: string): Promise<IbanAccorderingDto> {
  return apiPostJson<IbanAccorderingDto>(
    `/administraties/${administratieId}/iban-accorderingen/${accorderingId}/accorderen`,
    {},
  )
}

export function wijsIbanAf(
  administratieId: string,
  accorderingId: string,
  reden: string,
): Promise<IbanAccorderingDto> {
  return apiPostJson<IbanAccorderingDto>(
    `/administraties/${administratieId}/iban-accorderingen/${accorderingId}/afwijzen`,
    { reden },
  )
}

export function haalIbanAccordeursOp(administratieId: string): Promise<IbanAccordeursDto> {
  return apiJson<IbanAccordeursDto>(`/administraties/${administratieId}/iban-accordeurs`)
}

export function zetIbanAccordeurs(administratieId: string, accordeurs: string[]): Promise<IbanAccordeursDto> {
  return apiJson<IbanAccordeursDto>(`/administraties/${administratieId}/iban-accordeurs`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accordeurs }),
  })
}

/** Zelfde maskering als de backend (app/extractie/iban.py::masker_iban): land + bankdeel
 * zichtbaar, rekeninggedeelte grotendeels gemaskeerd — het volledige nummer staat op de
 * factuur-preview zelf. */
export function maskeerIban(iban: string): string {
  const compact = iban.replace(/\s+/g, '').toUpperCase()
  if (compact.length <= 11) return `${compact.slice(0, 4)}…`
  return `${compact.slice(0, 8)}…${compact.slice(-3)}`
}

export const SOORT_LABELS: Record<'regulier' | 'g_rekening', string> = {
  regulier: 'Reguliere rekening',
  g_rekening: 'G-rekening (WKA)',
}
