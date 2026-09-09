import { describe, expect, it } from 'vitest'
import { accorderingHerberekendTekst } from './accorderingHerberekendTijdlijn'

describe('accorderingHerberekendTekst — tijdlijnregel bundel 09-09 blok 2', () => {
  it('N akkoord(en) behouden, laag X opnieuw aangevraagd', () => {
    expect(
      accorderingHerberekendTekst({ akkoorden_behouden: 1, akkoorden_vervallen: 0, opnieuw_aangevraagd: [2], alles_akkoord: false }),
    ).toBe('Accordering herberekend (configuratie gewijzigd): 1 akkoord behouden, laag 2 opnieuw aangevraagd')
  })

  it('meervoud + vervallen akkoorden + meerdere lagen', () => {
    expect(
      accorderingHerberekendTekst({ akkoorden_behouden: 2, akkoorden_vervallen: 1, opnieuw_aangevraagd: [2, 3] }),
    ).toBe('Accordering herberekend (configuratie gewijzigd): 2 akkoorden behouden, 1 akkoord vervallen, lagen 2, 3 opnieuw aangevraagd')
  })

  it('alles gedekt → boeken gestart', () => {
    expect(accorderingHerberekendTekst({ akkoorden_behouden: 1, opnieuw_aangevraagd: [], alles_akkoord: true })).toBe(
      'Accordering herberekend (configuratie gewijzigd): 1 akkoord behouden, alle lagen gedekt — boeken gestart',
    )
  })

  it('onbekend detail = leesbare terugval', () => {
    expect(accorderingHerberekendTekst(true)).toBe('Accordering herberekend (configuratie gewijzigd): 0 akkoorden behouden')
  })
})
