// 22-09 (Peter, casus Bouwadvies): een wachtrij-item dat intussen buiten de module geboekt is telt NIET als "te
// accorderen" maar zichtbaar apart als "wacht op kantoor" — nooit stil weg, nooit in de oudste-wacht-regel.
import { describe, expect, it } from 'vitest'
import type { WachtrijItemDto } from './accordeurApi'
import { administratiesMetWerk, isWachtOpKantoor, wachtOpKantoorChipTekst } from './administraties'

function item(over: Partial<WachtrijItemDto>): WachtrijItemDto {
  return {
    document_id: 'd',
    administratie_id: 'a1',
    administratie_naam: 'Bouwadvies Oost Nederland B.V.',
    leverancier_naam: 'Beter Assemblage B.V.',
    referentie: 'F/2026/01235',
    factuurdatum: '2026-08-26',
    totaalbedrag: '173.84',
    aangeboden_op: '2026-09-16T09:13:00Z',
    laag_volgnummer: 3,
    boeking_omschrijving: null,
    staande_regel_kandidaat: false,
    ...over,
  }
}
const EXTERN = { boekstuk: 'RLZ-04-00000518', systeem: 'Reeleezee', stand: 'geboekt', tekst: 'Al geboekt in Reeleezee (RLZ-04-00000518) — kantoor beoordeelt; akkoord niet nodig' }

describe('administratiesMetWerk — wacht op kantoor (22-09)', () => {
  it('telt extern geboekte items apart en niet als te accorderen; oudste-wacht kijkt alleen naar echt werk', () => {
    const [s] = administratiesMetWerk(
      [
        item({ document_id: 'd1', extern_geboekt: EXTERN, aangeboden_op: '2026-09-01T09:00:00Z' }),
        item({ document_id: 'd2', aangeboden_op: '2026-09-16T09:00:00Z' }),
      ],
      [],
    )
    expect(s.teAccorderen).toBe(1)
    expect(s.wachtOpKantoor).toBe(1)
    expect(s.oudsteWacht).toBe('2026-09-16T09:00:00Z')
  })

  it('een administratie met alléén wacht-op-kantoor-items blijft een kaart (nooit stil), zonder te-accorderen-teller', () => {
    const [s] = administratiesMetWerk([item({ document_id: 'd1', extern_geboekt: EXTERN })], [])
    expect(s.teAccorderen).toBe(0)
    expect(s.wachtOpKantoor).toBe(1)
    expect(s.oudsteWacht).toBeNull()
  })

  it('predikaat + chiptekst', () => {
    expect(isWachtOpKantoor(item({ extern_geboekt: EXTERN }))).toBe(true)
    expect(isWachtOpKantoor(item({ extern_geboekt: null }))).toBe(false)
    expect(isWachtOpKantoor(item({}))).toBe(false)
    expect(wachtOpKantoorChipTekst(1)).toBe('1 wacht op kantoor')
    expect(wachtOpKantoorChipTekst(3)).toBe('3 wachten op kantoor')
  })
})
