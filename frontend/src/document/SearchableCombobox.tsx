import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'

export interface ComboboxOptie {
  id: string
  label: string
  /** Korte, opvallende sleutel vóór de omschrijving (bv. de grootboekcode of het btw-percentage)
   * — design-pass taak 2: "optie-rijen met code vet + omschrijving". Optioneel: niet elke
   * entiteit (crediteuren/projecten) heeft zoiets. */
  code?: string
  /** Btw-percentage als fractie (0.21 voor 21%) — alleen gezet door useTaxrateOpties, puur
   * doorgeefluik voor BoekvoorstelPanel's automatische btw-afleiding (design-pass taak 3).
   * SearchableCombobox zelf doet niets met dit veld. */
  percentage?: number
}

function weergaveTekst(optie: ComboboxOptie): string {
  return optie.code ? `${optie.code} · ${optie.label}` : optie.label
}

interface Props {
  label: string
  opties: ComboboxOptie[]
  waarde: string | null
  onWijzig: (id: string | null) => void
  placeholder?: string
  vereist?: boolean
  fout?: boolean
  /** Verbergt het visuele <label>-element (bv. in een tabelkolom waar de kolomkop al het label
   * is — design-pass taak 2: "dubbele labels weg"). De tekst blijft wel als aria-label op de
   * input staan, voor screenreaders die geen kolomkop-context hebben. */
  toonLabel?: boolean
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

// Ademruimte tussen lijst en viewportrand; de lijst klapt naar boven open ("flip") zodra er
// onder het veld minder ruimte is dan de gewenste hoogte én boven méér — en wordt in beide
// richtingen op de beschikbare ruimte afgekapt met interne scroll, zodat hij altijd volledig
// binnen de viewport valt (bugfix 2026-07-11: onderin het scherm vielen opties buiten beeld).
const VIEWPORT_MARGE = 8
const GEWENSTE_HOOGTE = ZICHTBARE_RIJEN * RIJHOOGTE + 8

interface Positie {
  /** Gezet bij openen naar beneden (afstand tot viewport-bovenkant). */
  top?: number
  /** Gezet bij openen naar boven (afstand tot viewport-ónderkant, CSS `bottom` op fixed). */
  bottom?: number
  left: number
  width: number
  maxWidth: number
  maxHeight: number
}

/** Zoekbare combobox met toetsenbordnavigatie en gevirtualiseerde opties-lijst (BOUWPLAN.md,
 * UI-eisen voor elk GB-/project-/entiteitveld) — debounced lokaal filteren, geen request per
 * toetsaanslag (de sync-cache is al lokaal). De opties-lijst rendert via een React-portal naar
 * `document.body` met een zelf-berekende `position: fixed`-plek: zo blijft hij altijd zichtbaar,
 * ook binnen containers met `overflow: hidden` (bv. de `<table>`-stijl in components.css) die 'm
 * anders zouden afknippen. */
export function SearchableCombobox({
  label,
  opties,
  waarde,
  onWijzig,
  placeholder,
  vereist,
  fout,
  toonLabel = true,
}: Props) {
  const reactId = useId()
  const inputId = `${reactId}-input`
  const listboxId = `${reactId}-listbox`

  const [open, setOpen] = useState(false)
  const [zoekterm, setZoekterm] = useState('')
  const [actieveIndex, setActieveIndex] = useState(0)
  const [scrollTop, setScrollTop] = useState(0)
  const [positie, setPositie] = useState<Positie | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const debouncedZoekterm = useDebounced(zoekterm, 150)

  const geselecteerd = useMemo(() => opties.find((o) => o.id === waarde) ?? null, [opties, waarde])

  const gefilterd = useMemo(() => {
    const term = debouncedZoekterm.trim().toLowerCase()
    if (!term) return opties
    return opties.filter(
      (o) => o.label.toLowerCase().includes(term) || (o.code?.toLowerCase().includes(term) ?? false),
    )
  }, [opties, debouncedZoekterm])

  useEffect(() => {
    setActieveIndex(0)
    setScrollTop(0)
  }, [debouncedZoekterm])

  const bijwerkenPositie = useCallback(() => {
    const el = inputRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    // Scrollt het veld zelf (vrijwel) uit beeld, dan sluit de lijst — een fixed lijst die aan
    // een onzichtbaar veld "vastzit" zweeft anders los door het scherm (bugfix 2026-07-11).
    if (rect.bottom < 0 || rect.top > window.innerHeight) {
      setOpen(false)
      return
    }
    const ruimteOnder = window.innerHeight - rect.bottom - VIEWPORT_MARGE
    const ruimteBoven = rect.top - VIEWPORT_MARGE
    const naarBoven = ruimteOnder < GEWENSTE_HOOGTE && ruimteBoven > ruimteOnder
    // Breedte >= het invoerveld (design-pass taak 2) — de lijst mag breder worden om "code +
    // omschrijving" leesbaar te tonen, tot de rand van het venster (met een kleine marge).
    setPositie({
      top: naarBoven ? undefined : rect.bottom,
      bottom: naarBoven ? window.innerHeight - rect.top : undefined,
      left: rect.left,
      width: rect.width,
      maxWidth: Math.max(rect.width, window.innerWidth - rect.left - 12),
      maxHeight: Math.max(RIJHOOGTE + 8, Math.min(GEWENSTE_HOOGTE, naarBoven ? ruimteBoven : ruimteOnder)),
    })
  }, [])

  useEffect(() => {
    if (!open) return
    bijwerkenPositie()
    // capture:true zodat scroll op ELKE voorouder-container (niet alleen window) de positie
    // bijwerkt — anders "drijft" de dropdown weg van het veld bij scrollen binnen een tabel-pane.
    window.addEventListener('scroll', bijwerkenPositie, true)
    window.addEventListener('resize', bijwerkenPositie)
    return () => {
      window.removeEventListener('scroll', bijwerkenPositie, true)
      window.removeEventListener('resize', bijwerkenPositie)
    }
  }, [open, bijwerkenPositie])

  useEffect(() => {
    if (!open) return
    function opKlikBuiten(e: MouseEvent) {
      const doel = e.target as Node
      const inVeld = containerRef.current?.contains(doel)
      const inLijst = listRef.current?.contains(doel)
      if (!inVeld && !inLijst) setOpen(false)
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

  // Het render-venster volgt de wérkelijke lijsthoogte — die kan door de viewport-clamp kleiner
  // zijn dan de acht standaardrijen, maar het venster mag nooit kleiner worden dan wat zichtbaar is.
  const zichtbareRijen = Math.min(ZICHTBARE_RIJEN, Math.ceil((positie?.maxHeight ?? GEWENSTE_HOOGTE) / RIJHOOGTE))
  const eersteIndex = Math.max(0, Math.floor(scrollTop / RIJHOOGTE) - BUFFER)
  const laatsteIndex = Math.min(gefilterd.length, eersteIndex + ZICHTBARE_RIJEN + BUFFER * 2)
  const zichtbareOpties = gefilterd.slice(eersteIndex, laatsteIndex)

  useEffect(() => {
    if (!open || !listRef.current) return
    const rijTop = actieveIndex * RIJHOOGTE
    const el = listRef.current
    // clientHeight i.p.v. de vaste acht rijen: bij een viewport-geclampte lijst is het zichtbare
    // venster kleiner en moet de actieve rij binnen dát venster blijven.
    const vensterHoogte = el.clientHeight || zichtbareRijen * RIJHOOGTE
    if (rijTop < el.scrollTop) el.scrollTop = rijTop
    else if (rijTop + RIJHOOGTE > el.scrollTop + vensterHoogte) {
      el.scrollTop = rijTop + RIJHOOGTE - vensterHoogte
    }
  }, [actieveIndex, open, zichtbareRijen])

  const actieveOptieId =
    open && gefilterd[actieveIndex] ? `${listboxId}-${gefilterd[actieveIndex].id}` : undefined

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      {toonLabel && (
        <label htmlFor={inputId}>
          {label}
          {vereist && ' *'}
        </label>
      )}
      <input
        ref={inputRef}
        id={inputId}
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={actieveOptieId}
        aria-required={vereist}
        aria-label={toonLabel ? undefined : `${label}${vereist ? ' (verplicht)' : ''}`}
        className={fout ? 'warnfield' : undefined}
        autoComplete="off"
        placeholder={placeholder ?? 'Typen om te zoeken…'}
        value={open ? zoekterm : geselecteerd ? weergaveTekst(geselecteerd) : ''}
        onFocus={() => {
          setOpen(true)
          setZoekterm('')
        }}
        onClick={() => setOpen(true)}
        onChange={(e) => {
          setZoekterm(e.target.value)
          setOpen(true)
        }}
        onKeyDown={opToetsenbord}
      />
      {open &&
        positie &&
        createPortal(
          <div
            ref={listRef}
            role="listbox"
            id={listboxId}
            aria-label={label}
            className="combobox-listbox"
            onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
            style={{
              position: 'fixed',
              zIndex: 1000,
              top: positie.top,
              bottom: positie.bottom,
              left: positie.left,
              minWidth: positie.width,
              maxWidth: positie.maxWidth,
              width: 'max-content',
              maxHeight: positie.maxHeight,
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
                    className={`combobox-optie${echteIndex === actieveIndex ? ' actief' : ''}`}
                    style={{ position: 'absolute', top: echteIndex * RIJHOOGTE, left: 0, right: 0, height: RIJHOOGTE }}
                  >
                    {optie.code && <span className="combobox-optie-code">{optie.code}</span>}
                    <span>{optie.label}</span>
                  </div>
                )
              })}
              {gefilterd.length === 0 && <div className="combobox-leeg">Geen resultaten</div>}
            </div>
          </div>,
          document.body,
        )}
    </div>
  )
}
