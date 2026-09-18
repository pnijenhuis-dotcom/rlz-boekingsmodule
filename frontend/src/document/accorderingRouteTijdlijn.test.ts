import { describe, expect, it } from 'vitest'
import { accorderingRouteTijdlijnTekst, isAccorderingRouteNotitie } from './accorderingRouteTijdlijn'

describe('accorderingRouteTijdlijn (leveranciersroute bovenop, 18-09)', () => {
  it('herkent alleen een gevulde route_omschrijving', () => {
    expect(isAccorderingRouteNotitie({ route_omschrijving: 'route: leveranciersroute Route Q' })).toBe(true)
    expect(isAccorderingRouteNotitie({ route_omschrijving: '' })).toBe(false)
    expect(isAccorderingRouteNotitie({ leverancier_route: 'Route Q' })).toBe(false)
  })

  it('toont de servertekst met hoofdletter', () => {
    expect(
      accorderingRouteTijdlijnTekst({
        route_omschrijving: 'route: gewoon + extra laag Sophia ná de laatste laag (leveranciersroute Route Q)',
      }),
    ).toBe('Route: gewoon + extra laag Sophia ná de laatste laag (leveranciersroute Route Q)')
  })
})
