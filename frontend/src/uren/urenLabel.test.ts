/** Blok A feedback uitvoerder 18-09: m² optioneel — een regel zonder m² toont alleen uren (geen "· —", geen "· 0 m²"). */
import { describe, expect, it } from 'vitest'
import { doorfacturerenLabel, urenLabel, weekTotaalLabel } from './urenApi'

describe('urenLabel / weekTotaalLabel (18-09 blok A)', () => {
  it('zonder m² alleen de uren', () => {
    expect(urenLabel('8', null)).toBe('8,0 u')
    expect(urenLabel('8', undefined)).toBe('8,0 u')
    expect(urenLabel('8', '0')).toBe('8,0 u')
    expect(urenLabel('8', '')).toBe('8,0 u')
  })
  it('mét m² de combinatie', () => {
    expect(urenLabel('8', '120')).toBe('8,0 u · 120 m²')
    expect(weekTotaalLabel('22.5', '215')).toBe('22,5 u · 215 m²')
    expect(weekTotaalLabel('22.5', '0')).toBe('22,5 u')
  })
  it('doorfactureren-labels', () => {
    expect(doorfacturerenLabel(true)).toBe('Doorfactureren')
    expect(doorfacturerenLabel(false)).toBe('Niet doorfactureren')
  })
})
