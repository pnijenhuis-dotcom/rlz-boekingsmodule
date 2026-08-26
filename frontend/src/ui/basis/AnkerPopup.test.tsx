import { fireEvent, render, screen } from '@testing-library/react'
import { useRef, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AnkerPopup, berekenPositie } from './AnkerPopup'

/** Feedbackronde 26-08 punt 2: een hover-/menu-popup mag door géén enkele overflow-container
 * afgekapt worden — hij rendert via een portal op document.body met position: fixed, en flipt
 * bij de viewport-rand. */

const VIEWPORT = { width: 1200, height: 800 }
const rect = (o: Partial<DOMRect>): DOMRect =>
  ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}), ...o }) as DOMRect

describe('berekenPositie (puur)', () => {
  it('onder: standaard onder het anker, linker rand gelijk', () => {
    const anker = rect({ top: 100, bottom: 120, left: 300, right: 340 })
    expect(berekenPositie(anker, { width: 150, height: 60 }, VIEWPORT, 'onder', 'start', 6)).toEqual({ top: 126, left: 300 })
  })

  it('onder: flipt naar boven als eronder geen ruimte is en erboven wél', () => {
    const anker = rect({ top: 760, bottom: 780, left: 300, right: 340 })
    expect(berekenPositie(anker, { width: 150, height: 60 }, VIEWPORT, 'onder', 'start', 6)).toEqual({ top: 694, left: 300 })
  })

  it('onder + eind: rechter rand gelijk aan het anker (rijmenu)', () => {
    const anker = rect({ top: 100, bottom: 120, left: 1100, right: 1140 })
    expect(berekenPositie(anker, { width: 150, height: 60 }, VIEWPORT, 'onder', 'eind', 6)).toEqual({ top: 126, left: 990 })
  })

  it('rechts: naast het anker; flipt naar links bij de rechterrand', () => {
    const links = rect({ top: 100, bottom: 120, left: 40, right: 68 })
    expect(berekenPositie(links, { width: 320, height: 400 }, VIEWPORT, 'rechts', 'start', 8)).toEqual({ top: 100, left: 76 })
    const rechts = rect({ top: 100, bottom: 120, left: 1100, right: 1128 })
    expect(berekenPositie(rechts, { width: 320, height: 400 }, VIEWPORT, 'rechts', 'start', 8)).toEqual({ top: 100, left: 772 })
  })

  it('een hoge popup schuift omhoog i.p.v. onder de viewport te verdwijnen (de ~30px-bug was clipping, dit is de rand)', () => {
    const anker = rect({ top: 700, bottom: 720, left: 40, right: 68 })
    const p = berekenPositie(anker, { width: 320, height: 400 }, VIEWPORT, 'rechts', 'start', 8)
    expect(p.top + 400).toBeLessThanOrEqual(VIEWPORT.height - 8)
    expect(p.top).toBeGreaterThanOrEqual(8)
  })
})

function Harnas({ kant = 'onder' as const }) {
  const ref = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  return (
    <div className="tabel-scroll" data-testid="wrapper" style={{ overflow: 'auto', height: 30 }}>
      <table>
        <tbody>
          <tr>
            <td>
              <button ref={ref} type="button" onClick={() => setOpen((o) => !o)}>
                open
              </button>
              <AnkerPopup open={open} anker={ref} kant={kant} role="tooltip" aria-label="popup">
                inhoud
              </AnkerPopup>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

describe('AnkerPopup', () => {
  afterEach(() => vi.restoreAllMocks())

  it('rendert buiten de scroll-wrapper (portal op document.body) met position: fixed en zichtbaar ná meting', () => {
    render(<Harnas />)
    expect(screen.queryByRole('tooltip')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'open' }))
    const popup = screen.getByRole('tooltip', { name: 'popup' })
    expect(screen.getByTestId('wrapper').contains(popup)).toBe(false)
    expect(popup.parentElement).toBe(document.body)
    expect(popup.style.position).toBe('fixed')
    expect(popup.style.visibility).toBe('visible')
    expect(popup.className).toContain('anker-popup')
  })

  it('verdwijnt weer bij sluiten', () => {
    render(<Harnas />)
    const knop = screen.getByRole('button', { name: 'open' })
    fireEvent.click(knop)
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    fireEvent.click(knop)
    expect(screen.queryByRole('tooltip')).toBeNull()
  })
})
