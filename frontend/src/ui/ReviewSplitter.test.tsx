/** PDF-viewer-splitter (kliktest Peter 2026-08-08): breedte versleepbaar, voorkeur in
 * localStorage, vergroot/verklein-knop. Puur layout — geen viewer-library. */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { ReviewSplitter, ReviewVergrootKnop, useReviewSplitter } from './ReviewSplitter'

// Node 22+ schaduwt window.localStorage in de jsdom-testomgeving met zijn eigen (lege)
// experimental global ("--localstorage-file was not provided") — in-memory vervanger zodat de
// tests het echte browser-gedrag (bewaren + terugllezen) kunnen toetsen.
beforeAll(() => {
  const opslag = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (sleutel: string) => opslag.get(sleutel) ?? null,
      setItem: (sleutel: string, waarde: string) => void opslag.set(sleutel, String(waarde)),
      removeItem: (sleutel: string) => void opslag.delete(sleutel),
      clear: () => opslag.clear(),
    },
  })
})

function Harnas() {
  const splitter = useReviewSplitter()
  return (
    <div className="review" ref={splitter.containerRef} style={splitter.stijl} data-testid="review">
      <div className="docpane">
        <ReviewVergrootKnop splitter={splitter} />
      </div>
      <ReviewSplitter splitter={splitter} />
      <div className="formpane" />
    </div>
  )
}

function docpaneBreedte(): string {
  return screen.getByTestId('review').style.getPropertyValue('--docpane-breedte')
}

describe('ReviewSplitter', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('start op de standaardbreedte en leest een bewaarde voorkeur terug', () => {
    const eerste = render(<Harnas />)
    expect(docpaneBreedte()).toBe('50%')
    eerste.unmount()

    window.localStorage.setItem('rlz.controle.docpaneBreedtePct', '62')
    render(<Harnas />)
    expect(docpaneBreedte()).toBe('62%')
  })

  it('negeert een onbruikbare bewaarde waarde', () => {
    window.localStorage.setItem('rlz.controle.docpaneBreedtePct', '999')
    render(<Harnas />)
    expect(docpaneBreedte()).toBe('50%')
  })

  it('versleept de breedte met pointer-events en bewaart de voorkeur bij loslaten', () => {
    render(<Harnas />)
    const review = screen.getByTestId('review')
    review.getBoundingClientRect = () =>
      ({ left: 0, width: 1000, top: 0, height: 800, right: 1000, bottom: 800, x: 0, y: 0 }) as DOMRect

    const separator = screen.getByRole('separator')
    fireEvent.pointerDown(separator, { clientX: 500 })
    fireEvent.pointerMove(window, { clientX: 600 })
    expect(docpaneBreedte()).toBe('60%')

    fireEvent.pointerUp(window)
    expect(window.localStorage.getItem('rlz.controle.docpaneBreedtePct')).toBe('60')
  })

  it('klemt het slepen binnen de min/max-grenzen', () => {
    render(<Harnas />)
    const review = screen.getByTestId('review')
    review.getBoundingClientRect = () =>
      ({ left: 0, width: 1000, top: 0, height: 800, right: 1000, bottom: 800, x: 0, y: 0 }) as DOMRect

    const separator = screen.getByRole('separator')
    fireEvent.pointerDown(separator, { clientX: 500 })
    fireEvent.pointerMove(window, { clientX: 990 })
    expect(docpaneBreedte()).toBe('75%')
    fireEvent.pointerMove(window, { clientX: 10 })
    expect(docpaneBreedte()).toBe('28%')
    fireEvent.pointerUp(window)
  })

  it('is met het toetsenbord te bedienen (pijltjes op de separator)', () => {
    render(<Harnas />)
    const separator = screen.getByRole('separator')
    fireEvent.keyDown(separator, { key: 'ArrowRight' })
    expect(docpaneBreedte()).toBe('52%')
    fireEvent.keyDown(separator, { key: 'ArrowLeft' })
    fireEvent.keyDown(separator, { key: 'ArrowLeft' })
    expect(docpaneBreedte()).toBe('48%')
    expect(window.localStorage.getItem('rlz.controle.docpaneBreedtePct')).toBe('48')
  })

  it('vergroot-knop zet de viewer breed en weer terug, zonder de voorkeur te overschrijven', () => {
    window.localStorage.setItem('rlz.controle.docpaneBreedtePct', '45')
    render(<Harnas />)
    expect(docpaneBreedte()).toBe('45%')

    const knop = screen.getByRole('button', { name: '⤢ Vergroot' })
    fireEvent.click(knop)
    expect(docpaneBreedte()).toBe('70%')

    fireEvent.click(screen.getByRole('button', { name: '⤡ Verklein' }))
    expect(docpaneBreedte()).toBe('45%')
    // De vergroot-stand is tijdelijk: de bewaarde voorkeur blijft onaangeroerd.
    expect(window.localStorage.getItem('rlz.controle.docpaneBreedtePct')).toBe('45')
  })
})
