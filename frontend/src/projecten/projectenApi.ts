// Datalaag kantoor-projectenmodule (mockup projecten-invoer.html, akkoord Peter 22-08) —
// spiegelt backend/app/projecten/schemas_kantoor.py. Bedragen/Decimals als string; de
// client rekent nooit zelf (analytische laag komt kant-en-klaar uit de backend).

import { apiFetch, apiJson, apiPostJson } from '../api/client'

export interface ProjectLijstRijDto {
  project_id: string
  naam: string | null
  is_actief: boolean
  opdrachtgever: string | null
  werknummer_opdrachtgever: string | null
  specs_status: 'compleet' | 'onvolledig' | 'geen' | string
  documenten: Record<string, number>
  staffels: number
  gebouwd_m2: string
  contract_m2: string | null
  doorlopende_huur: boolean
  heeft_activiteit: boolean
}

export interface ProjectenLijstDto {
  projecten: ProjectLijstRijDto[]
  zonder_specs: number
}

export interface SpecificatieDto {
  opdrachtgever: string | null
  werknummer_opdrachtgever: string | null
  soort_werk: string | null
  contract_m2: string | null
  looptijd_van: string | null
  looptijd_tot: string | null
  huurtijd_omschrijving: string | null
  doorlopende_huur_omschrijving: string | null
}

export interface ProjectDocumentDto {
  id: string
  soort: 'contract' | 'offerte' | string
  titel: string
  versie_omschrijving: string | null
  bestandsnaam: string
  aangemaakt_op: string
  ontleed: boolean
}

export interface StaffelDto {
  id: string
  omschrijving: string
  eenheid: string
  prijs_per_eenheid: string
  verrekenbaar: boolean
  bron: string | null
  aangemaakt_op: string
}

export interface WerknummerDto {
  id: string
  vendor_id: string
  leverancier_naam: string | null
  werknummer: string
  bron: string
  bevestigd: boolean
  aangemaakt_op: string
}

export interface OntledingRegelDto {
  id: string
  project_document_id: string
  soort: string
  omschrijving: string
  citaat: string | null
  waarde: Record<string, string> | null
  zekerheid: string | null
  status: 'voorstel' | 'bevestigd' | 'afgewezen' | string
}

export interface ProjectDetailDto {
  project_id: string
  naam: string | null
  is_actief: boolean
  specificatie: SpecificatieDto | null
  documenten: ProjectDocumentDto[]
  staffels: StaffelDto[]
  werknummers: WerknummerDto[]
  ontleding: OntledingRegelDto[]
  gebouwd_m2: string
}

export interface ProjectWeekDto {
  jaar: number
  weeknummer: number
  baten: string
  kosten_geboekt: string
  kosten_onderweg: string
  onderweg_onbepaalbaar_uren: string
  saldo: string
  cumulatief: string
  baten_detail: string[]
  kosten_detail: string[]
}

export interface ProjectResultaatDto {
  project_id: string
  project_naam: string | null
  opdrachtgever: string | null
  baten_geboekt: string
  kosten_geboekt: string
  uren_onderweg_bedrag: string
  uren_onderweg_uren: string
  onbepaalbaar_uren: string
  meerwerk_onderweg_bedrag: string
  onderweg_saldo: string
  verwachte_marge: string
  marge_pct: string | null
  weken: ProjectWeekDto[]
}

export interface OverzichtRijDto {
  project_id: string
  project_naam: string | null
  opdrachtgever: string | null
  baten: string
  kosten_incl_onderweg: string
  marge: string
  marge_pct: string | null
  trend: 'stijgend' | 'dalend' | 'stabiel' | string
  kosten_zonder_omzet_weken: number
  meerwerk_te_lang_niet_doorbelast: number
  doorlopende_huur: boolean
  onbepaalbaar_uren: string
}

export interface ProjectenOverzichtDto {
  baten_totaal: string
  kosten_totaal_incl_onderweg: string
  uren_onderweg_totaal: string
  onbepaalbaar_uren_totaal: string
  meerwerk_onderweg_totaal: string
  marge_totaal: string
  marge_pct: string | null
  aandacht: number
  rijen: OverzichtRijDto[]
}

export function haalProjecten(administratieId: string, zoek = ''): Promise<ProjectenLijstDto> {
  return apiJson(`/projecten/${administratieId}?zoek=${encodeURIComponent(zoek)}`)
}

export function haalProjectDetail(administratieId: string, projectId: string): Promise<ProjectDetailDto> {
  return apiJson(`/projecten/${administratieId}/${projectId}`)
}

export function haalVolgendNummer(administratieId: string): Promise<{ projectnummer: string }> {
  return apiJson(`/projecten/${administratieId}/volgend-nummer`)
}

