import { describe, expect, it } from 'vitest'
import { accorderingOvergeslagenTijdlijnTekst, isAccorderingOvergeslagenNotitie } from './accorderingOvergeslagenTijdlijn'

// Blok 4 bundel 08-09: tijdlijn-notitie van de backend (registreer_accordering_overgeslagen) leesbaar maken.
describe('accorderingOvergeslagenTijdlijn', () => {
  const detail = {
    accordering_overgeslagen: {
      reden: 'intercompany',
      vendor_id: '33333333-0000-0000-0000-000000000001',
      leverancier_naam: 'Universal Nederland B.V.',
      boek_cyclus: 0,
    },
  }

  it('herkent alleen de eigen sleutel', () => {
    expect(isAccorderingOvergeslagenNotitie(detail)).toBe(true)
    expect(isAccorderingOvergeslagenNotitie({ boekvoorstel_prefill: {} })).toBe(false)
    expect(isAccorderingOvergeslagenNotitie({ accordering_overgeslagen: null })).toBe(false)
  })

  it('tekst mét leveranciersnaam', () => {
    expect(accorderingOvergeslagenTijdlijnTekst(detail)).toBe(
      'Intercompany — klant-accordering overgeslagen (leveranciersregel): Universal Nederland B.V.',
    )
  })

  it('valt terug op vendor-id zonder naam, en op de reden zonder bekende vertaling', () => {
    expect(
      accorderingOvergeslagenTijdlijnTekst({ accordering_overgeslagen: { reden: 'intercompany', vendor_id: 'abc' } }),
    ).toBe('Intercompany — klant-accordering overgeslagen (leveranciersregel): abc')
    expect(accorderingOvergeslagenTijdlijnTekst({ accordering_overgeslagen: {} })).toBe(
      'leveranciersregel — klant-accordering overgeslagen (leveranciersregel)',
    )
  })
})
