// Verplichtingen (offertes/prijsopgaven/opdrachtbevestigingen) — besluiten Peter 04-09, mockup
// offerte-matching.html ①–⑧ = norm. Eén documenttype "verplichting" mét soort-label: kantoor
// controleert het veldvoorstel, de bestaande accorderingsflow legt het akkoord vast (wie/wanneer/
// welk bedrag) en elke latere inkoopfactuur wordt er CUMULATIEF tegen gematcht. Geen RLZ-/Odoo-
// boeking — dossierstuk mét verbruiksstand.
//
// Spiegelt backend/app/verplichting/schemas.py. Bedragen/percentages komen als string (Decimal)
// binnen; de client formatteert alleen en rekent nooit (kernprincipe "geld in code").
import { apiJson, apiPostJson } from '../api/client'

const JSON_HEADERS = { 'Content-Type': 'application/json' }

/** Soort-label van de verplichting (①) — het documenttype is één, het label onderscheidt. */
export type VerplichtingSoortLabel = 'offerte' | 'prijsopgave' | 'opdrachtbevestiging'

export const SOORT_LABEL_TEKST: Record<VerplichtingSoortLabel, string> = {
  offerte: 'Offerte',
  prijsopgave: 'Prijsopgave',
  opdrachtbevestiging: 'Opdrachtbevestiging',
}

export const SOORT_LABEL_OPTIES: VerplichtingSoortLabel[] = ['offerte', 'prijsopgave', 'opdrachtbevestiging']

/** Herkomst per veld: 'ai' (extractie), 'template' (deterministische terugval), 'mens' (opgeslagen
 * door de controleur) of null (leeg/onbekend) — voedt de herkomst-chip naast het veld. */
export type VerplichtingHerkomst = 'ai' | 'template' | 'mens'

export type VerplichtingVeld =
  | 'soort_label'
  | 'leverancier'
  | 'project'
  | 'offertenummer'
  | 'totaalbedrag_excl'
  | 'geldig_tot'
  | 'omschrijving'

export type VerplichtingCheckStatus = 'ok' | 'blokkerend' | 'signaal' | 'niet_van_toepassing'

export interface VerplichtingCheckDto {
  naam: string
  status: VerplichtingCheckStatus
  melding: string
}

export interface VerplichtingChecksDto {
  checks: VerplichtingCheckDto[]
  geblokkeerd: boolean
}

export interface VerplichtingSuggestieDto {
  vendor_id?: string
  project_id?: string
  naam: string | null
  match: string | null
}

export interface VerplichtingGoedgekeurdDto {
  bedrag_excl: string | null
  op: string | null
  door_naam: string | null
}

export interface VerplichtingVerbruikDto {
  verbruikt_excl: string
  totaal_excl: string | null
  /** Server rekent; de client toont alleen (③ cumulatief, grens = het offertebedrag). */
  percentage: number
  over_excl: string | null
}

export interface VerplichtingVervallenDto {
  op: string | null
  reden: string | null
  door_naam: string | null
}

export interface VerplichtingFactuurDto {
  document_id: string
  referentie: string | null
  factuurdatum: string | null
  bedrag_excl: string | null
  status: string
  /** True = de factuur is geboekt en het verbruik is verrekend (telt mee in de stand). */
  verrekend: boolean
}

export interface VerplichtingVoorstelDto {
  document_id: string
  status: string
  soort_label: VerplichtingSoortLabel | null
  vendor_id: string | null
  vendor_naam: string | null
  project_id: string | null
  project_naam: string | null
  offertenummer: string | null
  datum: string | null
  totaalbedrag_excl: string | null
  geldig_tot: string | null
  omschrijving: string | null
  opgeslagen: boolean
  herkomst: Partial<Record<VerplichtingVeld, VerplichtingHerkomst | null>>
  zekerheid: Partial<Record<VerplichtingVeld, number>>
  zekerheid_drempel: number
  vendor_suggestie: VerplichtingSuggestieDto | null
  project_suggestie: VerplichtingSuggestieDto | null
  goedgekeurd: VerplichtingGoedgekeurdDto | null
  verbruik: VerplichtingVerbruikDto | null
  vervallen: VerplichtingVervallenDto | null
  gekoppelde_facturen: VerplichtingFactuurDto[]
  checks: VerplichtingCheckDto[]
  ai_overgeslagen_reden: string | null
}

