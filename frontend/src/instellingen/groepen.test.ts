import { describe, expect, it } from 'vitest'
import { codeGeldig, codeVoorstel, groepLabel } from './groepen'

/** Blok 8 run 11-09: het code-voorstel is een spiegel van `app/beheer/groepen.py::code_voorstel` — dezelfde
 * voorbeelden als tests/beheer/test_groepen.py::TestCodeVoorstel. */
describe('codeVoorstel', () => {
  it.each([
    ['Kempen groep', 'KEMPENGROEP'],
    ['Jansen & Zn.', 'JANSENZN'],
    ['Café Ünïcode 2026', 'CAFEUNICODE2'],
    ['Vastgoedgroep Nederland Holding', 'VASTGOEDGROE'],
    ['X', ''],
  ])('%s → %s', (naam, verwacht) => {
    expect(codeVoorstel(naam)).toBe(verwacht)
  })

  it('codeGeldig volgt het serverpatroon (2–12 hoofdletters/cijfers)', () => {
    expect(codeGeldig('KG')).toBe(true)
    expect(codeGeldig('KEMPENGROEP')).toBe(true)
    expect(codeGeldig('K')).toBe(false)
    expect(codeGeldig('k-g')).toBe(false)
    expect(codeGeldig('KEMPENGROEPNL')).toBe(false)
  })

  it('groepLabel markeert een gearchiveerde groep', () => {
    expect(groepLabel({ naam: 'Kempen groep', actief: true })).toBe('Kempen groep')
    expect(groepLabel({ naam: 'Kempen groep', actief: false })).toBe('Kempen groep (gearchiveerd)')
  })
})
