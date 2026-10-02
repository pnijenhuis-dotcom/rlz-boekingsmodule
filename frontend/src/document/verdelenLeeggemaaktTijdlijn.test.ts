import { describe, expect, it } from 'vitest'
import { isVerdelenLeeggemaaktNotitie, verdelenLeeggemaaktTijdlijnTekst } from './verdelenLeeggemaaktTijdlijn'

describe('verdelenLeeggemaaktTijdlijn (punt 5 Boeken prettig 1, 02-10)', () => {
  it('herkent de notitie en noemt aantal regels + sleutel', () => {
    const detail = { verdelen_leeggemaakt: { regels: 2, sleutel: 'omzet_maand' } }
    expect(isVerdelenLeeggemaaktNotitie(detail)).toBe(true)
    expect(verdelenLeeggemaaktTijdlijnTekst(detail)).toBe(
      'Verdelen over projecten: project van 2 regels leeggemaakt — het hele bedrag verdeeld via de projectverdeling (pro rato omzet (maand van de factuurdatum))',
    )
  })
  it('één regel zonder sleutel', () => {
    expect(verdelenLeeggemaaktTijdlijnTekst({ verdelen_leeggemaakt: { regels: 1 } })).toBe(
      'Verdelen over projecten: project van 1 regel leeggemaakt — het hele bedrag verdeeld via de projectverdeling',
    )
    expect(isVerdelenLeeggemaaktNotitie({ kop_doorgezet: {} })).toBe(false)
  })
})
