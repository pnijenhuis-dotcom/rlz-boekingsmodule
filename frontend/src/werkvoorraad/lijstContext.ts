import type { DocumentListItemDto } from '../api/types'
import { statusLabel } from './status'

/** Lijstcontext (werkstroom-run 27/28-08, punt 1): de documentenlijst-context — soort-tab,
 * status-filter en zoekterm van één administratie — reist als URL-query mee naar het
 * controlescherm en stuurt daar (a) de doorloop ná boeken/afwijzen/ter accordering (volgende
 * BINNEN het actieve filter), (b) de ‹ ›-navigatie mét "3 van 12" en (c) de terugweg naar de lijst
 * (zelfde tab + filter). Eén bron voor het filteren: `filterDocumenten` wordt door de lijst zélf
 * gebruikt, zodat "3 van 12" op het controlescherm exact de rijen zijn die in de lijst stonden.
 *
 * URL-vorm op beide plekken: `soort=<soort|alle>`, `status=<status|sentinel>`, `q=<zoekterm>` —
 * op de lijst `/?administratie=X&soort=…&status=…&q=…`, op het controlescherm
 * `/documenten/X/D?soort=…&status=…&q=…`. Ontbreekt alles → geen context (bestaand gedrag). */

export const STATUSFILTER_ALLE = 'alle'
/** Sentinel voor het autoboeken-filter — met prefix, zodat het nooit met een echte
 * DocumentStatus-waarde uit de backend kan botsen. */
export const STATUSFILTER_AUTOMATISCH = '__automatisch_geboekt'
/** Sentinel voor het duplicaatsignaal-filter (besluit 25-08, deel 2 punt 6) — zelfde prefix-regel. */
export const STATUSFILTER_DUPLICAAT = '__mogelijk_duplicaat'
/** Sentinel voor urenmatch-afwijkingen (kolom "Urenmatch" in het klantoverzicht, punt 1a). */
export const STATUSFILTER_URENMATCH = '__urenmatch_afwijking'
/** Expliciete "alle documenten"-tab (incl. geboekt/verwijderd). */
export const SOORT_ALLE = 'alle'

/** Sorteerbare kolomkoppen van de documentenlijst (punt 21, opruimrun 28-08). */
export const SORTEER_KOLOMMEN = ['leverancier', 'factuurdatum', 'bedrag', 'status', 'toegewezen'] as const
export type SorteerKolom = (typeof SORTEER_KOLOMMEN)[number]
export type SorteerRichting = 'asc' | 'desc'
export interface Sortering {
  kolom: SorteerKolom
  richting: SorteerRichting
}

export interface LijstContext {
  /** null = "Alle documenten"-tab (geen soort-scope). */
  soort: string | null
  /** Echte DocumentStatus, een `__`-sentinel of STATUSFILTER_ALLE. */
  status: string
  zoekterm: string
  /** Punt 21: kolomsortering — onderdeel van de context zodat ‹ › en de na-boeken-doorstroom
   * dezelfde volgorde volgen als de lijst. Ontbreekt/null = backend-volgorde (nieuwste eerst). */
  sortering?: Sortering | null
}

export const LEGE_CONTEXT: LijstContext = { soort: null, status: STATUSFILTER_ALLE, zoekterm: '', sortering: null }

/** Optionele helpers die de sortering nodig heeft maar niet in de (serialiseerbare) context
 * thuishoren: de naam-resolver voor de kolom "Toegewezen" (medewerker-id → naam). */
export interface FilterOpties {
  naamVoor?: (gebruikerId: string) => string
}

/** Sleutel "Toegewezen": rang-prefix (0 = boekfout ná akkoord, altijd vooraan bij oplopend; 1 = een
 * naam) + de getoonde naam — numerieke collatie vergelijkt de rang vóór de naam. */
function toegewezenSleutel(d: DocumentListItemDto, opties: FilterOpties): string {
  if (d.accordering_boek_fout) return '0|boeken ná akkoord mislukt'
  if (d.status === 'ter_accordering' && d.accordeur_aan_de_beurt) return `1|${d.accordeur_aan_de_beurt.naam}`
  if (d.toegewezen_aan) return `1|${opties.naamVoor ? opties.naamVoor(d.toegewezen_aan) : d.toegewezen_aan}`
  return ''
}

