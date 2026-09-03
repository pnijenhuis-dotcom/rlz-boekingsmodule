// Voorraad-aansluiting fase 1 (bouwrun 28-08 blok D, mockup voorraad-aansluiting.html) — spiegelt
// backend/app/voorraad/schemas.py. Aantallen/bedragen als string (Decimal), nooit berekend in de
// client (code voor cijfers zit in de backend). Alle paden onder /administraties (bestaande proxy-prefix).
// v2 (30-08): soort-label artikel/dienst/transport (dienstregels blijven bewaard, tellen niet), dienst-inzage
// (§3) + codes-inzage (§4) mét correcties — controlemechanisme, nooit blind vertrouwen.
export type VoorraadSoort = 'artikel' | 'dienst' | 'transport'
export const SOORT_LABEL: Record<VoorraadSoort, string> = { artikel: 'artikel', dienst: 'dienst', transport: 'transport' }
import { apiFetch, apiJson } from '../api/client'

export interface GroepAansluitingDto {
  artikelgroep_id: string
  naam: string
  eenheid: string
  tolerantie_pct: string
  begin: string
  inkoop: string
  verkoop: string
  theoretisch: string
  systeemstand: string | null
  telling_datum: string | null
  verschil: string | null
  verschil_pct: string | null
  signaal: 'binnen_tolerantie' | 'onderzoeken' | 'geen_telling'
  onzeker_pct: string
  regels_in: number
  regels_uit: number
}

export interface AansluitingDto {
  administratie_id: string
  van: string
  tot: string
  groepen: GroepAansluitingDto[]
  niet_genormaliseerd_in: number
  niet_genormaliseerd_uit: number
  onzeker_totaal: number
  regels_totaal: number
  // v2: dienst-/transportregels in de periode (soort-label) — niet in de aansluiting, wél bewaard.
  dienst_regels: number
  transport_regels: number
  bronnen: Record<string, string>
}

export interface VoorraadRegelDto {
  id: string
  // Herkomst (migratie 0087): een lokaal document óf een RLZ-verkoopfactuur (bron 'rlz_verkoop' — de
  // eigen RLZ-facturen van de administratie via de dagelijkse leesroute; blok A 29-08).
  document_id: string | null
  rlz_document_id: string | null
  rlz_referentie: string | null
  richting: 'in' | 'uit'
  bron: string
  datum: string
  relatie_naam: string | null
  artikeltekst: string
  // v2: artikelcode (normalisatiesleutel per richting) + soort.
  artikelcode: string | null
  soort: VoorraadSoort
  aantal: string | null
  eenheid: string | null
  prijs: string | null
  netto_bedrag: string | null
  artikelgroep_id: string | null
  artikelgroep_naam: string | null
  // 'uitgesloten' = legacy pre-0088 (wordt door de hernormalisatie omgezet naar soort dienst/transport).
  normalisatie_status: 'genormaliseerd' | 'onzeker' | 'uitgesloten' | 'niet_genormaliseerd'
  normalisatie_zekerheid: string | null
}

/** §3 "als dienst geclassificeerd": één rij per unieke (leverancier, tekst) mét aantallen en de bron. */
export interface DienstTekstDto {
  voorbeeld_regel_id: string
  artikeltekst: string
  artikeltekst_norm: string
  vendor_id: string | null
  relatie_naam: string | null
  soort: VoorraadSoort
  bron: 'regel' | 'ai' | 'handmatig' | 'legacy' | string
  richtingen: string
  regels: number
  som_aantal: string
  som_netto: string
}

/** §4 codes-inzage: koppeling code → groep/soort per richting + leverancier. */
export interface ArtikelcodeDto {
  id: string
  richting: 'in' | 'uit'
  vendor_id: string | null
  relatie_naam: string | null
  code: string
  soort: VoorraadSoort
  artikelgroep_id: string | null
  artikelgroep_naam: string | null
  zekerheid: string | null
  bron: 'ai' | 'handmatig' | string
  voorbeeld_tekst: string | null
  regels: number
  teksten: number
}

export interface ArtikelgroepDto {
  id: string
  naam: string
  eenheid: string
  tolerantie_pct: string
  actief: boolean
}

export interface DagStandDto {
  datum: string
  inkoop: string
  verkoop: string
  stand: string
}

/** Server-side gepagineerde lijst (B3.3, design-ronde 03-09): regels, diensten en artikelcodes komen
 * nooit meer als 7-jaar-dump binnen. Default 25 per pagina, max 200. */
export interface GepagineerdDto<T> {
  rijen: T[]
  totaal: number
  pagina: number
  per_pagina: number
}

