// Kantoor-signaal "geplande week zonder weekstaat" (mini-run 06-09 blok A) — spiegelt de
// PlanningSignaal*-schema's in backend/app/uren/schemas.py. De veld-app toont geplande weken maar
// zes weken terug; een geplande week zonder ingediende weekstaat die uit dat venster valt is
// kantoorzijde zichtbaar mét precies één handeling per rij (herinneren of afmelden). De client
// formatteert alleen — venster, sortering, tellers en paginering komen van de server.
import { apiJson } from '../api/client'

export type SignaalSoort = 'geen_staat' | 'concept'
export type SignaalStatus = 'open' | 'afgemeld'
export type SignaalFilter = 'open' | 'afgemeld' | 'alle'

export interface PlanningSignaalDto {
  administratie_id: string
  administratie_naam: string
  gebruiker_id: string
  gebruiker_naam: string
  gebruiker_actief: boolean
  project_id: string
  project_naam: string | null
  jaar: number
  weeknummer: number
  maandag: string
  zondag: string
  /** Decimal als string ("1", "2.5"). */
  geplande_dagen: string
  soort: SignaalSoort
  weekstaat_status: string | null
  status: SignaalStatus
  herinneringen: number
  laatste_herinnering: { op: string; kanaal: string | null; door_naam: string | null } | null
  herinnerd_vandaag: boolean
  afmelding: { reden: string; op: string; door_naam: string | null } | null
}

export interface PlanningSignalenLijstDto {
  rijen: PlanningSignaalDto[]
  totaal: number
  pagina: number
  per_pagina: number
  administraties_in_selectie: number
  tellers: { open: number; afgemeld: number; administraties: number }
  facet_administraties: { administratie_id: string; naam: string; aantal: number }[]
  venster_weken: number
}

export interface SignaalSleutel {
  administratie_id: string
  gebruiker_id: string
  project_id: string
  jaar: number
  weeknummer: number
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export function sleutelVan(s: PlanningSignaalDto): SignaalSleutel {
  return {
    administratie_id: s.administratie_id,
    gebruiker_id: s.gebruiker_id,
    project_id: s.project_id,
    jaar: s.jaar,
    weeknummer: s.weeknummer,
  }
}

export function haalPlanningSignalen(params: {
  pagina: number
  filter: SignaalFilter
  administratieId?: string | null
}): Promise<PlanningSignalenLijstDto> {
  const p = new URLSearchParams()
  p.set('pagina', String(params.pagina))
  p.set('filter', params.filter)
  if (params.administratieId) p.set('administratie_id', params.administratieId)
  return apiJson(`/uren/kantoor/planning-signalen?${p.toString()}`)
}

/** Herinnering via het bestaande push-anders-mail-kanaal; max 1 per dag per combinatie (409). */
export function herinnerPlanningSignaal(
  sleutel: SignaalSleutel,
): Promise<{ gebruiker_id: string; kanaal: string; verzonden_op: string; herinneringen: number }> {
  return apiJson('/uren/kantoor/planning-signalen/herinneren', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(sleutel),
  })
}

export function meldPlanningSignaalAf(sleutel: SignaalSleutel, reden: string): Promise<{ id: string }> {
  return apiJson('/uren/kantoor/planning-signalen/afmelden', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ ...sleutel, reden }),
  })
}

export function trekAfmeldingIn(sleutel: SignaalSleutel): Promise<{ id: string }> {
  return apiJson('/uren/kantoor/planning-signalen/afmelden-intrekken', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(sleutel),
  })
}

export const FILTERS: SignaalFilter[] = ['open', 'afgemeld', 'alle']
export const FILTER_LABEL: Record<SignaalFilter, string> = { open: 'open', afgemeld: 'afgemeld', alle: 'alle' }

/** Deep-link naar de weekplanning van die week (planning-agenda: `?week=YYYY-Www`). */
export function planningPad(s: PlanningSignaalDto): string {
  return `/planning?administratie=${s.administratie_id}&week=${s.jaar}-W${String(s.weeknummer).padStart(2, '0')}`
}