/** Sorteersleutel per kolom: string (localeCompare, lege waarde altijd achteraan) of number. */
function sorteerSleutel(d: DocumentListItemDto, kolom: SorteerKolom, opties: FilterOpties): string | number | null {
  switch (kolom) {
    case 'leverancier':
      return (d.leverancier ?? d.bestandsnaam ?? '').trim() || null
    case 'factuurdatum':
      return d.factuurdatum ?? null
    case 'bedrag': {
      if (d.totaalbedrag === null || d.totaalbedrag === undefined) return null
      const n = Number(d.totaalbedrag)
      return Number.isFinite(n) ? n : null
    }
    case 'status':
      return statusLabel(d.status)
    case 'toegewezen':
      return toegewezenSleutel(d, opties) || null
  }
}

/** Stabiele sortering (Array.prototype.sort is stabiel): gelijke sleutels houden de lijstvolgorde;
 * ontbrekende waarden staan altijd achteraan, ongeacht de richting. */
export function sorteerDocumenten(
  items: DocumentListItemDto[],
  sortering: Sortering | null | undefined,
  opties: FilterOpties = {},
): DocumentListItemDto[] {
  if (!sortering) return items
  const teken = sortering.richting === 'desc' ? -1 : 1
  const sleutels = new Map(items.map((d) => [d.id, sorteerSleutel(d, sortering.kolom, opties)] as const))
  return [...items].sort((a, b) => {
    const ka = sleutels.get(a.id) ?? null
    const kb = sleutels.get(b.id) ?? null
    if (ka === null && kb === null) return 0
    if (ka === null) return 1
    if (kb === null) return -1
    if (typeof ka === 'number' && typeof kb === 'number') return teken * (ka - kb)
    return teken * String(ka).localeCompare(String(kb), 'nl', { sensitivity: 'base', numeric: true })
  })
}

/** Volgende sorteerstand bij een klik op een kolomkop: oplopend → aflopend → uit (punt 21). */
export function volgendeSortering(huidig: Sortering | null | undefined, kolom: SorteerKolom): Sortering | null {
  if (!huidig || huidig.kolom !== kolom) return { kolom, richting: 'asc' }
  if (huidig.richting === 'asc') return { kolom, richting: 'desc' }
  return null
}

export function sorteringUitParam(waarde: string | null): Sortering | null {
  if (!waarde) return null
  const [kolom, richting] = waarde.split(':')
  if (!(SORTEER_KOLOMMEN as readonly string[]).includes(kolom)) return null
  return { kolom: kolom as SorteerKolom, richting: richting === 'desc' ? 'desc' : 'asc' }
}

export function sorteringNaarParam(sortering: Sortering | null | undefined): string | null {
  return sortering ? `${sortering.kolom}:${sortering.richting}` : null
}

/** Eén duplicaat-begrip voor filter en teller: het gecachete RLZ-signaal óf de bestandsinhoud-
 * match bij upload (`mogelijk_duplicaat_van`). */
export function isMogelijkDuplicaat(d: DocumentListItemDto): boolean {
  return d.duplicaatsignaal?.uitkomst === 'mogelijk_duplicaat' || d.mogelijk_duplicaat_van !== null
}

export function isUrenmatchAfwijking(d: DocumentListItemDto): boolean {
  return d.factuurmatch?.uitkomst === 'afwijking'
}

/** Voldoet één document aan het status-filter (echte status óf sentinel)? */
export function voldoetAanStatusFilter(d: DocumentListItemDto, status: string): boolean {
  if (status === STATUSFILTER_ALLE) return true
  if (status === STATUSFILTER_AUTOMATISCH) return d.automatisch_geboekt
  if (status === STATUSFILTER_DUPLICAAT) return isMogelijkDuplicaat(d)
  if (status === STATUSFILTER_URENMATCH) return isUrenmatchAfwijking(d)
  return d.status === status
}

/** Zoeken blijft op leverancier, bestandsnaam, bedrag én statuslabel werken (punt 3a: de
 * bestandsnaam is een metaregel geworden, maar blijft doorzoekbaar). */
export function voldoetAanZoekterm(d: DocumentListItemDto, zoekterm: string): boolean {
  const term = zoekterm.trim().toLowerCase()
  if (!term) return true
  return [d.bestandsnaam, d.leverancier ?? '', d.totaalbedrag ?? '', statusLabel(d.status)]
    .join(' ')
    .toLowerCase()
    .includes(term)
}

