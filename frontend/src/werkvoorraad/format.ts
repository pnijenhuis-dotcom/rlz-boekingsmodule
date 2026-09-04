import type { DocumentListItemDto } from '../api/types'
import { lijstContextNaarParams, type LijstContext } from './lijstContext'

export function formatDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

/** Binnenkomst-metaregel in de documentenlijst (punt 3a): "26 aug, 16:42" — zonder jaar zolang
 * het dit kalenderjaar is, mét jaar daarbuiten ("26 aug 2025, 16:42"). */
export function formatBinnenkomst(iso: string, nu: Date = new Date()): string {
  const d = new Date(iso)
  const zelfdeJaar = d.getFullYear() === nu.getFullYear()
  const datum = d.toLocaleDateString('nl-NL', zelfdeJaar ? { day: 'numeric', month: 'short' } : { dateStyle: 'medium' })
  const tijd = d.toLocaleTimeString('nl-NL', { hour: '2-digit', minute: '2-digit' })
  return `${datum}, ${tijd}`
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
  // Verplichtingen (blok B 04-09, mockup offerte-matching ①): offertes/prijsopgaven/
  // opdrachtbevestigingen — eigen tab in de werkvoorraad, eigen reviewscherm, geen boeking.
  verplichting: 'Verplichtingen (offertes)',
}

export function soortLabel(soort: string): string {
  return SOORT_LABELS[soort] ?? soort
}

/** Vaste soort-volgorde (mockup-norm 25-08: minimaal Inkoopfacturen / Verkoopfacturen) — gedeeld
 * door de tabs van de documentenlijst en de "volgende document"-keuze ná boeken/afwijzen
 * (deel 4 punt 1). Onbekende soorten volgen achteraan. */
export const SOORT_VOLGORDE = ['inkoopfactuur', 'verplichting', 'verkoopfactuur', 'kassarapport', 'waarborg']

/** Route per documentsoort/-status — één plek voor het klik-doel van een documentregel
 * (mockup: klik op een vraag-regel opent de vráág, niet het controlescherm). Mét lijstcontext
 * (punt 1) reist de tab/filter/zoekterm als query mee naar het inkoop-controlescherm; de andere
 * reviewschermen kennen die context (nog) niet en krijgen 'm bewust niet. */
export function documentRoute(administratieId: string, d: DocumentListItemDto, context: LijstContext | null = null): string {
  const isVerwijderd = d.status === 'verwijderd'
  if (d.status === 'vraag_open' && !isVerwijderd) {
    return `/?administratie=${administratieId}&sectie=vragen&document=${d.id}`
  }
  if (d.soort === 'kassarapport') return `/omzet/${administratieId}/${d.id}`
  if (d.soort === 'verkoopfactuur') return `/verkoop/${administratieId}/${d.id}`
  if (d.soort === 'waarborg') return `/waarborg/${administratieId}/${d.id}`
  if (d.soort === 'verplichting') return `/verplichting/${administratieId}/${d.id}`
  const q = lijstContextNaarParams(context)
  return `/documenten/${administratieId}/${d.id}${q ? `?${q}` : ''}`
}

/** Terminale statussen — zelfde definitie als de backend-overzichtstellers
 * (`_TERMINAAL_VOOR_TELLERS`): geboekt/verwijderd/gesplitst/samengevoegd tellen niet als openstaand
 * werk. `geaccordeerd` (blok B 04-09) is de eindstand van een verplichting: het akkoord is gegeven,
 * er wordt niets geboekt — dus geen openstaand werk meer. */
export const TERMINALE_STATUSSEN = ['geboekt', 'verwijderd', 'gesplitst', 'samengevoegd', 'geaccordeerd']

/** Openstaand = niet terminaal. */
export function isOpenstaand(d: DocumentListItemDto): boolean {
  return !TERMINALE_STATUSSEN.includes(d.status)
}
