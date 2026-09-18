/** Beoordelen › Urenstaten — kolomminima uit één bron (zelfde regel als gebruikersKolommen.test). */
import { describe, expect, it } from 'vitest'
import { BEOORDELEN_KOLOMMEN, beschikbareBreedte, minimaleBeoordelenBreedte } from './beoordelenKolommen'

describe('beoordelenKolommen — de bron', () => {
  it('elke kolom heeft een geheel px-minimum ≥ 80 (acties ≥ 150: één knop + ⋯), unieke sleutels, acties laatst', () => {
    const sleutels = new Set<string>()
    for (const k of BEOORDELEN_KOLOMMEN) {
      expect(Number.isInteger(k.minPx), k.sleutel).toBe(true)
      expect(k.minPx, `${k.sleutel} te smal`).toBeGreaterThanOrEqual(k.sleutel === 'acties' ? 150 : 80)
      expect(sleutels.has(k.sleutel)).toBe(false)
      sleutels.add(k.sleutel)
    }
    expect(BEOORDELEN_KOLOMMEN.at(-1)?.sleutel).toBe('acties')
  })
  it('de som past op 1440 zonder interne scroll (kliktest-breedte Peter); op 1170 = interne scroll, nooit implosie', () => {
    const som = minimaleBeoordelenBreedte()
    expect(som).toBe(BEOORDELEN_KOLOMMEN.reduce((s, k) => s + k.minPx, 0))
    expect(som).toBeLessThanOrEqual(beschikbareBreedte(1440))
    expect(som).toBeGreaterThan(beschikbareBreedte(1170) - 400) // realistische tabel, geen speelgoedbreedtes
  })
})