export function maakProject(
  administratieId: string,
  payload: { projectnummer: string; plaats: string; opdrachtgever: string; startdatum?: string | null },
): Promise<{ rlz_project_id: string; projectnaam: string; bestond_al: boolean }> {
  return apiPostJson(`/projecten/${administratieId}`, payload)
}

export function zetSpecificatie(
  administratieId: string,
  projectId: string,
  specificatie: SpecificatieDto,
): Promise<void> {
  return apiJson(`/projecten/${administratieId}/${projectId}/specificatie`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(specificatie),
  })
}

export function voegStaffelToe(
  administratieId: string,
  projectId: string,
  payload: { omschrijving: string; eenheid: string; prijs_per_eenheid: string; verrekenbaar: boolean; bron?: string | null },
): Promise<{ id: string }> {
  return apiPostJson(`/projecten/${administratieId}/${projectId}/staffels`, payload)
}

export function wijzigStaffel(
  administratieId: string,
  staffelId: string,
  payload: { omschrijving: string; eenheid: string; prijs_per_eenheid: string; verrekenbaar: boolean; bron?: string | null },
): Promise<void> {
  return apiJson(`/projecten/${administratieId}/staffels/${staffelId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function uploadProjectDocument(
  administratieId: string,
  projectId: string,
  bestand: File,
  soort: 'contract' | 'offerte',
  titel: string,
): Promise<{ id: string }> {
  const form = new FormData()
  form.append('bestand', bestand)
  form.append('soort', soort)
  form.append('titel', titel)
  const resp = await apiFetch(`/projecten/${administratieId}/${projectId}/documenten`, {
    method: 'POST',
    body: form,
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => null)
    throw new Error((body as { detail?: string } | null)?.detail ?? `Upload mislukt (${resp.status})`)
  }
  return (await resp.json()) as { id: string }
}

export function ontleedDocument(
  administratieId: string,
  projectId: string,
  documentId: string,
): Promise<{ aantal_regels: number }> {
  return apiPostJson(`/projecten/${administratieId}/${projectId}/documenten/${documentId}/ontleden`, {})
}

export function beslisOntledingRegel(
  administratieId: string,
  regelId: string,
  payload: { bevestigen: boolean; eenheid?: string | null; verrekenbaar?: boolean },
): Promise<void> {
  return apiPostJson(`/projecten/${administratieId}/ontleding/${regelId}/beslis`, payload)
}

export function voegWerknummerToe(
  administratieId: string,
  projectId: string,
  payload: { vendor_id: string; werknummer: string },
): Promise<{ id: string }> {
  return apiPostJson(`/projecten/${administratieId}/${projectId}/werknummers`, payload)
}

export function bevestigWerknummer(administratieId: string, werknummerId: string): Promise<void> {
  return apiPostJson(`/projecten/${administratieId}/werknummers/${werknummerId}/bevestig`, {})
}

export function haalProjectResultaat(administratieId: string, projectId: string): Promise<ProjectResultaatDto> {
  return apiJson(`/projecten/${administratieId}/${projectId}/resultaat`)
}

export function haalProjectenOverzicht(administratieId: string): Promise<ProjectenOverzichtDto> {
  return apiJson(`/projecten/${administratieId}/resultaat-overzicht`)
}

/* Achtergrondrun-fix 23-08: de knop start een run (202) en de UI pollt de status —
 * de volledige RLZ-ronde liep in één request tegen Cloud Runs request-timeout (504). */
export interface CijfersSyncStatusDto {
  status: 'geen' | 'wachtrij' | 'bezig' | 'klaar' | 'fout'
  run_id?: string | null
  aangevraagd_op?: string | null
  gestart_op?: string | null
  beeindigd_op?: string | null
  documenten?: number | null
  regels?: number | null
  verdwenen?: number | null
  leesfouten?: number | null
  fout_reden?: string | null
}

export function startCijfersSync(administratieId: string): Promise<{ run_id: string; status: string }> {
  return apiPostJson(`/projecten/${administratieId}/cijfers-sync`, {})
}

export function haalCijfersSyncStatus(administratieId: string): Promise<CijfersSyncStatusDto> {
  return apiJson(`/projecten/${administratieId}/cijfers-sync/status`)
}

export function euro(bedrag: string | number | null | undefined): string {
  if (bedrag === null || bedrag === undefined) return '—'
  return Number(bedrag).toLocaleString('nl-NL', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
}

export function euroPrecies(bedrag: string | number | null | undefined): string {
  if (bedrag === null || bedrag === undefined) return '—'
  return Number(bedrag).toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}
