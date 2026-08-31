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

export interface WerkopdrachtKortDto {
  groep_id: string
  van: string
  tot_en_met: string
  tekst: string
}

export interface WerkopdrachtDagTekstDto {
  groep_id: string
  tekst: string
  afwijkend: boolean
}

export interface PlanningProjectRijDto {
  project_id: string
  project_naam: string | null
  opdrachtgever: string | null
  soort_werk: string | null
  looptijd_tot: string | null
  // V3 (besluit Peter 23-08): de leesroute levert ÁLLE actieve projecten — de UI splitst op
  // per_datum (mét planning bovenaan, de rest compact). is_actief=false alleen bij een
  // gedeactiveerd project dat mét planning zichtbaar blijft (telt niet mee als actief).
  is_actief: boolean
  week_man: number
  per_datum: Record<string, PlanningKaartDto[]>
  // Werkopdrachten (31-08): actuele opdrachten die de week raken (chip in de rijkop) +
  // dag-overrides binnen de week (ISO-datum → afwijkende teksten in de dagcel).
  werkopdrachten: WerkopdrachtKortDto[]
  werkopdracht_overrides: Record<string, WerkopdrachtDagTekstDto[]>
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
  // Wachtrisico (steigerbouw-run D5): personeel gepland op een dag zonder bevestigde levering.
  wachtrisico?: { project_id: string; project_naam: string | null; datum: string; aantal_personen: number; transport_id: string | null; leverancier_naam: string | null; samenvatting: string }[]
}

export function haalPlanning(administratieId: string, jaar: number, weeknummer: number): Promise<PlanningWeekDto> {
  return apiJson(`/uren/kantoor/planning?administratie_id=${administratieId}&jaar=${jaar}&weeknummer=${weeknummer}`)
}

// De scope-dependency (vereis_administratie_scope) leest administratie_id als QUERY-parameter,
// óók op de POST-routes — de body alleen is niet genoeg (422 "query.administratie_id required",
// kliktest cloud 23-08). Daarom draagt élke schrijfactie 'm dubbel: query (scope) + body (motor).

export function planToewijzing(payload: {
  administratie_id: string
  gebruiker_id: string
  project_id: string
  datum: string
  dagdeel?: 'heel' | 'half'
}): Promise<void> {
  return apiPostJson(`/uren/kantoor/planning?administratie_id=${payload.administratie_id}`, payload)
}

export function verwijderToewijzing(payload: {
  administratie_id: string
  gebruiker_id: string
  project_id: string
  datum: string
}): Promise<void> {
  return apiPostJson(`/uren/kantoor/planning/verwijderen?administratie_id=${payload.administratie_id}`, payload)
}

export function verplaatsToewijzing(payload: {
  administratie_id: string
  gebruiker_id: string
  van_project_id: string
  van_datum: string
  naar_project_id: string
  naar_datum: string
}): Promise<void> {
  return apiPostJson(`/uren/kantoor/planning/verplaatsen?administratie_id=${payload.administratie_id}`, payload)
}

export function zetDagdeel(payload: {
  administratie_id: string
  gebruiker_id: string
  project_id: string
  datum: string
  dagdeel: 'heel' | 'half'
}): Promise<void> {
  return apiPostJson(`/uren/kantoor/planning/dagdeel?administratie_id=${payload.administratie_id}`, payload)
}

/* --- werkopdrachten per project × periode (31-08, migratie 0091) ------------------------------ */

export interface WerkopdrachtDto {
  groep_id: string
  project_id: string
  versie: number
  van: string
  tot_en_met: string
  tekst: string
  dag_overrides: { datum: string; tekst: string }[]
  historie: { tijdstip: string; door_naam: string; omschrijving: string }[]
}

export function haalWerkopdrachten(administratieId: string, projectId: string): Promise<WerkopdrachtDto[]> {
  return apiJson(`/uren/kantoor/werkopdrachten?administratie_id=${administratieId}&project_id=${projectId}`)
}

export function maakWerkopdracht(payload: {
  administratie_id: string
  project_id: string
  van: string
  tot_en_met: string
  tekst: string
}): Promise<WerkopdrachtDto> {
  return apiPostJson(`/uren/kantoor/werkopdrachten?administratie_id=${payload.administratie_id}`, payload)
}

export function wijzigWerkopdracht(
  groepId: string,
  payload: { administratie_id: string; van: string; tot_en_met: string; tekst: string },
): Promise<WerkopdrachtDto> {
  return apiPostJson(
    `/uren/kantoor/werkopdrachten/${groepId}/wijzigen?administratie_id=${payload.administratie_id}`,
    payload,
  )
}

export function zetWerkopdrachtDagOverride(
  groepId: string,
  payload: { administratie_id: string; datum: string; tekst: string },
): Promise<WerkopdrachtDto> {
  return apiPostJson(
    `/uren/kantoor/werkopdrachten/${groepId}/dag-override?administratie_id=${payload.administratie_id}`,
    payload,
  )
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

/* --- week in de URL (?week=2026-W41) — deelbaar/herlaadbaar, zelfde vorm als <input type="week"> */

export function weekNaarParam(week: { jaar: number; weeknummer: number }): string {
  return `${week.jaar}-W${String(week.weeknummer).padStart(2, '0')}`
}

/** Parse "2026-W41" (ook "2026-W5"); ongeldig of niet-bestaande week → null. */
export function parseWeekParam(param: string | null): { jaar: number; weeknummer: number } | null {
  if (!param) return null
  const m = /^(\d{4})-W(\d{1,2})$/.exec(param)
  if (!m) return null
  const jaar = Number(m[1])
  const weeknummer = Number(m[2])
  if (weeknummer < 1 || weeknummer > 53) return null
  // Week 53 bestaat niet elk jaar: de maandag van "week 53" moet ook echt in week 53 vallen.
  const maandag = weekDagen(jaar, weeknummer)[0].datum
  const terug = isoWeekVan(new Date(`${maandag}T12:00:00Z`))
  if (terug.jaar !== jaar || terug.weeknummer !== weeknummer) return null
  return { jaar, weeknummer }
}
