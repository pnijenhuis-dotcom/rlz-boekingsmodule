import { useEffect, useRef } from 'react'

/** Sneltoetsen controlescherm (werkstroom-run 27/28-08, punt 5 — power-user-laag):
 *   B = boeken (of "Boeken + doorbelasten"/"Ter accordering" — wat de actieve knop ook is),
 *   A = afwijzen (opent het reden-veld), ← / → = vorige/volgende in de gefilterde lijst (punt 1c),
 *   Esc = terug naar de lijst, ? = sneltoets-overzicht; op de documentenlijst: / = focus zoekveld.
 * Alleen actief zonder focus in een invoerveld (input/textarea/select/contenteditable/combobox) en
 * niet zolang er een dialoog open staat (die heeft zijn eigen Esc/Enter). Modifier-toetsen
 * (Cmd/Ctrl/Alt) laten de browser zijn werk doen. */

export type SneltoetsActie = 'boeken' | 'afwijzen' | 'vorige' | 'volgende' | 'terug' | 'overzicht' | 'zoeken'

export interface SneltoetsBinding {
  actie: SneltoetsActie
  toets: string
  /** Weergavelabel in tooltip/overzicht. */
  label: string
}

export const SNELTOETSEN_CONTROLESCHERM: SneltoetsBinding[] = [
  { actie: 'boeken', toets: 'b', label: 'B' },
  { actie: 'afwijzen', toets: 'a', label: 'A' },
  { actie: 'vorige', toets: 'ArrowLeft', label: '←' },
  { actie: 'volgende', toets: 'ArrowRight', label: '→' },
  { actie: 'terug', toets: 'Escape', label: 'Esc' },
  { actie: 'overzicht', toets: '?', label: '?' },
]

export const SNELTOETSEN_LIJST: SneltoetsBinding[] = [{ actie: 'zoeken', toets: '/', label: '/' }]

export const SNELTOETS_OMSCHRIJVING: Record<SneltoetsActie, string> = {
  boeken: 'Boeken (of Boeken + doorbelasten / Ter accordering — de actieve knop)',
  afwijzen: 'Afwijzen… (opent het reden-veld)',
  vorige: 'Vorige document in de gefilterde lijst',
  volgende: 'Volgende document in de gefilterde lijst',
  terug: 'Terug naar de documentenlijst (zelfde tab en filter)',
  overzicht: 'Dit overzicht tonen',
  zoeken: 'Zoekveld in de documentenlijst',
}

/** Is de toetsaanslag bestemd voor een invoerveld of een open dialoog? Dan géén sneltoets. */
export function toetsInInvoer(target: EventTarget | null, doc: Document = document): boolean {
  if (doc.querySelector('[role="dialog"], .modal-bg, [role="alertdialog"]')) return true
  const el = target as HTMLElement | null
  if (!el || typeof el.closest !== 'function') return false
  if (el.isContentEditable) return true
  return el.closest('input, textarea, select, [contenteditable="true"], [role="combobox"], [role="listbox"]') !== null
}

/** Vertaalt een KeyboardEvent naar een actie uit `bindings` (null = geen). Shift+/ levert '?' —
 * `event.key` is dan al '?', dus geen aparte shift-logica. */
export function bepaalSneltoets(event: KeyboardEvent, bindings: SneltoetsBinding[]): SneltoetsActie | null {
  if (event.metaKey || event.ctrlKey || event.altKey) return null
  if (event.isComposing || event.repeat) return null
  const toets = event.key.length === 1 ? event.key.toLowerCase() : event.key
  const binding = bindings.find((b) => b.toets === toets)
  return binding?.actie ?? null
}

/** Registreert een globale keydown-listener zolang `actief` waar is. `handlers` mag per render
 * wisselen (ref), het effect hangt alleen aan `actief`. Een handler die `false` teruggeeft laat
 * de toets door (bv. Esc zonder open modal maar mét een onopgeslagen-bevestiging elders). */
export function useSneltoetsen(
  bindings: SneltoetsBinding[],
  handlers: Partial<Record<SneltoetsActie, () => void | boolean>>,
  actief = true,
): void {
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers
  const bindingsRef = useRef(bindings)
  bindingsRef.current = bindings

  useEffect(() => {
    if (!actief) return
    const luister = (event: KeyboardEvent) => {
      if (toetsInInvoer(event.target)) return
      const actie = bepaalSneltoets(event, bindingsRef.current)
      if (!actie) return
      const handler = handlersRef.current[actie]
      if (!handler) return
      const uitkomst = handler()
      if (uitkomst !== false) event.preventDefault()
    }
    window.addEventListener('keydown', luister)
    return () => window.removeEventListener('keydown', luister)
  }, [actief])
}
