import { describe, expect, it } from 'vitest'
import { onderwegTekst, verbruikSegmenten } from './verbruikPresentatie'
import { formatBedrag } from '../werkvoorraad/format'

const plat = (t: string) => t.replace(/\u00a0/g, ' ')

// Peter 18-09 (casus Bouwadvies): drie segmenten geboekt / onderweg / eigen en de zin "waarvan … nog niet geboekt".

describe('verbruikSegmenten', () => {
  it('verdeelt naar verhouding en blijft samen ≤ 100', () => {
    const seg = verbruikSegmenten({ geboekt: '25000.00', onderweg: '25000.00', eigen: '25000.00', totaal: '100000.00' })
    expect(seg).toEqual({ geboekt: 25, onderweg: 25, eigen: 25 })
    const vol = verbruikSegmenten({ geboekt: '80000.00', onderweg: '30000.00', eigen: '10000.00', totaal: '100000.00' })
    expect(vol.geboekt).toBe(80)
    expect(vol.onderweg).toBe(20)
    expect(vol.eigen).toBe(0)
  })
  it('zonder bruikbaar totaal is alles 0', () => {
    expect(verbruikSegmenten({ geboekt: '10', totaal: null })).toEqual({ geboekt: 0, onderweg: 0, eigen: 0 })
    expect(verbruikSegmenten({ geboekt: '10', totaal: '0' })).toEqual({ geboekt: 0, onderweg: 0, eigen: 0 })
  })
})

describe('onderwegTekst', () => {
  it('is leeg zonder onderweg en noemt anders bedrag, aantal en stand', () => {
    expect(onderwegTekst('0.00', 0, 0, formatBedrag)).toBe('')
    expect(onderwegTekst(null, 2, 0, formatBedrag)).toBe('')
    expect(plat(onderwegTekst('20000.00', 1, 1, formatBedrag))).toBe(
      'waarvan € 20.000,00 nog niet geboekt (1 factuur ter accordering)',
    )
    expect(plat(onderwegTekst('25000.00', 2, 1, formatBedrag))).toBe(
      'waarvan € 25.000,00 nog niet geboekt (2 facturen in behandeling)',
    )
  })
})