/** De rijen van de lijst in lijstvolgorde (= backend-volgorde, nieuwste eerst, óf de gekozen
 * kolomsortering — punt 21): soort-scope → status-filter → zoekterm → sortering. Puur; gedeeld door
 * DocumentenDeelscherm en het controlescherm. */
export function filterDocumenten(
  items: DocumentListItemDto[],
  context: LijstContext,
  opties: FilterOpties = {},
): DocumentListItemDto[] {
  const gefilterd = items.filter(
    (d) =>
      (context.soort === null || d.soort === context.soort) &&
      voldoetAanStatusFilter(d, context.status) &&
      voldoetAanZoekterm(d, context.zoekterm),
  )
  return sorteerDocumenten(gefilterd, context.sortering, opties)
}

/** Leest de context uit URL-params (lijst én controlescherm). `soort` ontbreekt → null (geen
 * scope; de lijst kiest dan zelf zijn eerste tab, maar het controlescherm weet dat niet — daarom
 * stuurt de lijst altijd de effectieve tab mee, zie `lijstContextNaarParams`). */
export function lijstContextUitParams(params: URLSearchParams): LijstContext | null {
  const soort = params.get('soort')
  const status = params.get('status')
  const q = params.get('q')
  const sort = params.get('sort')
  if (soort === null && status === null && q === null && sort === null) return null
  return {
    soort: soort === null || soort === SOORT_ALLE ? null : soort,
    status: status ?? STATUSFILTER_ALLE,
    zoekterm: q ?? '',
    sortering: sorteringUitParam(sort),
  }
}

/** Serialiseert de context als query-string (zonder '?'); lege context = ''. De soort gaat
 * altijd mee (ook 'alle') zodat het controlescherm dezelfde scope hanteert als de lijst. */
export function lijstContextNaarParams(context: LijstContext | null): string {
  if (!context) return ''
  const p = new URLSearchParams()
  p.set('soort', context.soort ?? SOORT_ALLE)
  if (context.status !== STATUSFILTER_ALLE) p.set('status', context.status)
  if (context.zoekterm.trim()) p.set('q', context.zoekterm.trim())
  const sort = sorteringNaarParam(context.sortering)
  if (sort) p.set('sort', sort)
  return p.toString()
}

/** Terugweg naar de documentenlijst mét dezelfde tab/filter/zoekterm. */
export function lijstRoute(administratieId: string, context: LijstContext | null): string {
  const q = lijstContextNaarParams(context)
  return `/?administratie=${administratieId}${q ? `&${q}` : ''}`
}

/** Positie van een document binnen de gefilterde lijst — voedt ‹ › + "3 van 12" (punt 1c).
 * Staat het document niet (meer) in de gefilterde lijst (bv. ná boeken is de status veranderd),
 * dan is `index` -1 en tonen we geen positie. */
export interface LijstPositie {
  index: number
  totaal: number
  vorige: DocumentListItemDto | null
  volgende: DocumentListItemDto | null
}

export function lijstPositie(
  items: DocumentListItemDto[],
  context: LijstContext,
  huidigId: string,
  opties: FilterOpties = {},
): LijstPositie {
  const rijen = filterDocumenten(items, context, opties)
  const index = rijen.findIndex((d) => d.id === huidigId)
  return {
    index,
    totaal: rijen.length,
    vorige: index > 0 ? rijen[index - 1] : null,
    volgende: index >= 0 && index < rijen.length - 1 ? rijen[index + 1] : null,
  }
}

/** Tab-keuze bij een voorgefilterde status (punt 1a — kolom-teller "Afgewezen" op een verkoopfactuur
 * terwijl de eerste tab Inkoopfacturen is): kies de eerste tab (in `tabs`-volgorde) waarin het
 * status-filter ten minste één rij oplevert; niets → null ("Alle documenten"). */
export function kiesTabVoorStatus(items: DocumentListItemDto[], tabs: string[], status: string): string | null {
  if (status === STATUSFILTER_ALLE) return tabs[0] ?? null
  for (const tab of tabs) {
    if (items.some((d) => d.soort === tab && voldoetAanStatusFilter(d, status))) return tab
  }
  return null
}
