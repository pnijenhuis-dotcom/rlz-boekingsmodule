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
  /** Blok 3 18-09: module-status lopend|afgesloten + afsluit-spoor (oudere mocks missen 'm → lopend). */
  status?: ProjectStatus
  afgesloten_op?: string | null
  afsluit_reden?: string | null
}

/** Blok 3 18-09 (Peter: "als een project afgesloten is kan het uit de lijst"). */
export type ProjectStatus = 'lopend' | 'afgesloten'

export interface ProjectenLijstDto {
  projecten: ProjectLijstRijDto[]
  zonder_specs: number
  /** Blok 3 18-09: teller voor de toggle "Toon afgesloten (N)"; ontbreekt bij oudere mocks. */
  aantal_afgesloten?: number
}

export interface ProjectStatusDto {
  project_id: string
  status: ProjectStatus
  is_actief: boolean | null
  afgesloten_op: string | null
  afgesloten_door: string | null
  afsluit_reden: string | null
}

/** 409-detail van `POST /projecten/{aid}` als het projectnummer al bestaat (blok B 18-09). */
export interface ProjectnummerBestaatAlDetail {
  code: 'projectnummer_bestaat_al'
  melding: string
  nummer: string
  bestaand_project_id: string
  bestaand_naam: string
  status: ProjectStatus
  bron: 'cache' | 'rlz' | string
}

export function isProjectnummerBestaatAl(detail: unknown): detail is ProjectnummerBestaatAlDetail {
  return (
    typeof detail === 'object' &&
    detail !== null &&
    (detail as { code?: unknown }).code === 'projectnummer_bestaat_al' &&
    typeof (detail as { bestaand_project_id?: unknown }).bestaand_project_id === 'string'
  )
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
  /** Projectzone werkstempels (blok C 28-08): zonder lat/lon = geen geofence voor dit project. */
  locatie_adres?: string | null
  locatie_lat?: string | null
  locatie_lon?: string | null
  zone_straal_m?: number | null
  /** D6 (07-09): herkomst per veld — 'contract' (chip "uit contract", direct ingevuld door de ontleding) |
   * 'mens' (handmatig ingevuld/gecorrigeerd); ontbrekend = onbekend (rij van vóór 0118). */
  veld_herkomst?: Record<string, 'contract' | 'mens' | string>
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
  /** D6: 'contract' | 'mens' | null (vóór 0118 — dan afleiden uit `bron`: 'handmatig' → mens, anders contract). */
  herkomst?: 'contract' | 'mens' | string | null
  herkomst_document_id?: string | null
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
  /** D6 auto-first: 'overgenomen' (direct ingevuld), 'niet_aangetroffen' (expliciete uitkomst), 'ongeldig'
   * (gelezen, niet plaatsbaar — reden in waarde.reden), 'mens_behouden' (mens-waarde wint); de drie oude
   * statussen alleen nog op rijen van vóór 07-09. */
  status:
    | 'voorstel'
    | 'bevestigd'
    | 'afgewezen'
    | 'overgenomen'
    | 'niet_aangetroffen'
    | 'ongeldig'
    | 'mens_behouden'
    | string
}

/** Projectafspraak per veldwerker (steigerbouw-run B1, mockup projecten-invoer "Prijsafspraken
 * veldwerkers — dit project"): wint in de factuurmatch van het koppeling-tarief; eenheid m²
 * rekent met goedgekeurde weekstaat-m². */
export interface PrijsafspraakDto {
  id: string
  gebruiker_id: string
  veldwerker_naam: string | null
  via_bureau_naam: string | null
  eenheid: 'uur' | 'm2'
  tarief: string
  geldig_vanaf_jaar: number | null
  geldig_vanaf_week: number | null
  geldig_tm_jaar: number | null
  geldig_tm_week: number | null
  toelichting: string | null
  standaard_tarief: string | null
  aangemaakt_op: string
  aangemaakt_door_naam: string | null
  ingetrokken_op: string | null
  ingetrokken_reden: string | null
}

