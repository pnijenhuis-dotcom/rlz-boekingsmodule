// Voorraad-aansluiting fase 1 (bouwrun 28-08 blok D, mockup voorraad-aansluiting.html) — spiegelt
// backend/app/voorraad/schemas.py. Aantallen/bedragen als string (Decimal), nooit berekend in de
// client (code voor cijfers zit in de backend). Alle paden onder /administraties (bestaande proxy-prefix).
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
  aantal: string | null
  eenheid: string | null
  prijs: string | null
  netto_bedrag: string | null
  artikelgroep_id: string | null
  artikelgroep_naam: string | null
  normalisatie_status: 'genormaliseerd' | 'onzeker' | 'uitgesloten' | 'niet_genormaliseerd'
  normalisatie_zekerheid: string | null
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

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export function haalAansluiting(administratieId: string, van: string, tot: string): Promise<AansluitingDto> {
  return apiJson(`/administraties/${administratieId}/voorraad/aansluiting?van=${van}&tot=${tot}`)
}

export function haalVoorraadRegels(
  administratieId: string,
  van: string,
  tot: string,
  filter: { artikelgroepId?: string; status?: VoorraadRegelDto['normalisatie_status'] } = {},
): Promise<VoorraadRegelDto[]> {
  const params = new URLSearchParams({ van, tot })
  if (filter.artikelgroepId) params.set('artikelgroep_id', filter.artikelgroepId)
  if (filter.status) params.set('normalisatie_status', filter.status)
  return apiJson(`/administraties/${administratieId}/voorraad/regels?${params.toString()}`)
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
  invoer: { regel_id: string; artikelgroep_id: string | null; uitgesloten: boolean },
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

/** Signaaltekst conform mockup: "✓ binnen tolerantie" / "⚑ −8,8% — onderzoeken" / "— nog geen telling". */
export function signaalTekst(g: GroepAansluitingDto): { tekst: string; soort: 'ok' | 'vlag' | 'geen' } {
  if (g.signaal === 'geen_telling') return { tekst: 'nog geen telling', soort: 'geen' }
  if (g.signaal === 'binnen_tolerantie') return { tekst: 'binnen tolerantie', soort: 'ok' }
  const pct = g.verschil_pct !== null ? `${Number(g.verschil_pct) > 0 ? '+' : ''}${aantal(g.verschil_pct, 1)}%` : aantal(g.verschil, 0)
  return { tekst: `${pct} — onderzoeken`, soort: 'vlag' }
}
