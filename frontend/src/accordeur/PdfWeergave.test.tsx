import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

// Peter 15-09: eigen zoomlaag + "⤢ Volledig scherm" in de PDF-weergave. pdf.js wordt gemockt (jsdom rendert geen canvas);
// de gebaar-wiskunde staat apart in pdfZoom.test.ts — hier: knop verschijnt ná het renderen, fullscreen-overlay opent/sluit
// (knop, Escape, terug-gebaar), dubbeltik zet de zoom op 2× en ingezoomd blokkeert het meescrollen (touch-action none).

const paginaMock = {
  getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 800 * scale }),
  render: () => ({ promise: Promise.resolve() }),
}
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: () => ({ promise: Promise.resolve({ numPages: 2, getPage: async () => paginaMock }) }),
}))
vi.mock('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url', () => ({ default: 'worker.js' }))

import { PdfWeergave } from './PdfWeergave'

afterEach(() => {
  vi.restoreAllMocks()
})

function tik(el: Element, x: number, y: number, id = 1) {
  fireEvent.pointerDown(el, { pointerId: id, clientX: x, clientY: y })
  fireEvent.pointerUp(el, { pointerId: id, clientX: x, clientY: y })
}

describe('PdfWeergave — zoom + volledig scherm', () => {
  it('toont ná het renderen de knop "Volledig scherm"; de overlay opent en sluit via de knop en Escape', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
    render(<PdfWeergave blobUrl="blob:factuur" laden={false} fout={null} />)
    const knop = await screen.findByTestId('pdf-volledig-scherm')
    fireEvent.click(knop)
    expect(screen.getByTestId('pdf-fullscreen')).toBeInTheDocument()
    expect(document.body.style.overflow).toBe('hidden')
    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('pdf-fullscreen')).not.toBeInTheDocument())
    fireEvent.click(screen.getByTestId('pdf-volledig-scherm'))
    expect(screen.getByTestId('pdf-fullscreen')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Volledig scherm sluiten/ }))
    await waitFor(() => expect(screen.queryByTestId('pdf-fullscreen')).not.toBeInTheDocument())
  })

  it('dubbeltik zoomt naar 2× (touch-action none, terugknop) en nog een dubbeltik gaat terug naar 1×', async () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({} as CanvasRenderingContext2D)
    render(<PdfWeergave blobUrl="blob:factuur" laden={false} fout={null} />)
    await screen.findByTestId('pdf-volledig-scherm')
    const viewport = screen.getByTestId('pdf-viewport')
    const pane = viewport.parentElement as HTMLElement
    expect(pane.getAttribute('data-zoom')).toBe('1.00')
    expect(viewport.style.touchAction).toBe('pan-y pinch-zoom')
    let nu = 1000
    vi.spyOn(performance, 'now').mockImplementation(() => (nu += 50))
    act(() => {
      tik(viewport, 100, 120)
      tik(viewport, 102, 121)
    })
    expect(pane.getAttribute('data-zoom')).toBe('2.00')
    expect(viewport.style.touchAction).toBe('none')
    expect(screen.getByRole('button', { name: /Zoom terug/ })).toHaveTextContent('200 %')
    act(() => {
      tik(viewport, 100, 120)
      tik(viewport, 101, 120)
    })
    expect(pane.getAttribute('data-zoom')).toBe('1.00')
  })

  it('zonder blobUrl of mét fout: geen fullscreen-knop, wél de bestaande fout-/laadstand', () => {
    const { rerender } = render(<PdfWeergave blobUrl={null} laden fout={null} />)
    expect(screen.getByRole('status')).toHaveTextContent('PDF laden…')
    expect(screen.queryByTestId('pdf-volledig-scherm')).not.toBeInTheDocument()
    rerender(<PdfWeergave blobUrl={null} laden={false} fout="Het factuurbeeld kon niet geladen worden." />)
    expect(screen.getByRole('alert')).toHaveTextContent('kon niet geladen worden')
  })
})
