import { describe, expect, it } from 'vitest'
import { bedragAlsGetal, berekenBtwBedrag, normaliseerBedrag } from './bedrag'

describe('normaliseerBedrag', () => {
  it('laat al-genormaliseerd punt-decimaal ongewijzigd', () => {
    expect(normaliseerBedrag('1234.56')).toBe('1234.56')
    expect(normaliseerBedrag('121.00')).toBe('121.00')
  })

  it('normaliseert NL-notatie met duizendtal-punt naar punt-decimaal', () => {
    expect(normaliseerBedrag('1.234,56')).toBe('1234.56')
  })

  it('normaliseert NL-notatie zonder duizendtal-punt naar punt-decimaal', () => {
    expect(normaliseerBedrag('121,00')).toBe('121.00')
  })

  it('meerdere duizendtal-punten worden allemaal verwijderd', () => {
    expect(normaliseerBedrag('1.234.567,89')).toBe('1234567.89')
  })

  it('laat lege invoer ongewijzigd (leeg)', () => {
    expect(normaliseerBedrag('')).toBe('')
    expect(normaliseerBedrag('   ')).toBe('')
  })

  it('trimt omliggende spaties', () => {
    expect(normaliseerBedrag('  121,00  ')).toBe('121.00')
  })
})

describe('bedragAlsGetal', () => {
  it('parseert genormaliseerde bedragen naar een getal', () => {
    expect(bedragAlsGetal('1.234,56')).toBe(1234.56)
    expect(bedragAlsGetal('100.00')).toBe(100)
  })

  it('geeft null voor leeg of onherkenbare invoer', () => {
    expect(bedragAlsGetal('')).toBeNull()
    expect(bedragAlsGetal('abc')).toBeNull()
  })
})

describe('berekenBtwBedrag', () => {
  it('berekent netto x percentage', () => {
    expect(berekenBtwBedrag(100, 0.21)).toBe(21)
    expect(berekenBtwBedrag(23.23, 0)).toBe(0)
  })

  it('rondt af op 2 decimalen', () => {
    expect(berekenBtwBedrag(10.1, 0.21)).toBe(2.12) // 2.121 -> 2.12
    expect(berekenBtwBedrag(33.33, 0.09)).toBe(3.0) // 2.9997 -> 3.00
  })

  it('werkt met een laag tarief en negatieve bedragen (creditnota)', () => {
    expect(berekenBtwBedrag(-50, 0.09)).toBe(-4.5)
  })
})
