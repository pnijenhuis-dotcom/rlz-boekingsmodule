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

/** Documentsoorten mét een eigen reviewscherm — de rest opent het inkoop-controlescherm. */
const REVIEW_ROUTE_PER_SOORT: Record<string, string> = {
  kassarapport: 'omzet',
  verkoopfactuur: 'verkoop',
  waarborg: 'waarborg',
  verplichting: 'verplichting',
}

export interface DocumentLinkDoel {
  id: string
  /** Documentsoort; ontbreekt hij (oudere DTO's zonder soort), dan valt de link terug op het inkoop-controlescherm. */
  soort?: string | null
  status?: string | null
}

/** DE ENE bron voor "open dit document" (BUG 23-09: de vraag-thread linkte hard naar `/documenten/…` en opende een
 * kassarapport in een leeg inkoopformulier). Route volgt de SOORT: kassarapport → omzetreview, verkoopfactuur →
 * verkoopreview, waarborg → waarborg, verplichting → verplichting-review, al het andere → inkoop-controlescherm.
 * Een open vraag (status `vraag_open`, niet verwijderd) opent de vráág op de klantpagina (mockup). Mét lijstcontext
 * reist tab/filter/zoekterm als query mee naar het inkoop-controlescherm; de andere reviewschermen kennen die context
 * (nog) niet en krijgen 'm bewust niet. Server-spiegel: `app/documenten/deeplink.py::document_pad`. Guard:
 * `werkvoorraad/documentPad.guard.test.ts` — nergens anders een letterlijke `/documenten/${…}`-link. */
export function documentPad(administratieId: string, doel: DocumentLinkDoel, context: LijstContext | null = null): string {
  const isVerwijderd = doel.status === 'verwijderd'
  if (doel.status === 'vraag_open' && !isVerwijderd) {
    return `/?administratie=${administratieId}&sectie=vragen&document=${doel.id}`
  }
  const review = doel.soort ? REVIEW_ROUTE_PER_SOORT[doel.soort] : undefined
  if (review) return `/${review}/${administratieId}/${doel.id}`
  const q = lijstContextNaarParams(context)
  return `/documenten/${administratieId}/${doel.id}${q ? `?${q}` : ''}`
}

/** Opent deze soort een ander scherm dan het inkoop-controlescherm? (redirect in DocumentDetailScreen) */
export function heeftEigenReviewscherm(soort: string | null | undefined): boolean {
  return Boolean(soort && REVIEW_ROUTE_PER_SOORT[soort])
}

/** Route per documentsoort/-status voor een documentregel uit de lijst — dunne laag op `documentPad`. */
export function documentRoute(administratieId: string, d: DocumentListItemDto, context: LijstContext | null = null): string {
  return documentPad(administratieId, { id: d.id, soort: d.soort, status: d.status }, context)
}

/** Terminale statussen — zelfde definitie als de backend-overzichtstellers
 * (`_TERMINAAL_VOOR_TELLERS`): geboekt/verwijderd/gesplitst/samengevoegd/afgevoerd_duplicaat tellen niet als
 * openstaand werk. `geaccordeerd` (blok B 04-09) is de eindstand van een verplichting: het akkoord is gegeven,
 * er wordt niets geboekt — dus geen openstaand werk meer. `afgevoerd_duplicaat` (blok 3 08-09) ontbrak hier
 * t.o.v. de backend-lijst — rechtgezet in de aanvulling van 08-09. */
export const TERMINALE_STATUSSEN = ['geboekt', 'verwijderd', 'gesplitst', 'samengevoegd', 'geaccordeerd', 'afgevoerd_duplicaat']

/** Openstaand = niet terminaal. */
export function isOpenstaand(d: DocumentListItemDto): boolean {
  return !TERMINALE_STATUSSEN.includes(d.status)
}
