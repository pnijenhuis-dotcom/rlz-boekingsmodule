// Veld-datalaag uren & meerwerk (fase 4, mockup uren-uitvoerder.html) — spiegelt
// backend/app/uren/schemas.py. Bedragen/uren als string (Decimal), nooit berekend in de
// client. Dit bestand hoort bij de accordeur-chunk: GEEN imports uit ui/basis of kantoor-
// schermen (performance-budget accordeur-PWA).

import { apiFetch, apiJson, apiPostJson } from '../api/client'

export interface DagDto {
  id: string
  datum: string
  uren: string
  m2: string | null
  opmerking: string | null
  ingevuld_door_naam: string | null
  namens: boolean
  // Correctievoorstel van de laatste afkeuring (hybride keuring, besluit 22-08) — de app
  // toont ze alleen in status 'corrigeren'; de keurder wijzigt nooit zelf de uren.
  voorstel_uren: string | null
  voorstel_m2: string | null
  voorstel_opmerking: string | null
  // Planning-dekking (planning-agenda, besluit 22-08): uren zonder planningstoewijzing =
  // oranje "buiten planning" bij de keuring — een signaal, nooit een blokkade.
  buiten_planning: boolean
  // Signaal >N uur per dag (A6, 25-08): som over álle weekstaten van deze persoon op deze
  // kalenderdag; boven de administratie-drempel = oranje vlag. Nooit een blokkade.
  dag_totaal_uren: string
  boven_dagmax: boolean
  dagmax_uren: string | null
}

export interface WeekstaatDto {
  id: string
  administratie_id: string
  gebruiker_id: string
  gebruiker_naam: string | null
  project_id: string
  project_naam: string | null
  jaar: number
  weeknummer: number
  status: 'concept' | 'ingediend' | 'goedgekeurd' | 'corrigeren'
  totaal_uren: string
  totaal_m2: string
  dagen: DagDto[]
  ingediend_op: string | null
  ingediend_door_naam: string | null
  ingediend_namens: boolean
  goedgekeurd_op: string | null
  goedgekeurd_door_naam: string | null
  afgekeurd_op: string | null
  afgekeurd_door_naam: string | null
  afkeur_reden: string | null
}

export interface ProjectKaartDto {
  administratie_id: string
  administratie_naam: string | null
  project_id: string
  project_naam: string | null
  soort_werk: string | null
  open_weken: number
  laatste_invoer: string | null
}

export interface WeekKaartDto {
  jaar: number
  weeknummer: number
  maandag: string
  zondag: string
  status: 'nieuw' | 'concept' | 'ingediend' | 'goedgekeurd' | 'corrigeren'
  weekstaat_id: string | null
  dagen_ingevuld: number
  totaal_uren: string
  totaal_m2: string
  ingediend_op: string | null
  goedgekeurd_door_naam: string | null
  afgekeurd_door_naam: string | null
  afkeur_reden: string | null
}

export interface IngediendeWeekDto {
  weekstaat_id: string
  administratie_id: string
  administratie_naam: string | null
  project_id: string
  project_naam: string | null
  jaar: number
  weeknummer: number
  status: string
  totaal_uren: string
  totaal_m2: string
  ingediend_op: string | null
  ingediend_namens: boolean
  goedgekeurd_door_naam: string | null
  afgekeurd_door_naam: string | null
  afkeur_reden: string | null
}

export interface ZzperKaartDto {
  gebruiker_id: string
  naam: string
  aantal_projecten: number
  open_weken: number
  laatste_invoer: string | null
}

export interface TeKeurenItemDto {
  weekstaat_id: string
  administratie_id: string
  administratie_naam: string | null
  zzper_id: string
  zzper_naam: string | null
  project_id: string
  project_naam: string | null
  jaar: number
  weeknummer: number
  totaal_uren: string
  totaal_m2: string
  ingediend_op: string | null
  ingediend_namens: boolean
  ingediend_door_naam: string | null
}

export interface MeerwerkDto {
  id: string
  administratie_id: string
  project_id: string
  project_naam: string | null
  omschrijving: string
  aantal: string
  eenheid: string
  datum_uitgevoerd: string
  in_opdracht_van: string | null
  heeft_foto: boolean
  gemeld_op: string
  status: 'gemeld' | 'goedgekeurd' | 'doorbelast' | 'afgewezen'
  verkoopfactuur_referentie: string | null
  vraag_tekst: string | null
  vraag_antwoord: string | null
}