export interface VerplichtingVoorstelInput {
  soort_label: VerplichtingSoortLabel | null
  vendor_id: string | null
  project_id: string | null
  offertenummer: string | null
  datum: string | null
  totaalbedrag_excl: string | null
  geldig_tot: string | null
  omschrijving: string | null
}

// --- Factuur ↔ offerte-match ------------------------------------------------------------------

/** ② Match-sleutel = leverancier (crediteur-kenmerk) + project; het offertenummer op de factuur
 * versterkt. `geen_verplichting`/`niet_toetsbaar` = stil (geen chip, geen melding). */
export type OfferteMatchUitkomst =
  | 'binnen'
  | 'buiten'
  | 'geen_match'
  | 'meerdere_kandidaten'
  | 'niet_toetsbaar'
  | 'geen_verplichting'

export interface OfferteMatchVerplichtingDto {
  document_id: string
  offertenummer: string | null
  soort_label: VerplichtingSoortLabel | null
  leverancier_naam: string | null
  project_naam: string | null
  totaal_excl: string | null
  goedgekeurd_op: string | null
  goedgekeurd_door_naam: string | null
}

export interface OfferteKandidaatDto {
  document_id: string
  offertenummer: string | null
  soort_label: VerplichtingSoortLabel | null
  totaal_excl: string | null
  verbruikt_excl: string | null
  project_naam: string | null
  geldig_tot: string | null
}

export interface VerplichtingMatchDto {
  document_id: string
  uitkomst: OfferteMatchUitkomst
  verplichting: OfferteMatchVerplichtingDto | null
  bedrag_excl: string | null
  verbruik_voor: string | null
  verbruik_na: string | null
  percentage_na: number | null
  overschrijding_excl: string | null
  handmatig_gekoppeld: boolean
  kandidaten: OfferteKandidaatDto[]
  /** Server levert dit als `datetime | None` — null zolang er nog niets berekend is. */
  berekend_op: string | null
  melding: string
}

/** Korte vorm op de accordeur-wachtrij + de documentenlijst-chip. */
export interface OfferteMatchKortDto {
  uitkomst: 'binnen' | 'buiten'
  offertenummer: string | null
  leverancier_naam: string | null
  goedgekeurd_door_naam: string | null
  goedgekeurd_op: string | null
  bedrag_excl: string | null
  verbruik_na: string | null
  totaal_excl: string | null
  percentage_na: number | null
  overschrijding_excl: string | null
}

// --- Inzicht › Verplichtingen (kantoorbreed) ---------------------------------------------------

export type VerplichtingLijstStatus = 'lopend' | 'overschreden' | 'vervallen'
export type VerplichtingStatusFacet = VerplichtingLijstStatus | 'alle'

export const LIJST_STATUS_FACETTEN: VerplichtingStatusFacet[] = ['lopend', 'overschreden', 'vervallen', 'alle']

export const LIJST_STATUS_LABEL: Record<VerplichtingStatusFacet, string> = {
  lopend: 'lopend',
  overschreden: 'overschreden',
  vervallen: 'vervallen',
  alle: 'alle',
}

export interface VerplichtingKantoorRijDto {
  document_id: string
  administratie_id: string
  administratie_naam: string
  offertenummer: string | null
  soort_label: VerplichtingSoortLabel | null
  leverancier_naam: string | null
  project_naam: string | null
  totaal_excl: string | null
  verbruikt_excl: string
  /** null = niet te bepalen (geen goedgekeurd bedrag) — de balk staat dan op 0. */
  percentage: number | null
  over_excl: string | null
  goedgekeurd_op: string | null
  goedgekeurd_door_naam: string | null
  geldig_tot: string | null
  status: VerplichtingLijstStatus
  facturen: VerplichtingFactuurDto[]
}

export interface VerplichtingKantoorLijstDto {
  rijen: VerplichtingKantoorRijDto[]
  totaal: number
  pagina: number
  per_pagina: number
  administraties_in_selectie: number
  tellers: { lopend: number; overschreden: number; vervallen: number }
  facetten: {
    status: Partial<Record<VerplichtingStatusFacet, number>>
    administraties: { administratie_id: string; naam: string; aantal: number }[]
  }
}

