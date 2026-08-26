import { useCallback, useLayoutEffect, useState, type CSSProperties, type HTMLAttributes, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { cn } from './cn'

/** Popup die aan een anker-element hangt maar op DOCUMENTNIVEAU rendert (portal + `position:
 * fixed`), zodat geen enkele scroll-/overflow-container hem kan afkappen.
 *
 * Aanleiding (feedbackronde 26-08, punt 2): de verzamelbak-hover-preview stond als
 * `position: absolute` bínnen `.tabel-scroll` (overflow-x: auto → per CSS-spec óók een
 * verticale scroll-container) én binnen `table { overflow: hidden }` — de popup rendert en
 * laadt correct, maar werd na ~30 px afgekapt. Dezelfde klasse zat in het ⋯-rijmenu van het
 * archief. Radix Popover (DatePicker) en de handmatige portal van SearchableCombobox lossen
 * dit al op voor klik-popovers; dit is de gedeelde, lichte variant voor hover-/menu-popups.
 *
 * Gedrag:
 * - `kant="onder"`: onder het anker, flipt naar boven als daar meer ruimte is en de popup
 *   onder niet past; `uitlijning` = linker- of rechterrand gelijk aan het anker.
 * - `kant="rechts"`: rechts naast het anker (bovenranden gelijk), flipt naar links als de
 *   popup rechts niet past en links meer ruimte heeft.
 * - Daarna altijd geclampt binnen de viewport (marge 8 px) — een hoge popup schuift omhoog
 *   i.p.v. onder het scherm te verdwijnen.
 * - Herpositioneert bij scroll op élke voorouder (capture), resize, en bij eigen
 *   maatverandering (ResizeObserver — de preview groeit zodra pdf.js de pagina heeft).
 * - Scrollt het anker zelf uit beeld, dan meldt `onAnkerUitBeeld` dat (de eigenaar sluit).
 *
 * Bewust GEEN focus-trap/auto-focus: dit is presentatie bij hover of een klein rijmenu; de
 * eigenaar bepaalt open/dicht. React-events (klik/hover) bubbelen via de React-boom, dus een
 * `stopPropagation` in de inhoud werkt zoals vóór de portal. */
export type AnkerKant = 'onder' | 'rechts'
export type AnkerUitlijning = 'start' | 'eind'

const VIEWPORT_MARGE = 8

type Positie = { top: number; left: number }

/** Het anker: een ref (stabiel) óf het element zelf (bv. uit een per-rij ref-map). */
export type Anker = RefObject<HTMLElement | null> | HTMLElement | null

function ankerElement(anker: Anker): HTMLElement | null {
  if (anker === null) return null
  return anker instanceof HTMLElement ? anker : anker.current
}

export interface AnkerPopupProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  open: boolean
  anker: Anker
  kant?: AnkerKant
  uitlijning?: AnkerUitlijning
  /** Afstand tot het anker in px. */
  afstand?: number
  onAnkerUitBeeld?: () => void
  children: ReactNode
}

export function berekenPositie(
  anker: DOMRect,
  popup: { width: number; height: number },
  viewport: { width: number; height: number },
  kant: AnkerKant,
  uitlijning: AnkerUitlijning,
  afstand: number,
): Positie {
  let top: number
  let left: number
  if (kant === 'onder') {
    const ruimteOnder = viewport.height - anker.bottom - VIEWPORT_MARGE
    const ruimteBoven = anker.top - VIEWPORT_MARGE
    const naarBoven = popup.height > ruimteOnder && ruimteBoven > ruimteOnder
    top = naarBoven ? anker.top - afstand - popup.height : anker.bottom + afstand
    left = uitlijning === 'eind' ? anker.right - popup.width : anker.left
  } else {
    const ruimteRechts = viewport.width - anker.right - VIEWPORT_MARGE
    const ruimteLinks = anker.left - VIEWPORT_MARGE
    const naarLinks = popup.width > ruimteRechts && ruimteLinks > ruimteRechts
    left = naarLinks ? anker.left - afstand - popup.width : anker.right + afstand
    top = uitlijning === 'eind' ? anker.bottom - popup.height : anker.top
  }
  // Clamp: liever verschoven dan afgekapt door de viewport-rand.
  left = Math.max(VIEWPORT_MARGE, Math.min(left, viewport.width - VIEWPORT_MARGE - popup.width))
  top = Math.max(VIEWPORT_MARGE, Math.min(top, viewport.height - VIEWPORT_MARGE - popup.height))
  return { top: Math.round(top), left: Math.round(left) }
}

export function AnkerPopup({
  open,
  anker,
  kant = 'onder',
  uitlijning = 'start',
  afstand = 6,
  onAnkerUitBeeld,
  children,
  className,
  style,
  ...rest
}: AnkerPopupProps) {
  const [el, setEl] = useState<HTMLDivElement | null>(null)
  const [positie, setPositie] = useState<Positie | null>(null)

  const herbereken = useCallback(() => {
    const ankerEl = ankerElement(anker)
    if (!ankerEl || !el) return
    const a = ankerEl.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    if (a.bottom < 0 || a.top > vh || a.right < 0 || a.left > vw) {
      onAnkerUitBeeld?.()
      return
    }
    const nieuw = berekenPositie(a, { width: el.offsetWidth, height: el.offsetHeight }, { width: vw, height: vh }, kant, uitlijning, afstand)
    setPositie((huidig) => (huidig && huidig.top === nieuw.top && huidig.left === nieuw.left ? huidig : nieuw))
  }, [anker, el, kant, uitlijning, afstand, onAnkerUitBeeld])

  useLayoutEffect(() => {
    if (!open || !el) {
      setPositie(null)
      return
    }
    herbereken()
    // capture:true zodat scroll op ELKE voorouder-container (bv. .tabel-scroll) de positie
    // bijwerkt — anders drijft de popup weg van zijn anker (les SearchableCombobox).
    window.addEventListener('scroll', herbereken, true)
    window.addEventListener('resize', herbereken)
    let observer: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(() => herbereken())
      observer.observe(el)
    }
    return () => {
      window.removeEventListener('scroll', herbereken, true)
      window.removeEventListener('resize', herbereken)
      observer?.disconnect()
    }
  }, [open, el, herbereken])

  if (!open) return null
  const inline: CSSProperties = {
    position: 'fixed',
    top: positie?.top ?? 0,
    left: positie?.left ?? 0,
    // Eerst meten, dan tonen: de eerste render staat op (0,0) tot de maat bekend is.
    visibility: positie ? 'visible' : 'hidden',
    ...style,
  }
  return createPortal(
    <div ref={setEl} className={cn('anker-popup', className)} style={inline} {...rest}>
      {children}
    </div>,
    document.body,
  )
}