export interface ProjectDocumentKaartDto {
  id: string
  soort: string
  titel: string
  versie_omschrijving: string | null
  bestandsnaam: string
}

export interface ProjectDetailDto {
  administratie_id: string
  project_id: string
  project_naam: string | null
  opdrachtgever: string | null
  werknummer_opdrachtgever: string | null
  soort_werk: string | null
  contract_m2: string | null
  gebouwd_m2: string
  looptijd_van: string | null
  looptijd_tot: string | null
  huurtijd_omschrijving: string | null
  doorlopende_huur_omschrijving: string | null
  documenten: ProjectDocumentKaartDto[]
  meerwerk: MeerwerkDto[]
}

export interface UitvoerderProjectKaartDto {
  administratie_id: string
  administratie_naam: string | null
  project_id: string
  project_naam: string | null
  soort_werk: string | null
  contract_m2: string | null
  gebouwd_m2: string
  looptijd_tot: string | null
  huurtijd_omschrijving: string | null
  meerwerk_gemeld: number
  te_keuren: number
}

export const EENHEDEN = [
  { waarde: 'm2', label: 'm²' },
  { waarde: 'm1', label: 'm¹' },
  { waarde: 'stuks', label: 'stuks' },
  { waarde: 'manuren', label: 'manuren' },
] as const

export function eenheidLabel(eenheid: string): string {
  return EENHEDEN.find((e) => e.waarde === eenheid)?.label ?? eenheid
}

function namensParam(namens: string | null): string {
  return namens ? `?namens=${namens}` : ''
}

/* --- ZZP (en detacheerder via namens) --------------------------------------------------------- */

export function haalZzpProjecten(namens: string | null): Promise<ProjectKaartDto[]> {
  return apiJson(`/uren/zzp/projecten${namensParam(namens)}`)
}

export function haalZzpWeken(
  administratieId: string,
  projectId: string,
  namens: string | null,
): Promise<WeekKaartDto[]> {
  const basis = `/uren/zzp/weken?administratie_id=${administratieId}&project_id=${projectId}`
  return apiJson(namens ? `${basis}&namens=${namens}` : basis)
}

export function haalIngediend(namens: string | null): Promise<IngediendeWeekDto[]> {
  return apiJson(`/uren/zzp/ingediend${namensParam(namens)}`)
}

