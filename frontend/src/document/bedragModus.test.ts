// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import {
  BEDRAGMODUS_OPSLAG_SLEUTEL,
  bewaarBedragModus,
  brutoNaarNetto,
  leesBedragModus,
  nettoNaarBruto,
  rekenOm,
} from './bedragModus'

// Node 22+/jsdom: geen bruikbare window.localStorage — in-memory vervanger (patroon WerkvoorraadScreen.test.tsx).
function installeerLocalStorage() {
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
}

describe('bedragModus (blok E, Peter 16-09)', () => {
  beforeAll(() => installeerLocalStorage())
  afterEach(() => window.localStorage.clear())

  it('rekent cent-exact om: netto ↔ bruto op het percentage van de btw-code', () => {
    expect(nettoNaarBruto(100, 0.21)).toBe(121)
    expect(brutoNaarNetto(121, 0.21)).toBe(100)
    // Kassabedragen (incl.) uit het ProfX-journaal: bruto 88,50 laag → netto 81,19, btw 7,31 sluit op de cent.
    const netto = brutoNaarNetto(88.5, 0.09)
    expect(netto).toBe(81.19)
    expect(Math.round((88.5 - netto) * 100) / 100).toBe(7.31)
    // Vrijgesteld/0 %: netto = bruto.
    expect(brutoNaarNetto(6431.47, 0)).toBe(6431.47)
    expect(nettoNaarBruto(6431.47, 0)).toBe(6431.47)
  })

  it('laat een waarde ongewijzigd zonder percentage (geen btw-code) of bij gelijke modus', () => {
    expect(rekenOm(123.45, 'netto', 'bruto', undefined)).toBe(123.45)
    expect(rekenOm(123.45, 'bruto', 'bruto', 0.21)).toBe(123.45)
    expect(rekenOm(100, 'netto', 'bruto', 0.21)).toBe(121)
    expect(rekenOm(121, 'bruto', 'netto', 0.21)).toBe(100)
  })

  it('onthoudt de voorkeur per gebruiker in localStorage en valt terug op netto', () => {
    expect(leesBedragModus()).toBe('netto')
    bewaarBedragModus('bruto')
    expect(window.localStorage.getItem(BEDRAGMODUS_OPSLAG_SLEUTEL)).toBe('bruto')
    expect(leesBedragModus()).toBe('bruto')
    window.localStorage.setItem(BEDRAGMODUS_OPSLAG_SLEUTEL, 'onzin')
    expect(leesBedragModus()).toBe('netto')
  })
})
