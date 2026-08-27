// Pull-to-refresh (feedback Peter 27-08): trek de lijst naar beneden bovenaan de scrolcontainer
// → "Laat los om te verversen" → onVerversen(). Eigen, kleine implementatie op touch-events
// (geen dependency, werkt in PWA én in de Capacitor-webview); de native browser-verversing van
// Chrome wordt via `overscroll-behavior: contain` op .acc-content buiten de deur gehouden.
// Toegankelijk alternatief blijft de verversknop op de lege staat + het automatisch verversen
// bij het naar de voorgrond komen (useVerversBijVoorgrond).

import { useRef, useState, type ReactNode, type TouchEvent } from 'react'

/** Trekafstand (px, ná demping) waarna loslaten ververst. */
export const PULL_DREMPEL_PX = 64
const MAX_PX = 110

interface Props {
  onVerversen: () => Promise<unknown>
  children: ReactNode
}

/** Dichtstbijzijnde scrollende voorouder — de trek telt alleen als die bovenaan staat. */
function scrollBovenaan(el: HTMLElement | null): boolean {
  let node: HTMLElement | null = el
  while (node) {
    const overflowY = typeof getComputedStyle === 'function' ? getComputedStyle(node).overflowY : ''
    if (overflowY === 'auto' || overflowY === 'scroll') return node.scrollTop <= 0
    node = node.parentElement
  }
  return (window.scrollY ?? 0) <= 0
}

export function PullToRefresh({ onVerversen, children }: Props) {
  const [afstand, setAfstand] = useState(0)
  const [bezig, setBezig] = useState(false)
  const startY = useRef<number | null>(null)
  const wrapper = useRef<HTMLDivElement>(null)

  const onTouchStart = (e: TouchEvent<HTMLDivElement>) => {
    if (bezig || e.touches.length !== 1) return
    startY.current = scrollBovenaan(wrapper.current) ? e.touches[0].clientY : null
  }
  const onTouchMove = (e: TouchEvent<HTMLDivElement>) => {
    if (startY.current === null || bezig) return
    const dy = e.touches[0].clientY - startY.current
    if (dy <= 0) {
      setAfstand(0)
      return
    }
    // Demping: de eerste centimeters volgen de vinger, daarna steeds trager (voelt natuurlijk).
    setAfstand(Math.min(MAX_PX, dy * 0.55))
  }
  const onTouchEnd = () => {
    if (startY.current === null) return
    startY.current = null
    if (afstand >= PULL_DREMPEL_PX && !bezig) {
      setBezig(true)
      setAfstand(40)
      void onVerversen().finally(() => {
        setBezig(false)
        setAfstand(0)
      })
    } else {
      setAfstand(0)
    }
  }

  const tekst = bezig ? 'Verversen…' : afstand >= PULL_DREMPEL_PX ? 'Laat los om te verversen' : 'Trek om te verversen'
  return (
    <div ref={wrapper} onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd} onTouchCancel={onTouchEnd}>
      <div
        className={`acc-ptr${bezig ? ' bezig' : ''}`}
        style={{ height: afstand, opacity: afstand > 8 ? 1 : 0 }}
        aria-live="polite"
        role="status"
        data-testid="pull-to-refresh"
      >
        {afstand > 8 && (
          <>
            <span className="acc-ptr-pijl" aria-hidden="true">
              {bezig ? '↻' : afstand >= PULL_DREMPEL_PX ? '↑' : '↓'}
            </span>
            {tekst}
          </>
        )}
      </div>
      {children}
    </div>
  )
}
