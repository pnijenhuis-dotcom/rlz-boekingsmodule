/* Openingsstand van de ingebouwde PDF-viewer (fix C2, besluit Peter 04-09).
 *
 * De bijlage-weergave op het controlescherm (en op de review-/verzamelbakschermen) is géén eigen
 * viewer maar de PDF-viewer van de browser in een `<object>`. Die opende standaard mét de
 * miniaturen-zijbalk, die op een halve-breedte-paneel de helft van het factuurbeeld opvrat. De
 * open-parameters in het URL-fragment zetten de openingsstand: `pagemode=none` (pdf.js/Edge) en
 * `navpanes=0` (Chrome/pdfium) laten de zijbalk dicht, `view=FitH` schaalt op paginabreedte.
 *
 * Bewust GEEN `toolbar=0`: de gebruiker moet de zijbalk via ☰ in de toolbar zelf kunnen openen —
 * dit is een openingsstand, geen beperking. Onbekende sleutels worden door een viewer genegeerd,
 * dus dit is veilig over browsers heen.
 *
 * `metViewerOpties` is idempotent en laat een al aanwezig fragment (en al gezette sleutels) staan
 * — twee keer toepassen levert nooit een dubbele `#` of een dubbele sleutel op. */

const VIEWER_OPTIES: ReadonlyArray<readonly [string, string]> = [
  ['pagemode', 'none'],
  ['navpanes', '0'],
  ['view', 'FitH'],
]

export function metViewerOpties(url: string): string {
  if (!url) return url
  const hashIndex = url.indexOf('#')
  const basis = hashIndex === -1 ? url : url.slice(0, hashIndex)
  const bestaandeDelen = hashIndex === -1 ? [] : url.slice(hashIndex + 1).split('&').filter(Boolean)
  const bestaandeSleutels = new Set(bestaandeDelen.map((deel) => deel.split('=')[0]))
  const nieuw = VIEWER_OPTIES.filter(([sleutel]) => !bestaandeSleutels.has(sleutel)).map(
    ([sleutel, waarde]) => `${sleutel}=${waarde}`,
  )
  if (nieuw.length === 0) return url
  return `${basis}#${[...bestaandeDelen, ...nieuw].join('&')}`
}