export function zetDag(payload: {
  administratie_id: string
  project_id: string
  jaar: number
  weeknummer: number
  datum: string
  uren: string
  m2: string | null
  opmerking: string | null
  namens_zzper_id: string | null
}): Promise<WeekstaatDto> {
  return apiJson('/uren/zzp/dag', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function dienWeekIn(payload: {
  administratie_id: string
  project_id: string
  jaar: number
  weeknummer: number
  namens_zzper_id: string | null
}): Promise<WeekstaatDto> {
  return apiPostJson('/uren/zzp/indienen', payload)
}

export function haalWeekstaat(administratieId: string, weekstaatId: string): Promise<WeekstaatDto> {
  return apiJson(`/uren/weekstaten/${administratieId}/${weekstaatId}`)
}

/** Eigen planning, ALLEEN-LEZEN (planning-agenda besluit B, 22-08): waar moet ik heen deze
 * week. Plannen doet uitsluitend het kantoor — de veld-API heeft bewust geen mutatiepad. */
export interface MijnPlanningDagDto {
  datum: string
  administratie_id: string
  administratie_naam: string | null
  project_id: string
  project_naam: string | null
  dagdeel: 'heel' | 'half'
}

export function haalMijnPlanning(
  jaar: number,
  weeknummer: number,
  namens: string | null,
): Promise<MijnPlanningDagDto[]> {
  const basis = `/uren/zzp/planning?jaar=${jaar}&weeknummer=${weeknummer}`
  return apiJson(namens ? `${basis}&namens=${namens}` : basis)
}

/* --- detacheerder ------------------------------------------------------------------------------ */

export function haalMijnZzpers(): Promise<ZzperKaartDto[]> {
  return apiJson('/uren/detacheerder/zzpers')
}

/* --- uitvoerder -------------------------------------------------------------------------------- */

export function haalUitvoerderProjecten(): Promise<UitvoerderProjectKaartDto[]> {
  return apiJson('/uren/uitvoerder/projecten')
}

export function haalProjectDetail(administratieId: string, projectId: string): Promise<ProjectDetailDto> {
  return apiJson(`/uren/uitvoerder/projecten/${administratieId}/${projectId}`)
}

export function haalTeKeuren(): Promise<TeKeurenItemDto[]> {
  return apiJson('/uren/uitvoerder/te-keuren')
}

export function keurWeekGoed(administratieId: string, weekstaatId: string): Promise<WeekstaatDto> {
  return apiPostJson(`/uren/uitvoerder/weekstaten/${administratieId}/${weekstaatId}/akkoord`, {})
}

/** Correctievoorstel per bestaande dagregel bij het afkeuren (hybride keuring, besluit
 * 22-08): minstens één van uren/m²/opmerking gevuld — de backend valideert hard. */
export interface DagCorrectieInvoer {
  datum: string
  uren: string | null
  m2: string | null
  opmerking: string | null
}

export function keurWeekAf(
  administratieId: string,
  weekstaatId: string,
  reden: string,
  correcties: DagCorrectieInvoer[] = [],
): Promise<WeekstaatDto> {
  return apiPostJson(`/uren/uitvoerder/weekstaten/${administratieId}/${weekstaatId}/afkeuren`, {
    reden,
    correcties,
  })
}

export async function meldMeerwerk(payload: {
  administratie_id: string
  project_id: string
  omschrijving: string
  aantal: string
  eenheid: string
  datum_uitgevoerd: string
  in_opdracht_van: string
  foto: File | null
}): Promise<MeerwerkDto> {
  const form = new FormData()
  form.set('administratie_id', payload.administratie_id)
  form.set('project_id', payload.project_id)
  form.set('omschrijving', payload.omschrijving)
  form.set('aantal', payload.aantal)
  form.set('eenheid', payload.eenheid)
  form.set('datum_uitgevoerd', payload.datum_uitgevoerd)
  if (payload.in_opdracht_van.trim() !== '') form.set('in_opdracht_van', payload.in_opdracht_van.trim())
  if (payload.foto) form.set('foto', payload.foto)
  const resp = await apiFetch('/uren/uitvoerder/meerwerk', { method: 'POST', body: form })
  if (!resp.ok) {
    const detail = await resp
      .json()
      .then((d: { detail?: string }) => d.detail)
      .catch(() => undefined)
    throw new Error(detail ?? `Melden mislukte (${resp.status})`)
  }
  return (await resp.json()) as MeerwerkDto
}

export function beantwoordMeerwerkVraag(
  administratieId: string,
  meerwerkId: string,
  tekst: string,
): Promise<MeerwerkDto> {
  return apiPostJson(`/uren/meerwerk/${administratieId}/${meerwerkId}/vraag-antwoord`, { tekst })
}

/** Contract-/offerte-PDF als object-URL (Authorization-header vereist — een kale <object src>
 * draagt geen token). De aanroeper is eigenaar van de URL (revokeObjectURL bij opruimen). */
export async function haalProjectDocumentBlob(administratieId: string, documentId: string): Promise<string> {
  const resp = await apiFetch(`/uren/projectdocumenten/${administratieId}/${documentId}`)
  if (!resp.ok) throw new Error(`Document laden mislukte (${resp.status})`)
  return URL.createObjectURL(await resp.blob())
}

/* --- weergave-helpers --------------------------------------------------------------------------- */

const DAG_NAMEN = ['ma', 'di', 'wo', 'do', 'vr', 'za', 'zo'] as const

/** De zeven dagen (ma–zo) van een ISO-week als ISO-datumstrings. */
export function weekDagen(jaar: number, weeknummer: number): { naam: string; datum: string }[] {
  // ISO-week: 4 januari zit altijd in week 1 (geen Date.UTC-verrassingen met tijdzones).
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

/** ISO-(jaar, week) van een datum (planning-weergave: huidige week + vooruit bladeren). */
export function isoWeekVan(datum: Date): { jaar: number; weeknummer: number } {
  const d = new Date(Date.UTC(datum.getFullYear(), datum.getMonth(), datum.getDate()))
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7)) // donderdag bepaalt het ISO-jaar
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

export function urenLabel(uren: string, m2: string | null): string {
  const u = Number(uren).toLocaleString('nl-NL', { minimumFractionDigits: 1, maximumFractionDigits: 2 })
  if (m2 === null || Number(m2) === 0) return `${u} u · —`
  return `${u} u · ${Number(m2).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} m²`
}

/** Compacte weergave van het correctievoorstel van de keurder (hybride keuring, 22-08). */
export function voorstelLabel(dag: DagDto): string {
  const delen: string[] = []
  if (dag.voorstel_uren !== null)
    delen.push(
      `${Number(dag.voorstel_uren).toLocaleString('nl-NL', { minimumFractionDigits: 1, maximumFractionDigits: 2 })} u`,
    )
  if (dag.voorstel_m2 !== null)
    delen.push(`${Number(dag.voorstel_m2).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} m²`)
  const cijfers = delen.join(' · ')
  if (dag.voorstel_opmerking) return cijfers ? `${cijfers} — "${dag.voorstel_opmerking}"` : `"${dag.voorstel_opmerking}"`
  return cijfers
}

export function heeftVoorstel(dag: DagDto): boolean {
  return dag.voorstel_uren !== null || dag.voorstel_m2 !== null || dag.voorstel_opmerking !== null
}

export function weekTotaalLabel(totaalUren: string, totaalM2: string): string {
  const u = Number(totaalUren).toLocaleString('nl-NL', { minimumFractionDigits: 1, maximumFractionDigits: 2 })
  const m2 = Number(totaalM2)
  return m2 > 0 ? `${u} u · ${m2.toLocaleString('nl-NL', { maximumFractionDigits: 2 })} m²` : `${u} u`
}

export function datumKort(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('nl-NL', { day: 'numeric', month: 'short' })
}

export function datumMetTijd(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('nl-NL', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}


/* --- ZZP-dossier (A1/A2, 25-08): eigen dossier + upload in de app, blokkade-melding ------------ */

export interface DossierDocumentDto {
  code: string
  naam: string
  verplicht: boolean
  geldig_tot_vereist: boolean
  bsn_gevoelig: boolean
  status: 'ontbreekt' | 'ter_controle' | 'afgewezen' | 'goedgekeurd' | 'verloopt_binnenkort' | 'verlopen'
  document_id: string | null
  geldig_tot: string | null
  verloopt_over_dagen: number | null
  bestandsnaam: string | null
  geupload_op: string | null
  geupload_door_naam: string | null
  afwijs_reden: string | null
}

export interface DossierDto {
  administratie_id: string
  gebruiker_id: string
  gebruiker_naam: string
  documenten: DossierDocumentDto[]
  aantal_verplicht: number
  aantal_aanwezig: number
  aantal_ontbrekend: number
  aantal_verlopen: number
  aantal_verloopt_binnenkort: number
  aantal_ter_controle: number
  compleet: boolean
  compleet_incl_ter_controle: boolean
  herinneringen_teller: number
  herinneringen_max: number
  geblokkeerd: boolean
  signalen: string[]
}

export function haalMijnDossier(administratieId: string, namens: string | null): Promise<DossierDto> {
  const q = new URLSearchParams({ administratie_id: administratieId })
  if (namens) q.set('namens', namens)
  return apiJson<DossierDto>(`/uren/dossier?${q.toString()}`)
}

export async function uploadDossierDocument(payload: {
  administratie_id: string
  type_code: string
  geldig_tot: string | null
  namens: string | null
  bestand: File
}): Promise<DossierDto> {
  const form = new FormData()
  form.append('administratie_id', payload.administratie_id)
  form.append('type_code', payload.type_code)
  if (payload.geldig_tot) form.append('geldig_tot', payload.geldig_tot)
  if (payload.namens) form.append('namens', payload.namens)
  form.append('bestand', payload.bestand, payload.bestand.name)
  return apiJson<DossierDto>('/uren/dossier/upload', { method: 'POST', body: form })
}

/** 423 Locked = dossier-handhaving (indienen geblokkeerd) — de app toont melding + upload-ingang. */
export function isDossierGeblokkeerd(err: unknown): boolean {
  return typeof err === 'object' && err !== null && (err as { status?: number }).status === 423
}

export function dossierStatusLabel(d: DossierDocumentDto): { klasse: string; label: string } {
  switch (d.status) {
    case 'ontbreekt':
      return { klasse: d.verplicht ? 'afgekeurd' : 'concept', label: d.verplicht ? 'ontbreekt' : 'optioneel' }
    case 'ter_controle':
      return { klasse: 'ingediend', label: 'ter controle' }
    case 'afgewezen':
      return { klasse: 'afgekeurd', label: 'afgewezen' }
    case 'goedgekeurd':
      return { klasse: 'akkoord', label: 'aanwezig' }
    case 'verloopt_binnenkort':
      return { klasse: 'open', label: `verloopt over ${d.verloopt_over_dagen ?? '?'} d` }
    case 'verlopen':
      return { klasse: 'afgekeurd', label: 'verlopen' }
  }
}
