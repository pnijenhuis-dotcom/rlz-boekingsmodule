import { describe, expect, it } from 'vitest'
import type { MutatieDto } from './bankApi'
import { cijferkern, filterMutaties, mutatieMatcht, normaliseerTekst, totaalCenten } from './bankZoek'

/** Blok A 16-09: zoekveld bankscherm — naam, IBAN, omschrijving, bedrag met/zonder punt-komma, nummers in omschrijving en
 * voorstel-tekst (open post, batch-posten, RLZ-koppelingen), AND over termen. */

function m(over: Partial<MutatieDto>): MutatieDto {
  return {
    id: 'x',
    boekdatum: '2026-09-15',
    bedrag: '-560925.88',
    open_bedrag: '-40723.85',
    tegenpartij_naam: 'Bouwadvies Oost Nederland B.V.',
    omschrijving: 'TOTAAL 14 VZ betaalkenmerk: PREF',
    tegenrekening_iban: 'NL04INGB0117244236',
    voorstel: { soort: 'handmatig', kleur: 'oranje', bron: 'handmatig', reden: '', payment_item_id: null, open_post: null, regel_id: null, regels: [] },
    afletter_opdracht: null,
    regel_voorstel: null,
    ...over,
  }
}

describe('bankZoek', () => {
  it('normaliseert en haalt cijferkernen', () => {
    expect(normaliseerTekst('  Élan   B.V. ')).toBe('elan b.v.')
    expect(cijferkern('560.925,88')).toBe('56092588')
    expect(cijferkern('NL04 INGB 0117 2442 36')).toBe('040117244236')
  })

  it('matcht op naam (deel, accent-ongevoelig), IBAN met/zonder spaties en omschrijving', () => {
    expect(mutatieMatcht(m({}), 'bouwadvies')).toBe(true)
    expect(mutatieMatcht(m({}), 'OOST nederland')).toBe(true)
    expect(mutatieMatcht(m({}), 'NL04 INGB 0117')).toBe(true)
    expect(mutatieMatcht(m({}), 'PREF')).toBe(true)
    expect(mutatieMatcht(m({}), 'zuilichem')).toBe(false)
  })

  it('matcht bedragen met of zonder punt/komma en het open bedrag', () => {
    expect(mutatieMatcht(m({}), '560925,88')).toBe(true)
    expect(mutatieMatcht(m({}), '560.925,88')).toBe(true)
    expect(mutatieMatcht(m({}), '40723.85')).toBe(true)
    expect(mutatieMatcht(m({}), '385000')).toBe(false)
  })

  it('matcht factuur-/boekstuknummers in de voorstel-tekst (open post, batch-posten, RLZ-koppelingen), genormaliseerd', () => {
    const met = m({
      voorstel: {
        soort: 'batch',
        kleur: 'groen',
        bron: 'betaalbatch RLZEE_CT_1, 2 facturen',
        reden: '',
        payment_item_id: null,
        open_post: null,
        regel_id: null,
        regels: [],
        batch: {
          sleutel: 'RLZEE_CT_20260915_101500_4471_0001',
          aantal: 2,
          som: '40723.85',
          open_bedrag: '-40723.85',
          verschil: '0.00',
          sluit: true,
          posten: [
            { id: 'p1', bedrag: '-40000.00', referentie: '700', referentie2: null, rlz_document_id: null, boekstuknummer: 'RLZ-04-00000497', klantreferentie: '92953485' },
            { id: 'p2', bedrag: '-723.85', referentie: '701', referentie2: null, rlz_document_id: null, klantreferentie: '9295 3490' },
          ],
        },
      },
      rlz_koppelingen: [{ document_id: 'd', boekstuknummer: 'RLZ-04-00000123', referentie: 'F-2026-0642', bedrag: '12.00', document_type: 1, omschrijving: null }],
    })
    expect(mutatieMatcht(met, '92953485')).toBe(true)
    expect(mutatieMatcht(met, '92953490')).toBe(true) // "9295 3490" ≡ "92953490"
    expect(mutatieMatcht(met, 'RLZ-04-00000497')).toBe(true)
    expect(mutatieMatcht(met, '0000123')).toBe(true)
    expect(mutatieMatcht(met, '20260642')).toBe(true) // F-2026-0642 als cijferkern
    expect(mutatieMatcht(met, 'RLZEE_CT_20260915')).toBe(true)
    // AND over termen.
    expect(mutatieMatcht(met, 'bouwadvies 92953485')).toBe(true)
    expect(mutatieMatcht(met, 'bouwadvies 99999999')).toBe(false)
  })

  it('filterMutaties en totaalCenten (open bedrag, gehele centen)', () => {
    const lijst = [m({ id: 'a' }), m({ id: 'b', tegenpartij_naam: 'Heren van Zuilichem', bedrag: '385000.00', open_bedrag: '385000.00' })]
    expect(filterMutaties(lijst, '').map((x) => x.id)).toEqual(['a', 'b'])
    expect(filterMutaties(lijst, 'zuilichem').map((x) => x.id)).toEqual(['b'])
    expect(totaalCenten(filterMutaties(lijst, 'zuilichem'))).toBe(38500000)
    expect(totaalCenten([m({ bedrag: '0.10', open_bedrag: '0.10' }), m({ bedrag: '0.20', open_bedrag: null })])).toBe(30)
  })
})
