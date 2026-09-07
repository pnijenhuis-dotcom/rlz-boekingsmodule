import { describe, expect, it } from 'vitest'
import { isPrefillAutosaveNotitie, prefillAutosaveTijdlijnTekst } from './prefillAutosaveTijdlijn'

describe('prefillAutosaveTijdlijn (blok A10 07-09)', () => {
  it('herkent alleen een notitie mét snapshot-object', () => {
    expect(isPrefillAutosaveNotitie({ boekvoorstel_prefill: { triggers: [] } })).toBe(true)
    expect(isPrefillAutosaveNotitie({ boekvoorstel_prefill: null })).toBe(false)
    expect(isPrefillAutosaveNotitie({ veldvoorstel: {} })).toBe(false)
  })

  it('benoemt de bronnen uit de triggers en het aantal regels', () => {
    const tekst = prefillAutosaveTijdlijnTekst({
      boekvoorstel_prefill: {
        triggers: ['grootboek regel 1: leverancier_geheugen', 'btw regel 2: standaard', 'grootboek regel 2: ai'],
        regels: [{}, {}],
      },
    })
    expect(tekst).toBe(
      'Voorstel automatisch vooringevuld uit leverancier-geheugen en standaard btw van de administratie — 2 regels opgeslagen; controleer en pas aan waar nodig',
    )
  })

  it('één regel en onbekende triggers geven een nette tekst zonder bronopsomming', () => {
    expect(prefillAutosaveTijdlijnTekst({ boekvoorstel_prefill: { triggers: ['iets: onbekend'], regels: [{}] } })).toBe(
      'Voorstel automatisch vooringevuld — 1 regel opgeslagen; controleer en pas aan waar nodig',
    )
  })
})
