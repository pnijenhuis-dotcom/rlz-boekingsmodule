import { describe, expect, it } from 'vitest'
import { btwPastBijTarief, btwUitTarief, brutoUitNetto, margeVoor, splitsBruto, zetBtwInKosten } from './regelsom'

/** Spiegel van backend/tests/documenten/test_regelsom_btw_tarief.py (opdracht Peter 18-09, casus Rituals). */
describe('regelsom — btw volgt het tarief (18-09)', () => {
  it('btw uit tarief en bruto uit netto, cent-exact', () => {
    expect(btwUitTarief(96.36, 0.21)).toBe(20.24)
    expect(brutoUitNetto(96.36, 0.21)).toBe(116.6)
    expect(btwUitTarief(0.1, 0.21)).toBe(0.02) // 0.021 → ROUND_HALF_UP op de cent
  })
  it('btw in kosten en terug splitsen geeft de oorspronkelijke splitsing terug (21 → 0 → 21)', () => {
    expect(zetBtwInKosten(96.36, 20.24)).toEqual([116.6, 0])
    expect(splitsBruto(116.6, 0.21)).toEqual([96.36, 20.24])
    expect(splitsBruto(116.6, 0)).toEqual([116.6, 0])
    expect(splitsBruto(-11.77, 0.09)).toEqual([-10.8, -0.97])
  })
  it('marge 1 cent per samengevoegde regel, min 1 max 5', () => {
    expect(margeVoor(0)).toBe(0.01)
    expect(margeVoor(3)).toBe(0.03)
    expect(margeVoor(6)).toBe(0.05)
  })
  it('btw past bij tarief binnen de marge', () => {
    expect(btwPastBijTarief(96.36, 20.24, 0.21)).toBe(true)
    expect(btwPastBijTarief(96.36, 20.21, 0.21, 6)).toBe(true)
    expect(btwPastBijTarief(96.36, 20.21, 0.21)).toBe(false)
    expect(btwPastBijTarief(96.36, 20.1, 0.21)).toBe(false)
    expect(btwPastBijTarief(96.36, 20.24, 0)).toBe(false)
  })
})
