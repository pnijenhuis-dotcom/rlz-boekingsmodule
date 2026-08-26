/** Gedeelde weergavehelpers voor het zoek- en archiefscherm — zelfde notatie als de
 * werkvoorraad (nl-NL, EUR, em-dash voor ontbrekende waarden). De bedragcel-klasse (negatief =
 * --danger, designpass v2) is één bron: werkvoorraad/format.ts. */
export { amountKlasse } from '../werkvoorraad/format'

export function formatBedrag(bedrag: string | null): string {
  if (bedrag === null) return '—'
  const numeriek = Number(bedrag)
  if (Number.isNaN(numeriek)) return '—'
  return numeriek.toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

export function formatDatum(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

export function formatDatumKort(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('nl-NL', { dateStyle: 'medium' })
}
