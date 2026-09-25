import * as React from 'react'
import { useEffect, useRef } from 'react'
import { cn } from './cn'

/* Zijpaneel — NIET-modaal paneel aan de rechterkant (blok 5 feedbackrun 25-09, FV-14: "crediteur aanmaken zonder
 * zicht op de factuur"). Anders dan Dialog: géén overlay, geen scroll-lock, geen focus-trap — de bijlage-viewer links
 * blijft leesbaar én scrollbaar. Wél: role=dialog met aria-modal="false", Escape en ✕ sluiten, focus naar het eerste
 * veld bij openen, focus terug naar de opener bij sluiten. Vormgeving via tokens (styles/components.css .zijpaneel). */
export function Zijpaneel({
  titel,
  beschrijving,
  onSluit,
  children,
  className,
  testId,
  ...props
}: React.HTMLAttributes<HTMLElement> & {
  titel: string
  beschrijving?: React.ReactNode
  onSluit: () => void
  testId?: string
}) {
  const ref = useRef<HTMLElement | null>(null)
  const opener = useRef<HTMLElement | null>(null)
  const titelId = React.useId()

  useEffect(() => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const eerste = ref.current?.querySelector<HTMLElement>('input, select, textarea, button:not([data-sluit])')
    eerste?.focus()
    return () => {
      opener.current?.focus?.()
    }
  }, [])

  useEffect(() => {
    const opEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onSluit()
      }
    }
    const el = ref.current
    el?.addEventListener('keydown', opEscape)
    return () => el?.removeEventListener('keydown', opEscape)
  }, [onSluit])

  return (
    <aside
      ref={ref}
      role="dialog"
      aria-modal="false"
      aria-labelledby={titelId}
      className={cn('zijpaneel', className)}
      data-testid={testId ?? 'zijpaneel'}
      {...props}
    >
      <div className="zijpaneel-kop">
        <h2 id={titelId} className="m-0 text-[15px] font-bold">
          {titel}
        </h2>
        <button type="button" className="linkbtn" data-sluit onClick={onSluit} aria-label="Paneel sluiten">
          ✕
        </button>
      </div>
      {beschrijving && <p className="m-0 mb-3 text-[12.5px] text-muted">{beschrijving}</p>}
      {children}
    </aside>
  )
}
