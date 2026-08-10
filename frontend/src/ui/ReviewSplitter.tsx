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

/** Per-scherm-instelbaar (blok C 2026-08-10): het verkoopscherm deelt het splitter-patroon
 * maar heeft een eigen voorkeurssleutel en een smallere standaard-viewer (meer ruimte voor de
 * regel-tabel). Zonder opties gedraagt de hook zich exact als op het controlescherm. */
export interface ReviewSplitterOpties {
  opslagSleutel?: string
  standaardPct?: number
}

function klem(pct: number): number {
  return Math.min(MAX_PCT, Math.max(MIN_PCT, pct))
}

function bewaardeBreedte(sleutel: string, standaard: number): number {
  try {
    const bewaard = Number(window.localStorage.getItem(sleutel))
    if (Number.isFinite(bewaard) && bewaard >= MIN_PCT && bewaard <= MAX_PCT) return bewaard
  } catch {
    // localStorage kan geblokkeerd zijn (private mode) — dan gewoon de standaard.
  }
  return standaard
}

function bewaarBreedte(sleutel: string, pct: number): void {
  try {
    window.localStorage.setItem(sleutel, String(Math.round(pct * 10) / 10))
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

export function useReviewSplitter(opties: ReviewSplitterOpties = {}): ReviewSplitterState {
  const opslagSleutel = opties.opslagSleutel ?? OPSLAG_SLEUTEL
  const standaardPct = klem(opties.standaardPct ?? STANDAARD_PCT)
  const containerElement = useRef<HTMLDivElement | null>(null)
  const laatstePct = useRef<number>(bewaardeBreedte(opslagSleutel, standaardPct))
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
        bewaarBreedte(opslagSleutel, laatstePct.current)
      }
      window.addEventListener('pointermove', beweeg)
      window.addEventListener('pointerup', los)
      window.addEventListener('pointercancel', los)
    },
    [zetBreedte, opslagSleutel],
  )

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
      event.preventDefault()
      setVergroot(false)
      const richting = event.key === 'ArrowLeft' ? -1 : 1
      zetBreedte(laatstePct.current + richting * TOETS_STAP_PCT)
      bewaarBreedte(opslagSleutel, laatstePct.current)
    },
    [zetBreedte, opslagSleutel],
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