/** Eén artikelgroep buiten tolerantie op de kantoorbrede landing Inzicht › Voorraad (B3, 03-09;
 * mockup inzicht-kantoorbreed.html ⑤). `zwaarte` = STATUS-kleur (oranje | rood) — de server bepaalt. */
export interface VoorraadVerschilRijDto {
  administratie_id: string
  administratie_naam: string
  artikelgroep_id: string
  naam: string
  eenheid: string
  tolerantie_pct: string
  theoretisch: string
  systeemstand: string
  telling_datum: string
  verschil: string
  verschil_pct: string | null
  zwaarte: 'oranje' | 'rood'
  tot: string
}

export interface VoorraadVerschilTellersDto {
  groepen: number
  administraties: number
  administraties_met_voorraad: number
}

export interface VoorraadVerschillenLijstDto extends GepagineerdDto<VoorraadVerschilRijDto> {
  tellers: VoorraadVerschilTellersDto
  facetten: { id: string; naam: string; aantal: number }[]
  van: string
  tot: string
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export function haalAansluiting(administratieId: string, van: string, tot: string): Promise<AansluitingDto> {
  return apiJson(`/administraties/${administratieId}/voorraad/aansluiting?van=${van}&tot=${tot}`)
}

export const VOORRAAD_PER_PAGINA = 25

/** Kantoorbrede landing (B3.1): artikelgroepen buiten tolerantie over álle voorraad-administraties in
 * scope, zwaarste eerst; `administratieId` = facet (leeg = alle), `q` zoekt op artikelgroep. */
export function haalVoorraadVerschillen(
  opties: { administratieId?: string; q?: string; pagina?: number; tot?: string } = {},
): Promise<VoorraadVerschillenLijstDto> {
  const params = new URLSearchParams({ pagina: String(opties.pagina ?? 1) })
  if (opties.administratieId) params.set('administratie_id', opties.administratieId)
  if (opties.q) params.set('q', opties.q)
  if (opties.tot) params.set('tot', opties.tot)
  return apiJson(`/voorraad/verschillen?${params.toString()}`)
}

/** Alleen de tellers (KPI-/nav-chip). */
export function haalVoorraadVerschillenStand(): Promise<VoorraadVerschilTellersDto> {
  return apiJson('/voorraad/verschillen/stand')
}

export function haalVoorraadRegels(
  administratieId: string,
  van: string,
  tot: string,
  filter: {
    artikelgroepId?: string
    /** Eén of meer statussen (komma-gescheiden server-side, bv. niet_genormaliseerd + onzeker in één lijst). */
    status?: VoorraadRegelDto['normalisatie_status'] | VoorraadRegelDto['normalisatie_status'][]
    soort?: VoorraadSoort
    pagina?: number
  } = {},
): Promise<GepagineerdDto<VoorraadRegelDto>> {
  const params = new URLSearchParams({ van, tot, pagina: String(filter.pagina ?? 1) })
  if (filter.artikelgroepId) params.set('artikelgroep_id', filter.artikelgroepId)
  if (filter.status) params.set('normalisatie_status', Array.isArray(filter.status) ? filter.status.join(',') : filter.status)
  if (filter.soort) params.set('soort', filter.soort)
  return apiJson(`/administraties/${administratieId}/voorraad/regels?${params.toString()}`)
}

export function haalDienstTeksten(administratieId: string, van: string, tot: string, pagina = 1): Promise<GepagineerdDto<DienstTekstDto>> {
  return apiJson(`/administraties/${administratieId}/voorraad/diensten?van=${van}&tot=${tot}&pagina=${pagina}`)
}

export function haalArtikelcodes(administratieId: string, pagina = 1): Promise<GepagineerdDto<ArtikelcodeDto>> {
  return apiJson(`/administraties/${administratieId}/voorraad/artikelcodes?pagina=${pagina}`)
}

export function corrigeerArtikelcode(
  administratieId: string,
  koppelingId: string,
  invoer: { soort: VoorraadSoort; artikelgroep_id: string | null },
): Promise<{ herrekend: number }> {
  return apiJson(`/administraties/${administratieId}/voorraad/artikelcodes/${koppelingId}/corrigeer`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(invoer),
  })
}

export function haalDagstanden(administratieId: string, artikelgroepId: string, van: string, tot: string): Promise<DagStandDto[]> {
  return apiJson(`/administraties/${administratieId}/voorraad/groepen/${artikelgroepId}/dagstanden?van=${van}&tot=${tot}`)
}

export function haalArtikelgroepen(administratieId: string): Promise<ArtikelgroepDto[]> {
  return apiJson(`/administraties/${administratieId}/voorraad/groepen`)
}

