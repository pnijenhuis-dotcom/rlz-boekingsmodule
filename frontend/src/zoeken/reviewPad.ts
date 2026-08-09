/** Zelfde soort-switch als de werkvoorraad (WerkvoorraadScreen): een kassarapport opent het
 * omzetreview-scherm, een Vastly-verkoopfactuur het verkoopreview-scherm, al het andere het
 * inkoop-controlescherm. */
export function reviewPad(soort: string, administratieId: string, documentId: string): string {
  if (soort === 'kassarapport') return `/omzet/${administratieId}/${documentId}`
  if (soort === 'verkoopfactuur') return `/verkoop/${administratieId}/${documentId}`
  return `/documenten/${administratieId}/${documentId}`
}
