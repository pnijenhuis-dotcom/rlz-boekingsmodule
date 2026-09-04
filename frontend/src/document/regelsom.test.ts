import { describe, expect, it } from 'vitest'
import { toetsRegelsom } from './regelsom'

// Huvanco-vorm (bugfix 04-09): regels zonder btw per regel + kortingsregel negatief.
const HUVANCO = { netto: [400, 164.4, -56.44], btw: [null, null, null] }

describe('toetsRegelsom — dezelfde beslisboom als de backend', () => {
  it('1. btw per regel compleet + incl bekend → Σ(netto+btw) vs incl', () => {
    const u = toetsRegelsom({ netto: [100, 50], btw: [21, 10.5], totaalIncl: 181.5, totaalExcl: 150, factuurBtw: null })
    expect(u.basis).toBe('incl')
    expect(u.som).toBe(181.5)
    expect(u.sluitAan).toBe(true)
  })

  it('2. zonder btw per regel maar mét gelezen excl → netto-vs-netto (de Huvanco-fix)', () => {
    const u = toetsRegelsom({ ...HUVANCO, totaalIncl: 614.63, totaalExcl: 507.96, factuurBtw: null })
    expect(u.basis).toBe('excl')
    expect(u.som).toBe(507.96)
    expect(u.sluitAan).toBe(true)
  })

  it('3. zonder excl maar mét factuur-btw → Σnetto + factuur-btw vs incl', () => {
    const u = toetsRegelsom({ ...HUVANCO, totaalIncl: 614.63, totaalExcl: null, factuurBtw: 106.67 })
    expect(u.basis).toBe('incl')
    expect(u.som).toBe(614.63)
    expect(u.sluitAan).toBe(true)
  })

  it('4. alleen incl en geen btw per regel → expliciet niet toetsbaar, nooit excl-vs-incl', () => {
    const u = toetsRegelsom({ ...HUVANCO, totaalIncl: 614.63, totaalExcl: null, factuurBtw: null })
    expect(u.basis).toBeNull()
    expect(u.reden).toBe('btw_per_regel_ontbreekt')
    expect(u.regelsZonderBtw).toEqual([1, 2, 3])
    expect(u.nettoSom).toBe(507.96)
    expect(u.sluitAan).toBeNull()
  })

  it('een echte afwijking blijft zichtbaar op elke basis, mét de basis erbij', () => {
    const excl = toetsRegelsom({ ...HUVANCO, totaalIncl: 614.63, totaalExcl: 600, factuurBtw: null })
    expect(excl.basis).toBe('excl')
    expect(excl.sluitAan).toBe(false)
    expect(excl.verschil).toBe(92.04)
    const incl = toetsRegelsom({ netto: [100], btw: [21], totaalIncl: 200, totaalExcl: null, factuurBtw: null })
    expect(incl.sluitAan).toBe(false)
    expect(incl.verschil).toBe(79)
  })

  it('cent-tolerantie en centen-rekenen zonder float-ruis', () => {
    expect(toetsRegelsom({ netto: [100], btw: [21], totaalIncl: 121.01, totaalExcl: null, factuurBtw: null }).sluitAan).toBe(true)
    expect(toetsRegelsom({ netto: [100], btw: [21], totaalIncl: 121.02, totaalExcl: null, factuurBtw: null }).sluitAan).toBe(false)
    expect(toetsRegelsom({ netto: [0.1, 0.2], btw: [0, 0], totaalIncl: 0.3, totaalExcl: null, factuurBtw: null }).som).toBe(0.3)
  })

  it('kortingsregel mét negatieve btw telt gewoon mee', () => {
    const u = toetsRegelsom({ netto: [100, -56.44], btw: [21, -11.85], totaalIncl: 52.71, totaalExcl: null, factuurBtw: null })
    expect(u.som).toBe(52.71)
    expect(u.sluitAan).toBe(true)
  })

  it('geen regels / netto leeg / geen totaal zijn eigen redenen', () => {
    expect(toetsRegelsom({ netto: [], btw: [], totaalIncl: 1, totaalExcl: null, factuurBtw: null }).reden).toBe('geen_regels')
    expect(toetsRegelsom({ netto: [null], btw: [null], totaalIncl: 1, totaalExcl: 1, factuurBtw: null }).reden).toBe('netto_ontbreekt')
    expect(toetsRegelsom({ netto: [1], btw: [null], totaalIncl: null, totaalExcl: null, factuurBtw: null }).reden).toBe('geen_totaal')
  })
})