export interface VeldwerkerKeuzeDto {
  gebruiker_id: string
  naam: string
  via_bureau_naam: string | null
  standaard_tarief: string | null
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
  prijsafspraken?: PrijsafspraakDto[]
  veldwerkers?: VeldwerkerKeuzeDto[]
  /** Additief (C5 07-09): verplichtingen mét verbruiksstand + weekstaten-/planningstand. */
  verplichtingen?: ProjectVerplichtingDto[]
  weekstaten_stand?: WeekstatenStandDto | null
  /** Blok 3 18-09: module-status + afsluit-spoor. */
  status?: ProjectStatus
  afgesloten_op?: string | null
  afgesloten_door?: string | null
  afsluit_reden?: string | null
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

export function haalProjecten(administratieId: string, zoek = '', opties: { metAfgesloten?: boolean } = {}): Promise<ProjectenLijstDto> {
  const p = new URLSearchParams({ zoek })
  // Blok 3 18-09: toggle "Toon afgesloten (N)" = alleen_actief=false (afgesloten + inactief erbij, grijs).
  if (opties.metAfgesloten) p.set('alleen_actief', 'false')
  return apiJson(`/projecten/${administratieId}?${p.toString()}`)
}

/** Blok 3 18-09: afsluiten (bron eerst inactief, RLZ wint bij conflict → 502 leesbaar) en heropenen. */
export function sluitProjectAf(
  administratieId: string,
  projectId: string,
  payload: { reden?: string | null; datum?: string | null } = {},
): Promise<ProjectStatusDto> {
  return apiPostJson(`/projecten/${administratieId}/${projectId}/afsluiten`, payload)
}

export function heropenProject(administratieId: string, projectId: string): Promise<ProjectStatusDto> {
  return apiPostJson(`/projecten/${administratieId}/${projectId}/heropenen`, {})
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

export function voegPrijsafspraakToe(
  administratieId: string,
  projectId: string,
  payload: {
    gebruiker_id: string
    eenheid: 'uur' | 'm2'
    tarief: string
    geldig_vanaf_jaar?: number | null
    geldig_vanaf_week?: number | null
    geldig_tm_jaar?: number | null
    geldig_tm_week?: number | null
    toelichting?: string | null
  },
): Promise<{ id: string }> {
  return apiPostJson(`/projecten/${administratieId}/${projectId}/prijsafspraken`, payload)
}

export function trekPrijsafspraakIn(administratieId: string, afspraakId: string, reden: string): Promise<void> {
  return apiJson(`/projecten/${administratieId}/prijsafspraken/${afspraakId}/intrekken`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reden }),
  })
}

/** B2 (25-08): weeknummers overal in steigerbouw-datumweergaves — "12-03-2026 (wk 11)". */
export function isoWeekVanDatum(iso: string): { jaar: number; weeknummer: number } {
  const d = new Date(`${iso.slice(0, 10)}T12:00:00Z`)
  const dag = d.getUTCDay() || 7
  d.setUTCDate(d.getUTCDate() + 4 - dag)
  const jaar = d.getUTCFullYear()
  const start = Date.UTC(jaar, 0, 1)
  return { jaar, weeknummer: Math.ceil(((d.getTime() - start) / 86400000 + 1) / 7) }
}

export function datumMetWeek(iso: string | null | undefined): string {
  if (!iso) return '—'
  const { weeknummer } = isoWeekVanDatum(iso)
  return `${new Date(iso).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit', year: 'numeric' })} (wk ${weeknummer})`
}

