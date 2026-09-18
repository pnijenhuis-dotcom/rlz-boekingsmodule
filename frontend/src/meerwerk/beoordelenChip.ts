/** Chip op de klantpagina/documentenlijst (bug 18-09: "14 meerwerk/urenstaten te beoordelen" landde op een lege
 * Meerwerk-pagina — de 14 waren ingediende weekstaten). Tekst = "N urenstaten · M meerwerk te beoordelen" uit precies de
 * twee tellers die de tabs van Beoordelen tonen (backend-guard: teller == tab); de link landt op de tab mét werk. */
import type { UrenStandDto } from './meerwerkApi'

export type BeoordelenTab = 'urenstaten' | 'meerwerk'

export interface BeoordelenChip {
  aantal: number
  tekst: string
  tab: BeoordelenTab
}

export function beoordelenChip(stand: Pick<UrenStandDto, 'urenstaten_wachten_op_keuring' | 'meerwerk_te_beoordelen'>): BeoordelenChip | null {
  const n = stand.urenstaten_wachten_op_keuring
  const m = stand.meerwerk_te_beoordelen
  if (n + m === 0) return null
  const delen = [n > 0 ? `${n} ${n === 1 ? 'urenstaat' : 'urenstaten'}` : null, m > 0 ? `${m} meerwerk` : null].filter(Boolean)
  return { aantal: n + m, tekst: `${delen.join(' · ')} te beoordelen`, tab: n > 0 ? 'urenstaten' : 'meerwerk' }
}

export function beoordelenUrl(administratieId: string, tab: BeoordelenTab): string {
  return `/meerwerk?administratie=${administratieId}&tab=${tab}`
}
