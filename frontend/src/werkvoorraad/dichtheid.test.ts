import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { DICHTHEID_OPSLAG_SLEUTEL, bewaarDichtheid, leesDichtheid } from './dichtheid'

// Node 22+/jsdom: geen bruikbare window.localStorage — in-memory vervanger (patroon
// ui/ReviewSplitter.test.tsx) zodat de voorkeur-/melding-opslag echt getoetst wordt.
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

describe('dichtheid — voorkeur per gebruiker in localStorage (punt 3b)', () => {
  beforeAll(() => installeerLocalStorage())
  afterEach(() => window.localStorage.removeItem(DICHTHEID_OPSLAG_SLEUTEL))

  it('standaard normaal; compact wordt onthouden; onbekende waarde valt terug op normaal', () => {
    expect(leesDichtheid()).toBe('normaal')
    bewaarDichtheid('compact')
    expect(window.localStorage.getItem(DICHTHEID_OPSLAG_SLEUTEL)).toBe('compact')
    expect(leesDichtheid()).toBe('compact')
    window.localStorage.setItem(DICHTHEID_OPSLAG_SLEUTEL, 'iets-anders')
    expect(leesDichtheid()).toBe('normaal')
  })
})
