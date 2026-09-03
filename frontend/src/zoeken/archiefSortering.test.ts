import { describe, expect, it } from 'vitest'
import {
  archiefSorteringNaarParam,
  archiefSorteringUitParam,
  volgendeArchiefSortering,
} from './archiefSortering'

describe('archiefSortering — kolomkop-conventie punt 21 voor het kantoorbrede archief', () => {
  it('klik: oplopend → aflopend → uit', () => {
    const a = volgendeArchiefSortering(null, 'bedrag')
    expect(a).toEqual({ kolom: 'bedrag', richting: 'asc' })
    const d = volgendeArchiefSortering(a, 'bedrag')
    expect(d).toEqual({ kolom: 'bedrag', richting: 'desc' })
    expect(volgendeArchiefSortering(d, 'bedrag')).toBeNull()
    // Andere kolom aanklikken begint altijd oplopend.
    expect(volgendeArchiefSortering(d, 'leverancier')).toEqual({ kolom: 'leverancier', richting: 'asc' })
  })

  it('URL-parameter heen en terug; onbekende kolom = geen sortering', () => {
    expect(archiefSorteringNaarParam({ kolom: 'administratie', richting: 'desc' })).toBe('administratie:desc')
    expect(archiefSorteringNaarParam(null)).toBeNull()
    expect(archiefSorteringUitParam('boekstuk:desc')).toEqual({ kolom: 'boekstuk', richting: 'desc' })
    expect(archiefSorteringUitParam('boekstuk')).toEqual({ kolom: 'boekstuk', richting: 'asc' })
    expect(archiefSorteringUitParam('status:asc')).toBeNull()
    expect(archiefSorteringUitParam(null)).toBeNull()
  })
})
