import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'

export interface ComboboxOptie {
  id: string
  label: string
}

interface Props {
  label: string
  opties: ComboboxOptie[]
  waarde: string | null
  onWijzig: (id: string | null) => void
  placeholder?: string
  vereist?: boolean
  fout?: boolean
}

// Sync-caches kunnen honderden tot duizenden opties bevatten (bv. Universal: 145 projecten) —
// alleen het zichtbare venster + een kleine buffer wordt daadwerkelijk gerenderd (BOUWPLAN.md,
// UI-eisen: gevirtualiseerde lijsten voor elke lijstweergave uit een sync-cache).
const RIJHOOGTE = 32
const ZICHTBARE_RIJEN = 8
const BUFFER = 4

function useDebounced<T>(waarde: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(waarde)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(waarde), delayMs)
    return () => clearTimeout(timer)
  }, [waarde, delayMs])
  return debounced
}

/** Zoekbare combobox met toetsenbordnavigatie en gevirtualiseerde opties-lijst (BOUWPLAN.md,
 * UI-eisen voor elk GB-/project-/entiteitveld) — debounced lokaal filteren, geen request per
 * toetsaanslag (de sync-cache is al lokaal). */
export function SearchableCombobox({ label, opties, waarde, onWijzig, placeholder, vereist, fout }: Props) {
  const reactId = useId()
  const inputId = `${reactId}-input`
  const listboxId = `${reactId}-listbox`

  const [open, setOpen] = useState(false)
  const [zoekterm, setZoekterm] = useState('')
  const [actieveIndex, setActieveIndex] = useState(0)
  const [scrollTop, setScrollTop] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const debouncedZoekterm = useDebounced(zoekterm, 150)

  const geselecteerd = useMemo(() => opties.find((o) => o.id === waarde) ?? null, [opties, waarde])

  const gefilterd = useMemo(() => {
    const term = debouncedZoekterm.trim().toLowerCase()
    if (!term) return opties
    return opties.filter((o) => o.label.toLowerCase().includes(term))
  }, [opties, debouncedZoekterm])

  useEffect(() => {
    setActieveIndex(0)
    setScrollTop(0)
  }, [debouncedZoekterm])

  useEffect(() => {
    if (!open) return
    function opKlikBuiten(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', opKlikBuiten)
    return () => document.removeEventListener('mousedown', opKlikBuiten)
  }, [open])

  const kiesOptie = useCallback(
    (optie: ComboboxOptie) => {
      onWijzig(optie.id)
      setZoekterm('')
      setOpen(false)
    },
    [onWijzig],
  )

  const opToetsenbord = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) {
        setOpen(true)
        return
      }
      setActieveIndex((i) => Math.min(i + 1, gefilterd.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActieveIndex((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (open && gefilterd[actieveIndex]) kiesOptie(gefilterd[actieveIndex])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const eersteIndex = Math.max(0, Math.floor(scrollTop / RIJHOOGTE) - BUFFER)
  const laatsteIndex = Math.min(gefilterd.length, eersteIndex + ZICHTBARE_RIJEN + BUFFER * 2)
  const zichtbareOpties = gefilterd.slice(eersteIndex, laatsteIndex)

  useEffect(() => {
    if (!open || !listRef.current) return
    const rijTop = actieveIndex * RIJHOOGTE
    const el = listRef.current
    if (rijTop < el.scrollTop) el.scrollTop = rijTop
    else if (rijTop + RIJHOOGTE > el.scrollTop + ZICHTBARE_RIJEN * RIJHOOGTE) {
      el.scrollTop = rijTop + RIJHOOGTE - ZICHTBARE_RIJEN * RIJHOOGTE
    }
  }, [actieveIndex, open])

  const actieveOptieId =
    open && gefilterd[actieveIndex] ? `${listboxId}-${gefilterd[actieveIndex].id}` : undefined

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <label htmlFor={inputId}>
        {label}
        {vereist && ' *'}
      </label>
      <input
        id={inputId}
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={actieveOptieId}
        aria-required={vereist}
        className={fout ? 'warnfield' : undefined}
        autoComplete="off"
        placeholder={placeholder ?? 'Typen om te zoeken…'}
        value={open ? zoekterm : geselecteerd?.label ?? ''}
        onFocus={() => {
          setOpen(true)
          setZoekterm('')
        }}
        onChange={(e) => {
          setZoekterm(e.target.value)
          setOpen(true)
        }}
        onKeyDown={opToetsenbord}
      />
      {open && (
        <div
          ref={listRef}
          role="listbox"
          id={listboxId}
          aria-label={label}
          onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
          style={{
            position: 'absolute',
            zIndex: 20,
            top: '100%',
            left: 0,
            right: 0,
            maxHeight: ZICHTBARE_RIJEN * RIJHOOGTE,
            overflowY: 'auto',
            background: 'var(--panel)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ height: gefilterd.length * RIJHOOGTE, position: 'relative' }}>
            {zichtbareOpties.map((optie, i) => {
              const echteIndex = eersteIndex + i
              return (
                <div
                  key={optie.id}
                  id={`${listboxId}-${optie.id}`}
                  role="option"
                  aria-selected={echteIndex === actieveIndex}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    kiesOptie(optie)
                  }}
                  onMouseEnter={() => setActieveIndex(echteIndex)}
                  style={{
                    position: 'absolute',
                    top: echteIndex * RIJHOOGTE,
                    left: 0,
                    right: 0,
                    height: RIJHOOGTE,
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0 10px',
                    fontSize: 13,
                    cursor: 'pointer',
                    background: echteIndex === actieveIndex ? 'var(--blue-bg)' : 'transparent',
                  }}
                >
                  {optie.label}
                </div>
              )
            })}
            {gefilterd.length === 0 && (
              <div style={{ padding: '8px 10px', fontSize: 12.5, color: 'var(--muted)' }}>Geen resultaten</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
