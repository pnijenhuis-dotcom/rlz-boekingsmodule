import { describe, expect, it } from 'vitest'
import { schatM2, type ProductDto } from './transportApi'

/* m²-schatting client-side (weergave tijdens het typen; de server rekent bindend met dezelfde
 * formule Σ(aantal × lengte) / 4,6 uit Peters bestellijst): het voorbeeld #262651 geeft 331,09 m². */
function product(id: string, lengte: string | null): ProductDto {
  return { id, leverancier_id: 'l', categorie_id: 'c', categorie_naam: 'Tubelock', bundel: 'steiger', naam: id, verpakking: null, eenheid: 'stuks', m2_lengte: lengte, volgorde: 0, actief: true, nummer: '1.1' }
}

describe('schatM2', () => {
  it('rekent Peters voorbeeld na en negeert producten zonder lengte', () => {
    const producten = new Map<string, ProductDto>([
      ['b2', product('b2', '2')],
      ['b28', product('b28', '2.8')],
      ['b3', product('b3', '3')],
      ['b4', product('b4', '4')],
      ['uk', product('uk', '1.4')],
      ['us', product('us', '2')],
      ['anker', product('anker', '1')],
      ['kruis', product('kruis', null)],
    ])
    expect(schatM2({ b2: 50, b28: 0, b3: 150, b4: 150, uk: 45, us: 150, anker: 10, kruis: 1000 }, producten)).toBe(331.09)
    expect(schatM2({}, producten)).toBe(0)
    expect(schatM2({ b4: 115 }, producten)).toBe(100)
  })
})
