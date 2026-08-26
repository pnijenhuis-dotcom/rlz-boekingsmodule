import type { DocumentListItemDto } from '../api/types'

export function formatDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatDatumKort(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { dateStyle: 'medium' })
}

/** Celklasse voor een bedragkolom: negatief = `amount neg` (--danger, designpass v2) — één plek
 * voor de geldsemantiek in lijsten; niet-numeriek/leeg = neutraal. */
export function amountKlasse(bedrag: string | number | null | undefined): string {
  if (bedrag === null || bedrag === undefined) return 'amount'
  const numeriek = typeof bedrag === 'number' ? bedrag : Number(bedrag)
  return Number.isFinite(numeriek) && numeriek < 0 ? 'amount neg' : 'amount'
}

export function formatBedrag(bedrag: string | null): string {
  if (bedrag === null) return '—'
  const numeriek = Number(bedrag)
  if (Number.isNaN(numeriek)) return '—'
  return numeriek.toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

/** "vandaag" / "1 dag" / "n dagen" — ouderdom van het oudste stuk (mockup-kolom "Oudste"). */
export function ouderdomLabel(iso: string): string {
  const dagen = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (dagen <= 0) return 'vandaag'
  return dagen === 1 ? '1 dag' : `${dagen} dagen`
}

/** Documentsoort → meervoudslabel voor de standen-tabel op de klantpagina. */
export const SOORT_LABELS: Record<string, string> = {
  inkoopfactuur: 'Inkoopfacturen',
  kassarapport: 'Omzetrapporten (kassarapporten)',
  verkoopfactuur: 'Verkoopfacturen',
  waarborg: 'Waarborg-berichten',
}

export function soortLabel(soort: string): string {
  return SOORT_LABELS[soort] ?? soort
}

/** Vaste soort-volgorde (mockup-norm 25-08: minimaal Inkoopfacturen / Verkoopfacturen) — gedeeld
 * door de tabs van de documentenlijst en de "volgende document"-keuze ná boeken/afwijzen
 * (deel 4 punt 1). Onbekende soorten volgen achteraan. */
export const SOORT_VOLGORDE = ['inkoopfactuur', 'verkoopfactuur', 'kassarapport', 'waarborg']

/** Route per documentsoort/-status — één plek voor het klik-doel van een documentregel
 * (mockup: klik op een vraag-regel opent de vráág, niet het controlescherm). */
export function documentRoute(administratieId: string, d: DocumentListItemDto): string {
  const isVerwijderd = d.status === 'verwijderd'
  if (d.status === 'vraag_open' && !isVerwijderd) {
    return `/?administratie=${administratieId}&sectie=vragen&document=${d.id}`
  }
  if (d.soort === 'kassarapport') return `/omzet/${administratieId}/${d.id}`
  if (d.soort === 'verkoopfactuur') return `/verkoop/${administratieId}/${d.id}`
  if (d.soort === 'waarborg') return `/waarborg/${administratieId}/${d.id}`
  return `/documenten/${administratieId}/${d.id}`
}

/** Openstaand = niet terminaal (zelfde definitie als de backend-overzichtstellers:
 * geboekt/verwijderd/gesplitst tellen niet als openstaand werk). */
export function isOpenstaand(d: DocumentListItemDto): boolean {
  return d.status !== 'geboekt' && d.status !== 'verwijderd' && d.status !== 'gesplitst'
}
