import { describe, expect, it } from 'vitest'
import { crediteurSuggesties, naamGelijkenis, normaliseerNaam } from './crediteurSuggesties'

describe('normaliseerNaam', () => {
  it('strijkt rechtsvorm-ruis en leestekens glad (zelfde regels als de backend-controlelaag)', () => {
    expect(normaliseerNaam('Jansen Bouw B.V.')).toBe('jansen bouw')
    expect(normaliseerNaam('JANSEN  BOUW BV')).toBe('jansen bouw')
    expect(normaliseerNaam('Confide Holding N.V.')).toBe('confide')
  })
})

describe('naamGelijkenis', () => {
  it('is 1 voor genormaliseerd-gelijke namen en 0 voor lege input', () => {
    expect(naamGelijkenis('Confide BV', 'Confide B.V.')).toBe(1)
    expect(naamGelijkenis('', 'Confide')).toBe(0)
  })

  it('scoort een spellingsvariant hoger dan een andere naam', () => {
    const variant = naamGelijkenis('Bouwmaat Nederland', 'Bouwmaat Nederland B.V.')
    const anders = naamGelijkenis('Bouwmaat Nederland', 'Technische Unie')
    expect(variant).toBeGreaterThan(0.8)
    expect(anders).toBeLessThan(0.3)
  })
})

describe('crediteurSuggesties', () => {
  const opties = [
    { id: '1', label: 'Bouwmaat Nederland B.V.' },
    { id: '2', label: 'Technische Unie' },
    { id: '3', label: 'Bouwmaat Nederland Noord' },
    { id: '4', label: 'Bouwmaat Ned.' },
    { id: '5', label: 'Bouwmaat Nederland Zuid' },
  ]

  it('geeft alleen plausibele kandidaten, best passende eerst, maximaal drie', () => {
    const suggesties = crediteurSuggesties('Bouwmaat Nederland BV', opties)
    expect(suggesties.length).toBeLessThanOrEqual(3)
    expect(suggesties[0].optie.id).toBe('1')
    expect(suggesties.map((s) => s.optie.id)).not.toContain('2')
  })

  it('geeft niets bij een naam die nergens op lijkt', () => {
    expect(crediteurSuggesties('Zeefdruk Atelier Willemijn', opties)).toEqual([])
  })
})