export function maakArtikelgroep(administratieId: string, naam: string, eenheid: string, tolerantiePct: string): Promise<ArtikelgroepDto> {
  return apiJson(`/administraties/${administratieId}/voorraad/groepen`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ naam, eenheid, tolerantie_pct: tolerantiePct }),
  })
}

export async function zetTolerantie(administratieId: string, artikelgroepId: string, tolerantiePct: string): Promise<void> {
  await apiFetch(`/administraties/${administratieId}/voorraad/groepen/${artikelgroepId}/tolerantie`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ tolerantie_pct: tolerantiePct }),
  })
}

export async function voerTellingIn(
  administratieId: string,
  invoer: { artikelgroep_id: string; datum: string; aantal: string; opmerking: string | null },
): Promise<void> {
  await apiFetch(`/administraties/${administratieId}/voorraad/tellingen`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(invoer),
  })
}

export function corrigeerNormalisatie(
  administratieId: string,
  invoer: { regel_id: string; soort: VoorraadSoort; artikelgroep_id: string | null },
): Promise<{ herrekend: number }> {
  return apiJson(`/administraties/${administratieId}/voorraad/normalisatie/corrigeer`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(invoer),
  })
}

export function herrekenVoorraad(administratieId: string): Promise<{
  inkoop_documenten: number
  inkoop_regels: number
  verkoop_documenten: number
  verkoop_regels: number
  rlz_regels: number
}> {
  return apiJson(`/administraties/${administratieId}/voorraad/herreken`, { method: 'POST' })
}

/** Bron van een classificatie (dienst-/codes-inzage), leesbaar. */
export function classificatieBronLabel(bron: string): string {
  if (bron === 'regel') return 'regex (automatisch)'
  if (bron === 'ai') return 'AI-voorstel'
  if (bron === 'handmatig') return 'handmatig bevestigd'
  if (bron === 'legacy') return 'vóór v2 (nog te hernormaliseren)'
  return bron
}

/** Leesbare herkomst van een factuurregel (drill-down): app-document of RLZ-verkoopfactuur. */
export function bronLabel(r: Pick<VoorraadRegelDto, 'bron' | 'rlz_referentie'>): string {
  if (r.bron === 'rlz_verkoop') return `RLZ-verkoopfactuur${r.rlz_referentie ? ` ${r.rlz_referentie}` : ''}`
  if (r.bron === 'verkoop_regel') return 'verkoopfactuur (app)'
  if (r.bron === 'inkoop_veldvoorstel') return 'inkoopfactuur (scan)'
  return r.bron
}

/** Getalweergave met NL-notatie; null = em-dash. */
export function aantal(waarde: string | null | undefined, decimalen = 0): string {
  if (waarde === null || waarde === undefined) return '—'
  const n = Number(waarde)
  if (Number.isNaN(n)) return waarde
  return n.toLocaleString('nl-NL', { minimumFractionDigits: 0, maximumFractionDigits: decimalen })
}

/** Verschil-weergave op de kantoorbrede lijst: "−88 st (−8,8%)"; onbepaalbaar % = alleen het aantal. */
export function verschilTekst(r: Pick<VoorraadVerschilRijDto, 'verschil' | 'verschil_pct' | 'eenheid'>): string {
  const teken = Number(r.verschil) > 0 ? '+' : ''
  const basis = `${teken}${aantal(r.verschil, 0)} ${r.eenheid}`
  if (r.verschil_pct === null) return `${basis} (theoretisch 0)`
  return `${basis} (${Number(r.verschil_pct) > 0 ? '+' : ''}${aantal(r.verschil_pct, 1)}%)`
}

/** Detail-deeplink per administratie (bestaande `?administratie=`-vorm) mét voorgefilterde groep/periode. */
export function detailPad(r: Pick<VoorraadVerschilRijDto, 'administratie_id' | 'artikelgroep_id'>, van: string, tot: string): string {
  return `/voorraad?administratie=${r.administratie_id}&groep=${r.artikelgroep_id}&van=${van}&tot=${tot}`
}

/** Signaaltekst conform mockup: "✓ binnen tolerantie" / "⚑ −8,8% — onderzoeken" / "— nog geen telling". */
export function signaalTekst(g: GroepAansluitingDto): { tekst: string; soort: 'ok' | 'vlag' | 'geen' } {
  if (g.signaal === 'geen_telling') return { tekst: 'nog geen telling', soort: 'geen' }
  if (g.signaal === 'binnen_tolerantie') return { tekst: 'binnen tolerantie', soort: 'ok' }
  const pct = g.verschil_pct !== null ? `${Number(g.verschil_pct) > 0 ? '+' : ''}${aantal(g.verschil_pct, 1)}%` : aantal(g.verschil, 0)
  return { tekst: `${pct} — onderzoeken`, soort: 'vlag' }
}
