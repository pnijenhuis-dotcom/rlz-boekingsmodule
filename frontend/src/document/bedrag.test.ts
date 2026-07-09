import { describe, expect, it } from 'vitest'
import { bedragAlsGetal, normaliseerBedrag } from './bedrag'

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