export function weekLabel(jaar: number | null, week: number | null): string {
  if (jaar === null || week === null) return ''
  return `wk ${week}-${jaar}`
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

/* --- Inzicht › Projecten kantoorbreed + detail-verrijking (fixrun 07-09 blok C5) ---------------------
 * Spiegelt backend/app/projecten/schemas_kantoor.py (ProjectenKantoorbreedResponse, ProjectVerplichtingDto,
 * WeekstatenStandDto). De client formatteert alleen — chips, urgentie, facetten en paginering komen van
 * de server. */

export type ProjectSignaal = 'verplichting_overschreden' | 'marge_negatief' | 'weekstaat_ontbreekt' | 'te_keuren'
export type ProjectStatusFacet = 'alle' | 'signaal' | ProjectSignaal | 'op_schema' | 'kandidaat_afsluiten' | 'afgesloten'

export interface ResultaatChipDto {
  baten: string
  kosten: string
  marge: string
  marge_pct: string | null
  onbepaalbaar_uren: string
  heeft_cijfers: boolean
}

export interface VerplichtingenChipDto {
  aantal: number
  goedgekeurd_excl: string
  verbruikt_excl: string
  percentage: number | null
  overschreden: number
}

export interface WeekstatenChipDto {
  van_toepassing: boolean
  ontbrekend: number
  oudste_ontbrekende_jaar: number | null
  oudste_ontbrekende_week: number | null
  te_keuren: number
  concept: number
}

export interface M2ChipDto {
  gebouwd_m2: string
  contract_m2: string | null
  percentage: number | null
  doorlopende_huur: boolean
}

export interface ProjectKantoorbreedRijDto {
  administratie_id: string
  administratie_naam: string
  project_id: string
  naam: string | null
  opdrachtgever: string | null
  werknummer_opdrachtgever: string | null
  looptijd_tot: string | null
  resultaat: ResultaatChipDto
  verplichtingen: VerplichtingenChipDto
  weekstaten: WeekstatenChipDto
  m2: M2ChipDto
  signalen: ProjectSignaal[]
  urgentie: number
  /** Blok 3 18-09: status + chip "kandidaat afsluiten" (90 dagen stil én contract-m² bereikt; nooit automatisch). */
  status?: ProjectStatus
  afgesloten_op?: string | null
  kandidaat_afsluiten?: boolean
  kandidaat_reden?: string | null
}

export interface ProjectenKantoorbreedTellersDto {
  projecten: number
  administraties: number
  met_signaal: number
  verplichting_overschreden: number
  marge_negatief: number
  weekstaat_ontbreekt: number
  te_keuren: number
  /** Blok 3 18-09 */
  kandidaat_afsluiten?: number
  afgesloten?: number
}

export interface ProjectenKantoorbreedDto {
  rijen: ProjectKantoorbreedRijDto[]
  totaal: number
  pagina: number
  per_pagina: number
  administraties_in_selectie: number
  tellers: ProjectenKantoorbreedTellersDto
  facetten: {
    status: Record<string, number>
    administraties: { administratie_id: string; naam: string; aantal: number }[]
  }
}

export const PROJECT_STATUS_FACETTEN: ProjectStatusFacet[] = [
  'alle',
  'signaal',
  'verplichting_overschreden',
  'marge_negatief',
  'weekstaat_ontbreekt',
  'te_keuren',
  'op_schema',
  'kandidaat_afsluiten',
  'afgesloten',
]

export const PROJECT_STATUS_LABEL: Record<ProjectStatusFacet, string> = {
  alle: 'alle',
  signaal: 'met signaal',
  verplichting_overschreden: 'offerte overschreden',
  marge_negatief: 'negatieve marge',
  weekstaat_ontbreekt: 'weekstaat ontbreekt',
  te_keuren: 'weekstaat te keuren',
  op_schema: 'op schema',
  kandidaat_afsluiten: 'kandidaat afsluiten',
  afgesloten: 'afgesloten',
}

export function haalProjectenKantoorbreed(params: {
  pagina: number
  q?: string
  administratieId?: string | null
  status?: ProjectStatusFacet
  /** Blok 3 18-09: toggle "Toon afgesloten (N)". */
  toonAfgesloten?: boolean
}): Promise<ProjectenKantoorbreedDto> {
  const p = new URLSearchParams()
  p.set('pagina', String(params.pagina))
  p.set('status', params.status ?? 'alle')
  if (params.q) p.set('q', params.q)
  if (params.administratieId) p.set('administratie_id', params.administratieId)
  if (params.toonAfgesloten) p.set('toon_afgesloten', 'true')
  return apiJson(`/projecten/kantoorbreed?${p.toString()}`)
}

/** Eén verplichting op het projectdetail mét verbruiksstand (VerbruiksBalk-patroon). */
export interface ProjectVerplichtingDto {
  document_id: string
  offertenummer: string | null
  soort_label: string | null
  leverancier_naam: string | null
  omschrijving: string | null
  goedgekeurd_excl: string | null
  verbruikt_excl: string
  percentage: number | null
  over_excl: string | null
  geldig_tot: string | null
  status: 'lopend' | 'overschreden' | 'vervallen' | string
  open_facturen_aantal: number
  open_facturen_excl: string
}

export interface WeekStandDto {
  jaar: number
  weeknummer: number
  maandag: string
  gepland_personen: number
  gepland_dagen: string
  concept: number
  ingediend: number
  goedgekeurd: number
  corrigeren: number
  ontbrekend: number
  afgemeld: number
}

export interface WeekstatenStandDto {
  van_toepassing: boolean
  weken: WeekStandDto[]
  ontbrekend_totaal: number
  te_keuren_totaal: number
  oudste_ontbrekende_jaar: number | null
  oudste_ontbrekende_week: number | null
}

// --- Afsluiten? (N) — opdracht Peter 19-09 -------------------------------------------------------------------------------
// Eén motor (server) voor de tab per administratie én kantoorbreed, de chip op Inzicht › Projecten en de CLI. Kandidaat =
// één of meer redenen; "Niet afsluiten" mét verplichte reden onthoudt het besluit tot er nieuwe activiteit is; bulk-afsluiten
// = per project de bestaande afsluit-flow mét uitkomst per rij. De client formatteert alleen.

export type AfsluitReden = 'stil' | 'eindfactuur' | 'naam_afgesloten' | 'looptijd_verstreken'
export type AfsluitUitkomst = 'gelukt' | 'bron_weigert' | 'al_afgesloten' | 'niet_gevonden' | 'geen_toegang'

export interface AfsluitActiviteitDto {
  soort: 'inkoop' | 'verkoop' | 'uren' | 'planning' | 'verplichting' | string
  datum: string
  bedrag: string | null
  boekstuk: string | null
}

export interface AfsluitOpenPostenDto {
  inkoop_niet_geboekt: number
  inkoop_niet_geboekt_bedrag: string
  verplichting_open: number
  uren_niet_gekeurd: number
  let_op: boolean
}

export interface AfsluitUitstelDto {
  reden: string
  door: string
  op: string
  laatste_activiteit: string | null
}

export interface AfsluitKandidaatDto {
  administratie_id: string
  administratie_naam: string
  project_id: string
  naam: string | null
  redenen: AfsluitReden[]
  reden_tekst: string
  laatste_activiteit: AfsluitActiviteitDto | null
  stil_dagen: number | null
  stil_maanden: number
  open_posten: AfsluitOpenPostenDto
  looptijd_tot: string | null
  uitstel: AfsluitUitstelDto | null
}

export interface AfsluitTellersDto {
  kandidaten: number
  uitgesteld: number
  administraties: number
  per_reden: Record<string, number>
  let_op: number
}

export interface AfsluitKandidatenDto {
  rijen: AfsluitKandidaatDto[]
  totaal: number
  pagina: number
  per_pagina: number
  tellers: AfsluitTellersDto
  redenen: AfsluitReden[]
  reden_labels: Record<string, string>
  stil_maanden: number | null
}

export interface AfsluitBulkUitkomstDto {
  administratie_id: string
  project_id: string
  naam: string | null
  uitkomst: AfsluitUitkomst
  detail: string | null
}

export interface AfsluitBulkDto {
  uitkomsten: AfsluitBulkUitkomstDto[]
  gelukt: number
  mislukt: number
}

export const AFSLUIT_REDEN_LABEL: Record<AfsluitReden, string> = {
  stil: 'geen activiteit',
  eindfactuur: 'eindfactuur geboekt',
  naam_afgesloten: 'naam zegt afgesloten',
  looptijd_verstreken: 'looptijd verstreken',
}

export const AFSLUIT_UITKOMST_LABEL: Record<AfsluitUitkomst, string> = {
  gelukt: 'afgesloten',
  bron_weigert: 'bron weigerde',
  al_afgesloten: 'was al afgesloten',
  niet_gevonden: 'niet gevonden',
  geen_toegang: 'geen toegang',
}

export function haalAfsluitKandidaten(params: {
  administratieId?: string | null
  q?: string
  reden?: AfsluitReden | null
  toonUitgesteld?: boolean
  pagina?: number
}): Promise<AfsluitKandidatenDto> {
  const p = new URLSearchParams()
  if (params.administratieId) p.set('administratie_id', params.administratieId)
  if (params.q) p.set('q', params.q)
  if (params.reden) p.set('reden', params.reden)
  if (params.toonUitgesteld) p.set('toon_uitgesteld', 'true')
  if (params.pagina && params.pagina > 1) p.set('pagina', String(params.pagina))
  const qs = p.toString()
  return apiJson(`/projecten/afsluit-kandidaten${qs ? `?${qs}` : ''}`)
}

export function sluitProjectenBulkAf(
  items: { administratie_id: string; project_id: string }[],
  payload: { reden?: string | null; datum?: string | null } = {},
): Promise<AfsluitBulkDto> {
  return apiPostJson('/projecten/afsluiten-bulk', { items, ...payload })
}

export function projectNietAfsluiten(administratieId: string, projectId: string, reden: string): Promise<AfsluitUitstelDto> {
  return apiPostJson(`/projecten/${administratieId}/${projectId}/niet-afsluiten`, { reden })
}

export function zetAfsluitStilMaanden(administratieId: string, stilMaanden: number): Promise<{ stil_maanden: number }> {
  return apiJson(`/projecten/${administratieId}/afsluit-instelling`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stil_maanden: stilMaanden }),
  })
}

/** Rollen die mogen afsluiten / "niet afsluiten" / het stil-venster zetten (server-side afgedwongen: Beheerder + B+P).
 * Zonder auth-context (visueel harnas, losse test) tonen we de knoppen — de server blijft de waarheid. */
export function magAfsluitenBedienen(rol: string | null | undefined): boolean {
  if (rol === undefined || rol === null) return true
  return rol === 'beheerder' || rol === 'boekhouding_projecten'
}
