// Transportplanning + bestellingen + materiaalstand (steigerbouw-run blok D, mockup
// planning-steigerbouw.html Transport-tab + bestelling-popup = norm) — spiegelt
// backend/app/materiaal/schemas.py. Bedragen/m² als string (Decimal), nooit berekend in de client.
import { apiFetch, apiJson, apiPostJson } from '../api/client'

export interface LeverancierDto {
  id: string
  naam: string
  bestel_email: string | null
  telefoon: string | null
  adres: string | null
  vendor_id: string | null
  actief: boolean
  aantal_producten: number
}

export interface ProductDto {
  id: string
  leverancier_id: string
  categorie_id: string
  categorie_naam: string
  bundel: string
  naam: string
  verpakking: string | null
  eenheid: string
  m2_lengte: string | null
  volgorde: number
  actief: boolean
  nummer: string
}

export interface CategorieDto {
  id: string
  naam: string
  bundel: string
  volgorde: number
  actief: boolean
  producten: ProductDto[]
}

export interface BestelRegelDto {
  product: ProductDto
  aantal: number
  was: number | null
  geleverd: number
}

export interface RevisieDto {
  revisie: number
  verstuurd_op: string
  verstuurd_door_naam: string | null
  verzonden_naar: string
  mail_status: string
  mail_fout: string | null
  m2_totaal: string
  delta: { product_id: string; naam: string; oud: number; nieuw: number }[] | null
  aantal_regels: number
}

export interface BestellingDto {
  id: string
  nummer: string
  project_id: string
  project_naam: string | null
  leverancier_id: string
  leverancier_naam: string
  leverancier_email: string | null
  status: 'concept' | 'verstuurd' | 'geannuleerd'
  revisie: number
  heeft_concept_wijzigingen: boolean
  gewenste_leverdatum: string | null
  gewenste_levertijd: string | null
  leveradres: string | null
  contactpersoon: string | null
  opmerking: string | null
  annulering_reden: string | null
  m2_totaal: string
  aantal_regels: number
  aangemaakt_op: string
  bijgewerkt_op: string
  regels: BestelRegelDto[]
  revisies: RevisieDto[]
  transport_ids: string[]
}

export interface TransportDto {
  id: string
  project_id: string
  project_naam: string | null
  leverancier_id: string
  leverancier_naam: string
  bestelling_id: string | null
  bestelling_nummer: string | null
  soort: 'levering' | 'retour'
  datum: string
  tijdstip: string | null
  status: 'gepland' | 'bevestigd' | 'geleverd' | 'geannuleerd'
  status_bron: string
  status_reden: string | null
  regels: { product_id: string; naam: string; aantal: number; eenheid: string }[]
  samenvatting: string
  m2: string
  omschrijving: string | null
}

export interface WachtrisicoDto {
  project_id: string
  project_naam: string | null
  datum: string
  aantal_personen: number
  transport_id: string | null
  leverancier_naam: string | null
  samenvatting: string
}

export interface TransportProjectRijDto {
  project_id: string
  project_naam: string | null
  opdrachtgever: string | null
  is_actief: boolean
  per_datum: Record<string, TransportDto[]>
  week_transporten: number
  ploeg_label: string | null
}

export interface TransportWeekDto {
  jaar: number
  weeknummer: number
  maandag: string
  zondag: string
  projecten: TransportProjectRijDto[]
  wachtrisico: WachtrisicoDto[]
  aantal_transporten: number
  bestellingen_concept: number
  bestellingen_met_wijzigingen: number
  materiaalmatch_open: number
}

export interface StandRegelDto {
  product_id: string
  naam: string
  categorie: string
  eenheid: string
  geleverd: number
  retour: number
  op_locatie: number
  eerste_levering: string | null
  laatste_retour: string | null
  huurdagen_tot_vandaag: number
  huur_eenheden: string
  leveranciers: string[]
  m2: string
}

export interface MateriaalStandDto {
  project_id: string
  project_naam: string | null
  tot_en_met: string
  regels: StandRegelDto[]
  m2_op_locatie: string
  totaal_items: number
  leveranciers: string[]
}

