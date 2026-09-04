import { describe, expect, it } from 'vitest'
import { isKantoorRol, isVeldRol, magProjectAanmaken } from './rollen'

describe('rol-allowlists (spiegel van backend/app/auth/rollen.py)', () => {
  it('kantoorrollen vs veldrollen', () => {
    expect(isKantoorRol('beheerder')).toBe(true)
    expect(isKantoorRol('boekhouding')).toBe(true)
    expect(isKantoorRol('boekhouding_projecten')).toBe(true)
    expect(isKantoorRol('zzper')).toBe(false)
    expect(isKantoorRol('klant_accordeur')).toBe(false)
    expect(isVeldRol('detacheerder')).toBe(true)
    expect(isVeldRol('beheerder')).toBe(false)
  })

  it('magProjectAanmaken: alle drie de kantoorrollen (besluit Peter 04-09), niemand anders', () => {
    expect(magProjectAanmaken('beheerder')).toBe(true)
    expect(magProjectAanmaken('boekhouding_projecten')).toBe(true)
    expect(magProjectAanmaken('boekhouding')).toBe(true)
    for (const rol of ['klant_accordeur', 'zzper', 'uitvoerder', 'detacheerder', 'nieuwe_rol', '']) {
      expect(magProjectAanmaken(rol)).toBe(false)
    }
    expect(magProjectAanmaken(null)).toBe(false)
  })
})
