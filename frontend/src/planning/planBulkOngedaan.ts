import type { PlanningBulkItemDto, PlanningBulkResultaatDto } from './planningApi'
import { dagKort } from './dagEerst'

/* Toast + "Ongedaan maken" ná een bulk-actie (vulhandvat / ploeg-paneel; mockup ②): de server geeft de daadwerkelijk
 * aangemaakte set terug — de client onthoudt precies die set en stuurt 'm bij ongedaan maken als `verwijderen: true` mét
 * dezelfde correlatie-id terug. Cmd/Ctrl-Z doet hetzelfde zolang de toast staat (10 s). Puur; geen React. */

export const TOAST_DUUR_MS = 10_000

export interface OngedaanStand {
  correlatie_id: string
  aangemaakt: PlanningBulkItemDto[]
  tekst: string
  aantal_conflicten: number
  /** Eerste conflict-kaart (`project|datum`) voor "Toon conflict". */
  conflict_sleutel: string | null
  verloopt_op: number
  /** 21-09 (conflictenpaneel): ná een verwijdering via bron `conflict` = exact de verwijderde set, om terug te plaatsen. */
  herplaats?: PlanningBulkItemDto[]
  /** 28-09 (v4): ná "Kopiëren naar ‹weekdag› volgende week" — de doelweek voor de link "Naar week N". */
  naar_week?: { jaar: number; weeknummer: number }
}

/** "Gekopieerd naar di–vr · 16 persoon-dagen · 1 conflict" (vulhandvat) of "Ploeg opgeslagen · 3 toegevoegd · 1 verwijderd". */
export type BulkToastSoort = 'vulhandvat' | 'ploeg' | 'kopie'

export function bulkToastTekst(
  resultaat: PlanningBulkResultaatDto,
  opties: { soort: BulkToastSoort; doelDatums?: string[]; verwijderd?: number; naarWeek?: { jaar: number; weeknummer: number } },
): string {
  const gedaan = resultaat.resultaten.filter((r) => r.uitkomst !== 'overgeslagen').length
  const conflicten = resultaat.resultaten.filter((r) => r.uitkomst === 'conflict').length
  const afwezigOvergeslagen = resultaat.resultaten.filter((r) => r.uitkomst === 'overgeslagen' && r.conflict === 'afwezig').length
  const overgeslagen = resultaat.resultaten.filter((r) => r.uitkomst === 'overgeslagen').length - afwezigOvergeslagen
  const delen: string[] = []
  if (opties.soort === 'kopie') {
    // v4 (28-09): "Gekopieerd naar do 8-10 (week 41) · 3 persoon-dagen · 1 afwezig overgeslagen · 1 al gepland".
    const d = opties.doelDatums?.[0]
    delen.push(`Gekopieerd naar ${d ? dagKort(d) : 'volgende week'}${opties.naarWeek ? ` (week ${opties.naarWeek.weeknummer})` : ''}`)
    delen.push(`${gedaan} persoon-${gedaan === 1 ? 'dag' : 'dagen'}`)
    if (conflicten > 0) delen.push(`${conflicten} ${conflicten === 1 ? 'conflict' : 'conflicten'}`)
    if (afwezigOvergeslagen > 0) delen.push(`${afwezigOvergeslagen} afwezig overgeslagen`)
    if (overgeslagen > 0) delen.push(`${overgeslagen} al gepland`)
    return delen.join(' · ')
  }
  if (opties.soort === 'vulhandvat') {
    const d = opties.doelDatums ?? []
    const bereik = d.length === 0 ? '' : d.length === 1 ? dagKort(d[0]).split(' ')[0] : `${dagKort(d[0]).split(' ')[0]}–${dagKort(d[d.length - 1]).split(' ')[0]}`
    delen.push(bereik ? `Gekopieerd naar ${bereik}` : 'Gekopieerd')
    delen.push(`${gedaan} persoon-${gedaan === 1 ? 'dag' : 'dagen'}`)
  } else {
    delen.push('Ploeg opgeslagen')
    delen.push(`${gedaan} toegevoegd`)
    if (opties.verwijderd) delen.push(`${opties.verwijderd} verwijderd`)
  }
  if (conflicten > 0) delen.push(`${conflicten} ${conflicten === 1 ? 'conflict' : 'conflicten'}`)
  if (overgeslagen > 0) delen.push(`${overgeslagen} overgeslagen`)
  return delen.join(' · ')
}

export function maakOngedaanStand(
  resultaat: PlanningBulkResultaatDto,
  opties: { soort: BulkToastSoort; doelDatums?: string[]; verwijderd?: number; nu?: number; naarWeek?: { jaar: number; weeknummer: number } },
): OngedaanStand {
  const eersteConflict = resultaat.resultaten.find((r) => r.uitkomst === 'conflict')
  return {
    correlatie_id: resultaat.correlatie_id,
    aangemaakt: resultaat.aangemaakt,
    tekst: bulkToastTekst(resultaat, opties),
    aantal_conflicten: resultaat.resultaten.filter((r) => r.uitkomst === 'conflict').length,
    // Een conflict in week+1 ligt buiten de getoonde week: "Toon conflict" heeft daar geen kaart — de link "Naar week N" wél.
    conflict_sleutel: eersteConflict && opties.soort !== 'kopie' ? `${eersteConflict.project_id}|${eersteConflict.datum}` : null,
    verloopt_op: (opties.nu ?? Date.now()) + TOAST_DUUR_MS,
    ...(opties.naarWeek ? { naar_week: opties.naarWeek } : {}),
  }
}

/** Is de toetsaanslag Cmd/Ctrl-Z (zonder shift) buiten een invoerveld? */
export function isOngedaanToets(e: Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey' | 'shiftKey' | 'target'>): boolean {
  if (e.key.toLowerCase() !== 'z' || e.shiftKey || !(e.metaKey || e.ctrlKey)) return false
  const el = e.target as HTMLElement | null
  return !(el && typeof el.closest === 'function' && el.closest('input, textarea, select, [contenteditable="true"]'))
}