export interface MateriaalmatchDto {
  document_id: string
  leverancier_id: string
  leverancier_naam: string | null
  project_id: string | null
  project_naam: string | null
  uitkomst: 'match' | 'afwijking' | 'niet_toetsbaar'
  aantal_regels_getoetst: number
  aantal_regels_afwijkend: number
  aantal_regels_onbekend: number
  details: {
    regels?: { omschrijving: string; product_naam?: string; hoeveelheid: string | null; verwacht_aantal?: string; verwacht_huur_eenheden?: string; huurdagen?: number; status: string }[]
    reden?: string | null
    stand?: { product_naam: string; op_locatie: number; huurdagen: number; huur_eenheden: string }[]
    m2_op_locatie?: string | null
  } | null
  berekend_op: string
  afwijking_bevestigd: boolean
  afwijking_bevestigd_op: string | null
}

const JSON_PUT = { method: 'PUT', headers: { 'Content-Type': 'application/json' } } as const

export function haalLeveranciers(administratieId: string, zoek = '', alleenActief = true): Promise<LeverancierDto[]> {
  const q = new URLSearchParams({ zoek, alleen_actief: String(alleenActief) })
  return apiJson(`/materiaal/${administratieId}/leveranciers?${q}`)
}

export function zetLeverancier(administratieId: string, payload: Partial<LeverancierDto> & { naam: string }): Promise<{ id: string }> {
  return apiJson(`/materiaal/${administratieId}/leveranciers`, { ...JSON_PUT, body: JSON.stringify(payload) })
}

export function haalCatalogus(administratieId: string, leverancierId: string, alleenActief = true): Promise<CategorieDto[]> {
  return apiJson(`/materiaal/${administratieId}/leveranciers/${leverancierId}/catalogus?alleen_actief=${alleenActief}`)
}

export function haalProducten(
  administratieId: string,
  params: { leverancier_id?: string | null; zoek?: string; pagina?: number; per_pagina?: number },
): Promise<{ items: ProductDto[]; totaal: number; pagina: number; per_pagina: number }> {
  const q = new URLSearchParams()
  if (params.leverancier_id) q.set('leverancier_id', params.leverancier_id)
  if (params.zoek) q.set('zoek', params.zoek)
  q.set('pagina', String(params.pagina ?? 1))
  q.set('per_pagina', String(params.per_pagina ?? 25))
  return apiJson(`/materiaal/${administratieId}/producten?${q}`)
}

export function zetCategorie(
  administratieId: string,
  payload: { id?: string | null; leverancier_id: string; naam: string; bundel: string; volgorde: number; actief: boolean },
): Promise<{ id: string }> {
  return apiJson(`/materiaal/${administratieId}/categorieen`, { ...JSON_PUT, body: JSON.stringify(payload) })
}

export function zetProduct(
  administratieId: string,
  payload: {
    id?: string | null
    leverancier_id: string
    categorie_id: string
    naam: string
    verpakking: string | null
    eenheid: string
    m2_lengte: string | null
    volgorde: number
    actief: boolean
  },
): Promise<{ id: string }> {
  return apiJson(`/materiaal/${administratieId}/producten`, { ...JSON_PUT, body: JSON.stringify(payload) })
}

export function seedUniversal(administratieId: string): Promise<{ leverancier_id: string; categorieen_nieuw: number; producten_nieuw: number; producten_bestaand: number }> {
  return apiPostJson(`/materiaal/${administratieId}/seed-universal`, {})
}

export function haalBestellingen(
  administratieId: string,
  params: { project_id?: string | null; zoek?: string; bestel_status?: string | null; pagina?: number; per_pagina?: number },
): Promise<{ items: BestellingDto[]; totaal: number; pagina: number; per_pagina: number }> {
  const q = new URLSearchParams()
  if (params.project_id) q.set('project_id', params.project_id)
  if (params.zoek) q.set('zoek', params.zoek)
  if (params.bestel_status) q.set('bestel_status', params.bestel_status)
  q.set('pagina', String(params.pagina ?? 1))
  q.set('per_pagina', String(params.per_pagina ?? 25))
  return apiJson(`/materiaal/${administratieId}/bestellingen?${q}`)
}

