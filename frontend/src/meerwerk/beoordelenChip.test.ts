import { describe, expect, it } from 'vitest'
import { beoordelenChip, beoordelenUrl } from './beoordelenChip'

describe('beoordelenChip — chip-tekst = som van de tabs (bug 18-09)', () => {
  it('14 ingediende weekstaten en 0 meerwerk = "14 urenstaten te beoordelen" → tab urenstaten (de casus Universal)', () => {
    const chip = beoordelenChip({ urenstaten_wachten_op_keuring: 14, meerwerk_te_beoordelen: 0 })
    expect(chip).toEqual({ aantal: 14, tekst: '14 urenstaten te beoordelen', tab: 'urenstaten' })
    expect(beoordelenUrl('adm-1', chip!.tab)).toBe('/meerwerk?administratie=adm-1&tab=urenstaten')
  })
  it('beide tellers → "N urenstaten · M meerwerk te beoordelen"; alleen meerwerk → tab meerwerk; enkelvoud', () => {
    expect(beoordelenChip({ urenstaten_wachten_op_keuring: 3, meerwerk_te_beoordelen: 2 })).toEqual({
      aantal: 5,
      tekst: '3 urenstaten · 2 meerwerk te beoordelen',
      tab: 'urenstaten',
    })
    expect(beoordelenChip({ urenstaten_wachten_op_keuring: 0, meerwerk_te_beoordelen: 2 })).toEqual({
      aantal: 2,
      tekst: '2 meerwerk te beoordelen',
      tab: 'meerwerk',
    })
    expect(beoordelenChip({ urenstaten_wachten_op_keuring: 1, meerwerk_te_beoordelen: 0 })?.tekst).toBe('1 urenstaat te beoordelen')
  })
  it('niets te beoordelen = geen chip (toon-regel); "nog doorbelasten" telt bewust niet mee — dat is geen beoordeling', () => {
    expect(beoordelenChip({ urenstaten_wachten_op_keuring: 0, meerwerk_te_beoordelen: 0 })).toBeNull()
  })
})
