import { useState, type DragEvent } from 'react'

/* Gedeelde drag-mechaniek voor dag-agenda's (Transport v2 31-08 + Planning v3 18-09 — één implementatie, geen tweede):
 * payload = `<soort>:<id>` in `text/plain`, dropdoel = de dagkolom (dragOver-markering, leave-detectie, drop → callback
 * met soort + id). De eigen state van de agenda (wat er gesleept wordt) blijft bij de agenda zelf. */

export function maakSleepPayload(soort: string, id: string): string {
  return `${soort}:${id}`
}

export function leesSleepPayload(e: DragEvent): { soort: string; id: string } | null {
  const raw = e.dataTransfer.getData('text/plain')
  const i = raw.indexOf(':')
  if (i <= 0) return raw ? { soort: '', id: raw } : null
  return { soort: raw.slice(0, i), id: raw.slice(i + 1) }
}

export function useDagDrop<T extends HTMLElement = HTMLTableCellElement>(
  onDrop: (datum: string, payload: { soort: string; id: string } | null, e: DragEvent<T>) => void,
  dropEffect: 'copy' | 'move' | ((e: DragEvent<T>) => 'copy' | 'move') = 'move',
) {
  const [dragOverDag, setDragOverDag] = useState<string | null>(null)
  function dagDropProps(datum: string) {
    return {
      onDragEnter: (e: DragEvent<T>) => e.preventDefault(),
      onDragOver: (e: DragEvent<T>) => {
        e.preventDefault()
        e.dataTransfer.dropEffect = typeof dropEffect === 'function' ? dropEffect(e) : dropEffect
        setDragOverDag(datum)
      },
      onDragLeave: (e: DragEvent<T>) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOverDag((h) => (h === datum ? null : h))
      },
      onDrop: (e: DragEvent<T>) => {
        e.preventDefault()
        setDragOverDag(null)
        onDrop(datum, leesSleepPayload(e), e)
      },
    }
  }
  return { dragOverDag, setDragOverDag, dagDropProps }
}
