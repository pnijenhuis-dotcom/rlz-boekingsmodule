import { describe, expect, it } from 'vitest'
import { kaartPastInFilter, parseUrenFilter, urenKort, weekUrenTekst } from './planningApi'

// 15-09 (Peter/Haci): pure helpers voor de urenstatus in het planningsgrid.
describe('urenstatus-helpers', () => {
  it('urenKort: uren en m² kort, anders het statuslabel', () => {
    expect(urenKort({ uren_status: 'ingevuld', uren: '8.00', m2: '42.00' })).toBe('8 u · 42 m²')
    expect(urenKort({ uren_status: 'ingevuld', uren: '7.5', m2: '0' })).toBe('7,5 u')
    expect(urenKort({ uren_status: 'geen', uren: null, m2: null })).toBe('geen uren')
    expect(urenKort({})).toBe('geen uren')
    expect(urenKort({ uren_status: 'vraag', uren: null })).toBe('afgekeurd / vraag')
  })

  it('weekUrenTekst: nullen vallen weg, alles nul = null', () => {
    expect(weekUrenTekst({ ingevuld_uren: '24', gekeurd_uren: '16', open_aantal: 2, zonder_uren_aantal: 0 })).toBe(
      '24 u ingevuld · 16 u gekeurd · 2 open',
    )
    expect(weekUrenTekst({ ingevuld_uren: '0', gekeurd_uren: '0', open_aantal: 0, zonder_uren_aantal: 3 })).toBe('3 zonder uren')
    expect(weekUrenTekst({ ingevuld_uren: '0', gekeurd_uren: '0', open_aantal: 0, zonder_uren_aantal: 0 })).toBeNull()
    expect(weekUrenTekst(undefined)).toBeNull()
  })

  it('filter uit de URL en per kaartje', () => {
    expect(parseUrenFilter('zonder')).toBe('zonder')
    expect(parseUrenFilter('ongekeurd')).toBe('ongekeurd')
    expect(parseUrenFilter('x')).toBe('alle')
    expect(parseUrenFilter(null)).toBe('alle')
    const gekeurd = { gebruiker_id: 'a', naam: null, rol: 'zzper', dagdeel: 'heel' as const, uren_status: 'gekeurd' as const }
    const geen = { ...gekeurd, uren_status: 'geen' as const }
    const oud = { gebruiker_id: 'b', naam: null, rol: 'zzper', dagdeel: 'heel' as const }
    expect(kaartPastInFilter(gekeurd, 'zonder')).toBe(false)
    expect(kaartPastInFilter(geen, 'zonder')).toBe(true)
    expect(kaartPastInFilter(oud, 'zonder')).toBe(true)
    expect(kaartPastInFilter(gekeurd, 'ongekeurd')).toBe(false)
    expect(kaartPastInFilter(geen, 'ongekeurd')).toBe(true)
    expect(kaartPastInFilter(gekeurd, 'alle')).toBe(true)
  })
})
