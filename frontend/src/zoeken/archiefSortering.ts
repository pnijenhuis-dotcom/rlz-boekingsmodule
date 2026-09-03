/** Sorteerbare kolomkoppen van het kantoorbrede archief (B4 design-ronde 03-09) — dezelfde
 * conventie als de documentenlijst (opruimrun 28-08 punt 21): klik = oplopend → aflopend → uit,
 * `sort=<kolom>:<richting>` in de URL. Puur; de server sorteert (backend
 * `ARCHIEF_SORTEER_KOLOMMEN`), dit bestand vertaalt alleen klik ↔ URL-parameter. */
export const ARCHIEF_SORTEER_KOLOMMEN = ['leverancier', 'factuurdatum', 'bedrag', 'boekstuk', 'administratie', 'geboekt_op'] as const
export type ArchiefSorteerKolom = (typeof ARCHIEF_SORTEER_KOLOMMEN)[number]
export type ArchiefSorteerRichting = 'asc' | 'desc'
export interface ArchiefSortering {
  kolom: ArchiefSorteerKolom
  richting: ArchiefSorteerRichting
}

function isKolom(waarde: string): waarde is ArchiefSorteerKolom {
  return (ARCHIEF_SORTEER_KOLOMMEN as readonly string[]).includes(waarde)
}

/** Volgende stand bij een klik op een kolomkop: oplopend → aflopend → uit (= server-default:
 * boekmoment, nieuwste eerst). */
export function volgendeArchiefSortering(
  huidig: ArchiefSortering | null | undefined,
  kolom: ArchiefSorteerKolom,
): ArchiefSortering | null {
  if (!huidig || huidig.kolom !== kolom) return { kolom, richting: 'asc' }
  if (huidig.richting === 'asc') return { kolom, richting: 'desc' }
  return null
}

export function archiefSorteringUitParam(waarde: string | null): ArchiefSortering | null {
  if (!waarde) return null
  const [kolom, richting] = waarde.split(':')
  if (!kolom || !isKolom(kolom)) return null
  return { kolom, richting: richting === 'desc' ? 'desc' : 'asc' }
}

export function archiefSorteringNaarParam(sortering: ArchiefSortering | null | undefined): string | null {
  return sortering ? `${sortering.kolom}:${sortering.richting}` : null
}
