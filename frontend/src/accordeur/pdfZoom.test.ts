import { describe, expect, it } from 'vitest'
import {
  BEGINSTAND,
  clampSchaal,
  clampVerschuiving,
  dubbeltik,
  knijp,
  pan,
  renderStap,
  zoomRond,
  ZOOM_MAX,
  ZOOM_MIN,
} from './pdfZoom'

// Peter 15-09: eigen knijpzoom in de PDF-weergave (native WebView/PWA-standalone) — de gebaar-wiskunde puur getest.
const VP = { breedte: 360, hoogte: 600 }

describe('pdfZoom', () => {
  it('clampt de schaal op 1×–4×', () => {
    expect(clampSchaal(0.2)).toBe(ZOOM_MIN)
    expect(clampSchaal(9)).toBe(ZOOM_MAX)
    expect(clampSchaal(2.5)).toBe(2.5)
    expect(clampSchaal(Number.NaN)).toBe(ZOOM_MIN)
  })

  it('zoomRond houdt het inhoudspunt onder de vinger', () => {
    const stand = zoomRond(BEGINSTAND, 2, { x: 100, y: 200 })
    expect(stand.schaal).toBe(2)
    // inhoudspunt (100,200) op schaal 1 → op schaal 2 staat het op 2·100 + x = 100 → x = −100
    expect(stand.x).toBe(-100)
    expect(stand.y).toBe(-200)
    // nog eens rond hetzelfde punt naar 4×: het punt blijft staan
    const verder = zoomRond(stand, 4, { x: 100, y: 200 })
    expect(verder.x).toBe(-300)
    expect(verder.y).toBe(-600)
  })

  it('knijp: schaal volgt de vingerafstand op de beginschaal, rond het middelpunt', () => {
    const stand = knijp(BEGINSTAND, 100, 200, { x: 180, y: 300 })
    expect(stand.schaal).toBe(2)
    expect(stand.x).toBe(-180)
    expect(knijp(BEGINSTAND, 0, 200, { x: 0, y: 0 })).toEqual(BEGINSTAND) // ongeldige beginafstand = niets
    expect(knijp(BEGINSTAND, 100, 900, { x: 0, y: 0 }).schaal).toBe(ZOOM_MAX)
  })

  it('dubbeltik: 1× → 2× op de tikplek, daarna terug naar 1×', () => {
    const in2 = dubbeltik(BEGINSTAND, { x: 50, y: 80 })
    expect(in2).toEqual({ schaal: 2, x: -50, y: -80 })
    expect(dubbeltik(in2, { x: 0, y: 0 })).toEqual(BEGINSTAND)
    expect(dubbeltik({ schaal: 3.5, x: -10, y: -10 }, { x: 0, y: 0 })).toEqual(BEGINSTAND)
  })

  it('clampVerschuiving houdt de inhoud binnen het vak en laat op 1× geen verschuiving toe', () => {
    expect(clampVerschuiving({ schaal: 1, x: -40, y: -40 }, VP, 1000)).toEqual({ schaal: 1, x: 0, y: -40 })
    // 2×: inhoud 720 breed in een vak van 360 → x ∈ [−360, 0]
    expect(clampVerschuiving({ schaal: 2, x: -500, y: 20 }, VP, 1000).x).toBe(-360)
    expect(clampVerschuiving({ schaal: 2, x: -500, y: 20 }, VP, 1000).y).toBe(0)
    // y: inhoud 2000 hoog in een vak van 600 → y ∈ [−1400, 0]
    expect(clampVerschuiving({ schaal: 2, x: 0, y: -9999 }, VP, 1000).y).toBe(-1400)
    // inhoud korter dan het vak: y blijft 0
    expect(clampVerschuiving({ schaal: 1, x: 0, y: -50 }, VP, 300).y).toBe(0)
  })

  it('pan telt op; renderStap kiest de hoogst gebruikte hele stap', () => {
    expect(pan({ schaal: 2, x: -10, y: -10 }, -5, 7)).toEqual({ schaal: 2, x: -15, y: -3 })
    expect(renderStap(1)).toBe(1)
    expect(renderStap(1.2)).toBe(2)
    expect(renderStap(2)).toBe(2)
    expect(renderStap(3.7)).toBe(4)
    expect(renderStap(4)).toBe(4)
  })
})
