/**
 * Versleepbare scheiding tussen bijlage-viewer en formulier op het controlescherm
 * (kliktest Peter 2026-08-08: het factuurbeeld is het primaire werkobject — viewer dominant,
 * breedte instelbaar, voorkeur onthouden). Puur een layout-oplossing: de breedte leeft als
 * CSS-variabele op de .review-container, de bestaande <object>-viewer blijft ongemoeid.
 *
 * Gebruik:
 *   const splitter = useReviewSplitter()
 *   <div className="review" ref={splitter.containerRef} style={splitter.stijl}>
 *     <div className="docpane">… <ReviewVergrootKnop splitter={splitter} /> …</div>
 *     <ReviewSplitter splitter={splitter} />
 *     <div className="formpane">…</div>
 *   </div>
 */

import { useCallback, useRef, useState } from 'react'
import type { CSSProperties } from 'react'

const OPSLAG_SLEUTEL = 'rlz.controle.docpaneBreedtePct'
const MIN_PCT = 28
const MAX_PCT = 75
const STANDAARD_PCT = 50
const VERGROOT_PCT = 70
const TOETS_STAP_PCT = 2

function klem(pct: number): number {
  return Math.min(MAX_PCT, Math.max(MIN_PCT, pct))
}

function bewaardeBreedte(): number {
  try {
    const bewaard = Number(window.localStorage.getItem(OPSLAG_SLEUTEL))
    if (Number.isFinite(bewaard) && bewaard >= MIN_PCT && bewaard <= MAX_PCT) return bewaard
  } catch {
    // localStorage kan geblokkeerd zijn (private mode) — dan gewoon de standaard.
  }
  return STANDAARD_PCT
}

function bewaarBreedte(pct: number): void {
  try {
    window.localStorage.setItem(OPSLAG_SLEUTEL, String(Math.round(pct * 10) / 10))
  } catch {
    // Niet kunnen bewaren is geen fout — de sessie werkt gewoon door.
  }
}

export interface ReviewSplitterState {
  containerRef: (element: HTMLDivElement | null) => void
  stijl: CSSProperties
  breedtePct: number
  slepen: boolean
  vergroot: boolean
  toggleVergroot: () => void
  onPointerDown: (event: React.PointerEvent<HTMLDivElement>) => void
  onKeyDown: (event: React.KeyboardEvent<HTMLDivElement>) => void
}

export function useReviewSplitter(): ReviewSplitterState {
  const containerElement = useRef<HTMLDivElement | null>(null)
  const laatstePct = useRef<number>(bewaardeBreedte())
  const [breedtePct, setBreedtePct] = useState<number>(laatstePct.current)
  const [slepen, setSlepen] = useState(false)
  const [vergroot, setVergroot] = useState(false)

  const containerRef = useCallback((element: HTMLDivElement | null) => {
    containerElement.current = element
  }, [])

  const zetBreedte = useCallback((pct: number) => {
    const geklemd = klem(pct)
    laatstePct.current = geklemd
    setBreedtePct(geklemd)
  }, [])

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const container = containerElement.current
      if (!container) return
      event.preventDefault()
      setSlepen(true)
      setVergroot(false) // handmatig slepen wint van de vergroot-stand

      const beweeg = (ev: PointerEvent) => {
        const rect = container.getBoundingClientRect()
        if (rect.width <= 0) return
        zetBreedte(((ev.clientX - rect.left) / rect.width) * 100)
      }
      const los = () => {
        window.removeEventListener('pointermove', beweeg)
        window.removeEventListener('pointerup', los)
        window.removeEventListener('pointercancel', los)
        setSlepen(false)
        bewaarBreedte(laatstePct.current)
      }
      window.addEventListener('pointermove', beweeg)
      window.addEventListener('pointerup', los)
      window.addEventListener('pointercancel', los)
    },
    [zetBreedte],
  )

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
      event.preventDefault()
      setVergroot(false)
      const richting = event.key === 'ArrowLeft' ? -1 : 1
      zetBreedte(laatstePct.current + richting * TOETS_STAP_PCT)
      bewaarBreedte(laatstePct.current)
    },
    [zetBreedte],
  )

  const toggleVergroot = useCallback(() => setVergroot((huidig) => !huidig), [])

  const effectiefPct = vergroot ? Math.max(breedtePct, VERGROOT_PCT) : breedtePct
  const stijl = { '--docpane-breedte': `${effectiefPct}%` } as CSSProperties

  return {
    containerRef,
    stijl,
    breedtePct: effectiefPct,
    slepen,
    vergroot,
    toggleVergroot,
    onPointerDown,
    onKeyDown,
  }
}

export function ReviewSplitter({ splitter }: { splitter: ReviewSplitterState }) {
  return (
    <div
      className={splitter.slepen ? 'review-splitter actief' : 'review-splitter'}
      role="separator"
      aria-orientation="vertical"
      aria-label="Breedte factuurbeeld aanpassen"
      aria-valuenow={Math.round(splitter.breedtePct)}
      aria-valuemin={MIN_PCT}
      aria-valuemax={MAX_PCT}
      tabIndex={0}
      onPointerDown={splitter.onPointerDown}
      onKeyDown={splitter.onKeyDown}
    />
  )
}

export function ReviewVergrootKnop({ splitter }: { splitter: ReviewSplitterState }) {
  return (
    <button
      type="button"
      className="btn secondary"
      style={{ padding: '3px 10px', fontSize: 12 }}
      onClick={splitter.toggleVergroot}
      aria-pressed={splitter.vergroot}
      title={splitter.vergroot ? 'Factuurbeeld terug naar de ingestelde breedte' : 'Factuurbeeld vergroten'}
    >
      {splitter.vergroot ? '⤡ Verklein' : '⤢ Vergroot'}
    </button>
  )
}