// --- Routes ------------------------------------------------------------------------------------

function voorstelPad(administratieId: string, documentId: string): string {
  return `/administraties/${administratieId}/verplichtingen/documenten/${documentId}`
}

export function haalVerplichtingVoorstel(administratieId: string, documentId: string): Promise<VerplichtingVoorstelDto> {
  return apiJson<VerplichtingVoorstelDto>(`${voorstelPad(administratieId, documentId)}/voorstel`)
}

export function slaVerplichtingVoorstelOp(
  administratieId: string,
  documentId: string,
  invoer: VerplichtingVoorstelInput,
): Promise<VerplichtingVoorstelDto> {
  return apiJson<VerplichtingVoorstelDto>(`${voorstelPad(administratieId, documentId)}/voorstel`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(invoer),
  })
}

export function voerVerplichtingChecksUit(administratieId: string, documentId: string): Promise<VerplichtingChecksDto> {
  return apiPostJson<VerplichtingChecksDto>(`${voorstelPad(administratieId, documentId)}/checks`, {})
}

/** ⑥ Laten vervallen: stopt nieuwe matches, gematchte facturen blijven ongemoeid. Reden verplicht;
 * alleen op een geaccordeerde verplichting (server 409 anders). */
export function laatVerplichtingVervallen(
  administratieId: string,
  documentId: string,
  reden: string,
): Promise<VerplichtingVoorstelDto> {
  return apiPostJson<VerplichtingVoorstelDto>(`${voorstelPad(administratieId, documentId)}/vervallen`, { reden })
}

export function haalOfferteMatch(administratieId: string, documentId: string): Promise<VerplichtingMatchDto> {
  return apiJson<VerplichtingMatchDto>(`/administraties/${administratieId}/documenten/${documentId}/verplichting-match`)
}

/** "Koppel offerte…" (②) — `null` = ontkoppelen; 409 als de verplichting niet (meer) lopend is. */
export function koppelOfferte(
  administratieId: string,
  documentId: string,
  verplichtingDocumentId: string | null,
): Promise<VerplichtingMatchDto> {
  return apiPostJson<VerplichtingMatchDto>(
    `/administraties/${administratieId}/documenten/${documentId}/verplichting-match/koppel`,
    { verplichting_document_id: verplichtingDocumentId },
  )
}

export function haalVerplichtingenKantoorbreed(params: {
  pagina: number
  q?: string
  administratieId?: string | null
  status?: VerplichtingStatusFacet
}): Promise<VerplichtingKantoorLijstDto> {
  const p = new URLSearchParams()
  p.set('pagina', String(params.pagina))
  p.set('status', params.status ?? 'lopend')
  if (params.q) p.set('q', params.q)
  if (params.administratieId) p.set('administratie_id', params.administratieId)
  // Query buiten het letterlijke pad houden: `/verplichtingen` is een EXACT proxy-pad (het is
  // ook een SPA-route) — de dev-proxy-guard leest het literal-deel van de template.
  const query = p.toString()
  return apiJson<VerplichtingKantoorLijstDto>(`/verplichtingen${query ? `?${query}` : ''}`)
}

// --- Presentatiehelpers (puur) ----------------------------------------------------------------

/** Breedte van de verbruiksbalk in procenten — afgekapt op 0–100 (een overschrijding is vol +
 * rood; het bedrag erover staat in de chip, nooit in de balkbreedte). */
export function balkBreedte(percentage: number | null | undefined): number {
  if (percentage === null || percentage === undefined || !Number.isFinite(percentage)) return 0
  return Math.min(100, Math.max(0, percentage))
}

export function percentageTekst(percentage: number | null | undefined): string {
  if (percentage === null || percentage === undefined || !Number.isFinite(percentage)) return '—'
  return `${Math.round(percentage)}%`
}

/** ⑤/B6: het handelingsperspectief bij "buiten offerte" — een offerte rekt niet op. */
export const MEERWERK_PERSPECTIEF =
  'Meerwerk rekt een offerte niet op — laat aanvullend werk als aparte verplichting accorderen.'