export function maakBestelling(
  administratieId: string,
  payload: { project_id: string; leverancier_id: string; gewenste_leverdatum?: string | null; gewenste_levertijd?: string | null },
): Promise<{ id: string }> {
  return apiPostJson(`/materiaal/${administratieId}/bestellingen`, payload)
}

export function haalBestelling(administratieId: string, bestellingId: string): Promise<BestellingDto> {
  return apiJson(`/materiaal/${administratieId}/bestellingen/${bestellingId}`)
}

export function werkConceptBij(
  administratieId: string,
  bestellingId: string,
  payload: {
    regels: Record<string, number>
    gewenste_leverdatum: string | null
    gewenste_levertijd: string | null
    leveradres: string | null
    contactpersoon: string | null
    opmerking: string | null
  },
): Promise<BestellingDto> {
  return apiJson(`/materiaal/${administratieId}/bestellingen/${bestellingId}/concept`, { ...JSON_PUT, body: JSON.stringify(payload) })
}

export function verstuurBestelling(administratieId: string, bestellingId: string): Promise<BestellingDto> {
  return apiPostJson(`/materiaal/${administratieId}/bestellingen/${bestellingId}/versturen`, { koppel_levering: true })
}

export function annuleerBestelling(administratieId: string, bestellingId: string, reden: string): Promise<BestellingDto> {
  return apiPostJson(`/materiaal/${administratieId}/bestellingen/${bestellingId}/annuleren`, { reden })
}

export async function haalBestellingPdfBlob(administratieId: string, bestellingId: string, revisie: number): Promise<string> {
  const resp = await apiFetch(`/materiaal/${administratieId}/bestellingen/${bestellingId}/revisies/${revisie}/pdf`)
  if (!resp.ok) throw new Error(`PDF ophalen mislukt (${resp.status})`)
  return URL.createObjectURL(await resp.blob())
}

export function haalTransportWeek(administratieId: string, jaar: number, weeknummer: number): Promise<TransportWeekDto> {
  return apiJson(`/materiaal/${administratieId}/transport?jaar=${jaar}&weeknummer=${weeknummer}`)
}

export function planTransport(
  administratieId: string,
  payload: {
    project_id: string
    leverancier_id: string
    soort: 'levering' | 'retour'
    datum: string
    tijdstip: string | null
    regels: Record<string, number>
    omschrijving: string | null
    bestelling_id?: string | null
  },
): Promise<TransportDto> {
  return apiPostJson(`/materiaal/${administratieId}/transport`, payload)
}

export function wijzigTransport(
  administratieId: string,
  transportId: string,
  payload: { datum?: string | null; tijdstip?: string | null; regels?: Record<string, number> | null; omschrijving?: string | null; project_id?: string | null },
): Promise<TransportDto> {
  return apiJson(`/materiaal/${administratieId}/transport/${transportId}`, { ...JSON_PUT, body: JSON.stringify(payload) })
}

export function zetTransportStatus(administratieId: string, transportId: string, status: TransportDto['status'], reden?: string): Promise<TransportDto> {
  return apiPostJson(`/materiaal/${administratieId}/transport/${transportId}/status`, { status, reden: reden ?? null })
}

export function haalMateriaalstand(administratieId: string, projectId: string): Promise<MateriaalStandDto> {
  return apiJson(`/materiaal/${administratieId}/stand/${projectId}`)
}

export function haalMateriaalmatch(administratieId: string, documentId: string): Promise<MateriaalmatchDto | null> {
  return apiJson(`/materiaal/${administratieId}/match/${documentId}`)
}

export function herberekenMateriaalmatch(administratieId: string, documentId: string): Promise<MateriaalmatchDto | null> {
  return apiPostJson(`/materiaal/${administratieId}/match/${documentId}/herbereken`, {})
}

/** m²-som client-side alleen ter WEERGAVE tijdens het typen (de server rekent bindend, zelfde formule). */
export const M2_DELER = 4.6
export function schatM2(regels: Record<string, number>, producten: Map<string, ProductDto>): number {
  let som = 0
  for (const [pid, aantal] of Object.entries(regels)) {
    const p = producten.get(pid)
    if (!p || p.m2_lengte === null || !aantal) continue
    som += aantal * Number(p.m2_lengte)
  }
  return Math.round((som / M2_DELER) * 100) / 100
}
