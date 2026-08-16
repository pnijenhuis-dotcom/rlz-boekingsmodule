import { apiJson, apiPostJson } from '../api/client'

/* Gebruikers & toegang (fase 3 modernisering 15-08, mockup #scherm-gebruikers) — dunne laag op
 * de bestaande auth-endpoints; alleen de gebruikerslijst en "opnieuw mailen" zijn nieuw. */

export interface GebruikerOverzichtDto {
  id: string
  naam: string
  e_mail: string
  rol: string
  status: string
  administratie_ids: string[]
  heeft_totp: boolean
  aantal_passkeys: number
  open_uitnodiging_verloopt_op: string | null
  staande_goedkeuringen: number
  geblokkeerd_op: string | null
  geblokkeerd_door_naam: string | null
}

export interface GebruikersLijstDto {
  gebruikers: GebruikerOverzichtDto[]
}

export interface UitnodigingResultaatDto {
  uitnodiging_id: string
  gebruiker_id: string
  token: string
  verloopt_op: string
  mail_verzonden: boolean
  mail_fout: string | null
}

export interface ApparaatDto {
  id: string
  apparaat_naam: string | null
  is_dev_stub: boolean
  aangemaakt_op: string
  laatst_gebruikt_op: string | null
  ingetrokken_op: string | null
}

export const ROL_LABELS: Record<string, string> = {
  beheerder: 'Beheerder',
  boekhouding_projecten: 'Boekhouding + Projecten',
  boekhouding: 'Boekhouding',
  klant_accordeur: 'Klant-accordeur',
}

export function rolLabel(rol: string): string {
  return ROL_LABELS[rol] ?? rol
}

export function haalGebruikersOp(): Promise<GebruikersLijstDto> {
  return apiJson<GebruikersLijstDto>('/auth/gebruikers')
}

export function nodigUit(payload: {
  naam: string
  e_mail: string
  rol: string
  administratie_ids: string[]
}): Promise<UitnodigingResultaatDto> {
  return apiPostJson<UitnodigingResultaatDto>('/auth/uitnodigingen', payload)
}

export function mailUitnodigingOpnieuw(gebruikerId: string): Promise<UitnodigingResultaatDto> {
  return apiPostJson<UitnodigingResultaatDto>(`/auth/gebruikers/${gebruikerId}/uitnodiging-opnieuw`, {})
}

export async function wijzigRol(gebruikerId: string, rol: string): Promise<void> {
  await apiJson(`/auth/gebruikers/${gebruikerId}/rol`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rol }),
  })
}

export async function voegScopeToe(gebruikerId: string, administratieId: string): Promise<void> {
  await apiPostJson(`/auth/gebruikers/${gebruikerId}/scope`, { administratie_id: administratieId })
}

export async function verwijderScope(gebruikerId: string, administratieId: string): Promise<void> {
  await apiJson(`/auth/gebruikers/${gebruikerId}/scope/${administratieId}`, { method: 'DELETE' })
}

export async function blokkeerGebruiker(gebruikerId: string): Promise<void> {
  await apiPostJson(`/auth/gebruikers/${gebruikerId}/blokkeren`, {})
}

export async function heractiveerGebruiker(gebruikerId: string): Promise<void> {
  await apiPostJson(`/auth/gebruikers/${gebruikerId}/heractiveren`, {})
}

export function haalApparatenVan(gebruikerId: string): Promise<{ apparaten: ApparaatDto[] }> {
  return apiJson<{ apparaten: ApparaatDto[] }>(`/auth/gebruikers/${gebruikerId}/apparaten`)
}

export async function trekApparaatIn(apparaatId: string): Promise<void> {
  await apiPostJson(`/auth/apparaten/${apparaatId}/intrekken`, {})
}
