// Kantoor-datalaag planning-agenda steigerbouw (mockup planning-steigerbouw.html, akkoord
// Peter 22-08) — spiegelt backend/app/uren/schemas.py (planning-sectie). Uren/dagen als
// string (Decimal), nooit berekend in de client.

import { apiJson, apiPostJson } from '../api/client'

export interface PlanningKaartDto {
  gebruiker_id: string
  naam: string | null
  rol: string
  dagdeel: 'heel' | 'half'
}

export interface PlanningProjectRijDto {
  project_id: string
  project_naam: string | null
  opdrachtgever: string | null
  soort_werk: string | null
  looptijd_tot: string | null
  week_man: number
  per_datum: Record<string, PlanningKaartDto[]>
}

export interface PlanningPoolPersoonDto {
  gebruiker_id: string
  naam: string
  rol: string
  geplande_dagen: string // heel = 1, half = 0,5 — besluit C: > 5 kleurt als zacht signaal
}

export interface BuitenPlanningMeldingDto {
  gebruiker_id: string
  naam: string | null
  datum: string
  project_naam: string | null
  uren: string
}

export interface DubbeleDagMeldingDto {
  gebruiker_id: string
  naam: string | null
  datum: string
  project_namen: string[]
  ongedekte_project_namen: string[]
}

export interface DubbeleDagTellerDto {
  gebruiker_id: string
  naam: string | null
  aantal: number
}

export interface PlanningWeekDto {
  jaar: number
  weeknummer: number
  maandag: string
  zondag: string
  projecten: PlanningProjectRijDto[]
  pool: PlanningPoolPersoonDto[]
  buiten_planning: BuitenPlanningMeldingDto[]
  dubbele_dagen: DubbeleDagMeldingDto[]
  dubbele_dag_tellers: DubbeleDagTellerDto[]
}

export function haalPlanning(administratieId: string, jaar: number, weeknummer: number): Promise<PlanningWeekDto> {
  return apiJson(`/uren/kantoor/planning?administratie_id=${administratieId}&jaar=${jaar}&weeknummer=${weeknummer}`)
}

export function planToewijzing(payload: {
  administratie_id: string
  gebruiker_id: string
  project_id: string
  datum: string
  dagdeel?: 'heel' | 'half'
}): Promise<void> {
  return apiPostJson('/uren/kantoor/planning', payload)
}

export function verwijderToewijzing(payload: {
  administratie_id: string
  gebruiker_id: string
  project_id: string
  datum: string
}): Promise<void> {
  return apiPostJson('/uren/kantoor/planning/verwijderen', payload)
}

export function verplaatsToewijzing(payload: {
  administratie_id: string
  gebruiker_id: string
  van_project_id: string
  van_datum: string
  naar_project_id: string
  naar_datum: string
}): Promise<void> {
  return apiPostJson('/uren/kantoor/planning/verplaatsen', payload)
}

export function zetDagdeel(payload: {
  administratie_id: string
  gebruiker_id: string
  project_id: string
  datum: string
  dagdeel: 'heel' | 'half'
}): Promise<void> {
  return apiPostJson('/uren/kantoor/planning/dagdeel', payload)
}

/* --- ISO-week-helpers (kantoor-chunk; bewust niet uit uren/urenApi — accordeur-chunk) --------- */

const DAG_NAMEN = ['ma', 'di', 'wo', 'do', 'vr', 'za', 'zo'] as const

/** De zeven dagen (ma–zo) van een ISO-week als ISO-datumstrings (4 januari zit in week 1). */
export function weekDagen(jaar: number, weeknummer: number): { naam: string; datum: string }[] {
  const vierJan = new Date(Date.UTC(jaar, 0, 4))
  const maandagWeek1 = new Date(vierJan)
  maandagWeek1.setUTCDate(vierJan.getUTCDate() - ((vierJan.getUTCDay() + 6) % 7))
  const maandag = new Date(maandagWeek1)
  maandag.setUTCDate(maandagWeek1.getUTCDate() + (weeknummer - 1) * 7)
  return DAG_NAMEN.map((naam, i) => {
    const d = new Date(maandag)
    d.setUTCDate(maandag.getUTCDate() + i)
    return { naam, datum: d.toISOString().slice(0, 10) }
  })
}

/** ISO-(jaar, week) van een datum. */
export function isoWeekVan(datum: Date): { jaar: number; weeknummer: number } {
  const d = new Date(Date.UTC(datum.getFullYear(), datum.getMonth(), datum.getDate()))
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7)) // donderdag van deze week bepaalt het ISO-jaar
  const jaar = d.getUTCFullYear()
  const eersteDonderdag = new Date(Date.UTC(jaar, 0, 4))
  eersteDonderdag.setUTCDate(eersteDonderdag.getUTCDate() + 4 - (eersteDonderdag.getUTCDay() || 7))
  const weeknummer = 1 + Math.round((d.getTime() - eersteDonderdag.getTime()) / (7 * 24 * 3600 * 1000))
  return { jaar, weeknummer }
}

/** Eén ISO-week vooruit of terug ten opzichte van (jaar, weeknummer). */
export function schuifWeek(jaar: number, weeknummer: number, delta: number): { jaar: number; weeknummer: number } {
  const maandag = weekDagen(jaar, weeknummer)[0].datum
  const d = new Date(`${maandag}T12:00:00Z`)
  d.setUTCDate(d.getUTCDate() + delta * 7)
  return isoWeekVan(new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()))
}
