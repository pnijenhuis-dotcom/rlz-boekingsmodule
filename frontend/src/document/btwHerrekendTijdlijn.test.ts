import { describe, expect, it } from 'vitest'
import { btwHerrekendTijdlijnTekst, isBtwHerrekendNotitie } from './btwHerrekendTijdlijn'

/** FV-09 (25-09): tijdlijntekst per aanleiding — `tarief` (18-09, ook zonder het veld = oude notitie) en `netto`. */
describe('btwHerrekendTijdlijn', () => {
  it('oude notitie zonder aanleiding = tarief', () => {
    const detail = { btw_herrekend: [{ regel: 1, btw_van: '20.24', btw_naar: '0.00', netto_van: '96.36', netto_naar: '116.60', in_kosten: true }] }
    expect(isBtwHerrekendNotitie(detail)).toBe(true)
    expect(btwHerrekendTijdlijnTekst(detail)).toBe(
      'Btw herrekend uit tarief — regel 1: btw € 20,24 → € 0,00 (btw in de kosten: netto € 96,36 → € 116,60)',
    )
  })
  it('aanleiding netto = "Btw herrekend — regel n: netto … , btw … (netto gewijzigd)"', () => {
    const detail = {
      btw_herrekend: [{ regel: 1, aanleiding: 'netto', btw_van: '20.24', btw_naar: '21.00', netto_van: '96.36', netto_naar: '100.00', in_kosten: false }],
    }
    expect(btwHerrekendTijdlijnTekst(detail)).toBe('Btw herrekend — regel 1: netto € 96,36 → € 100,00, btw € 20,24 → € 21,00 (netto gewijzigd)')
  })
  it('beide aanleidingen in één notitie = twee zinnen', () => {
    const detail = {
      btw_herrekend: [
        { regel: 1, aanleiding: 'tarief', btw_van: '20.24', btw_naar: '8.67', netto_van: '96.36', netto_naar: '96.36', in_kosten: false },
        { regel: 2, aanleiding: 'netto', btw_van: '2.10', btw_naar: '4.20', netto_van: '10.00', netto_naar: '20.00', in_kosten: false },
      ],
    }
    expect(btwHerrekendTijdlijnTekst(detail)).toBe(
      'Btw herrekend uit tarief — regel 1: btw € 20,24 → € 8,67 · Btw herrekend — regel 2: netto € 10,00 → € 20,00, btw € 2,10 → € 4,20 (netto gewijzigd)',
    )
  })
})
