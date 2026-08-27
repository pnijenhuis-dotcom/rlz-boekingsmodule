// BV-openingsscherm (27-08): pure afleidingen — groepering per administratie, volgorde, de
// "één met werk = automatisch die"-regel en de oudste-wacht-tekst.
import { describe, expect, it } from 'vitest'
import type { AccordeurVraagDto, WachtrijItemDto } from './accordeurApi'
import { administratiesMetWerk, kiesActieveAdministratie, vragenChipTekst, wachtSindsTekst } from './administraties'

function item(over: Partial<WachtrijItemDto>): WachtrijItemDto {
  return {
    document_id: 'd',
    administratie_id: 'a1',
    administratie_naam: 'Kempen Facilities B.V.',
    leverancier_naam: 'X',
    referentie: null,
    factuurdatum: null,
    totaalbedrag: '1.00',
    aangeboden_op: '2026-08-26T09:00:00Z',
    laag_volgnummer: 1,
    boeking_omschrijving: null,
    staande_regel_kandidaat: false,
    ...over,
  }
}
function vraag(over: Partial<AccordeurVraagDto>): AccordeurVraagDto {
  return {
    id: 'v',
    administratie_id: 'a1',
    administratie_naam: 'Kempen Facilities B.V.',
    document_id: 'd9',
    document_status: 'geboekt',
    leverancier_naam: null,
    totaalbedrag: null,
    vraag_tekst: '?',
    gesteld_op: '2026-08-26T09:00:00Z',
    ik_ben_aan_de_beurt: true,
    berichten: [],
    ...over,
  }
}

describe('administratiesMetWerk', () => {
  it('groepeert per administratie, telt facturen + vragen en zet de langst wachtende bovenaan', () => {
    const standen = administratiesMetWerk(
      [
        item({ document_id: 'd1', administratie_id: 'a2', administratie_naam: 'Universal Steigerbouw B.V.', aangeboden_op: '2026-08-27T08:00:00Z' }),
        item({ document_id: 'd2', administratie_id: 'a1', aangeboden_op: '2026-08-26T09:00:00Z' }),
        item({ document_id: 'd3', administratie_id: 'a1', aangeboden_op: '2026-08-27T07:00:00Z' }),
      ],
      [vraag({ id: 'v1', administratie_id: 'a1' }), vraag({ id: 'v2', administratie_id: 'a1', document_id: 'd2' })],
    )
    expect(standen.map((s) => s.id)).toEqual(['a1', 'a2'])
    expect(standen[0]).toMatchObject({ naam: 'Kempen Facilities B.V.', teAccorderen: 2, vragen: 2, oudsteWacht: '2026-08-26T09:00:00Z' })
    expect(standen[1]).toMatchObject({ teAccorderen: 1, vragen: 0 })
  })

  it('een administratie met alleen een vraag (geen facturen) telt als werk en komt achteraan', () => {
    const standen = administratiesMetWerk([item({ administratie_id: 'a2', administratie_naam: 'B' })], [vraag({ administratie_id: 'a3', administratie_naam: 'C' })])
    expect(standen.map((s) => s.id)).toEqual(['a2', 'a3'])
    expect(standen[1]).toMatchObject({ teAccorderen: 0, vragen: 1, oudsteWacht: null })
  })

  it('geen werk = geen administraties (lege staat "✓ Alles is bij")', () => {
    expect(administratiesMetWerk([], [])).toEqual([])
  })
})

describe('kiesActieveAdministratie', () => {
  const twee = administratiesMetWerk([item({ administratie_id: 'a1' }), item({ document_id: 'd2', administratie_id: 'a2', administratie_naam: 'B' })], [])
  it('precies één administratie met werk → altijd die, ook zonder keuze (keuzescherm overslaan)', () => {
    const een = administratiesMetWerk([item({})], [])
    expect(kiesActieveAdministratie(null, een)).toBe('a1')
    expect(kiesActieveAdministratie('onbekend', een)).toBe('a1')
  })
  it('≥ 2 → de keuze zolang die werk heeft, anders het overzicht (null)', () => {
    expect(kiesActieveAdministratie(null, twee)).toBeNull()
    expect(kiesActieveAdministratie('a2', twee)).toBe('a2')
    expect(kiesActieveAdministratie('a9', twee)).toBeNull()
  })
  it('geen werk → null', () => {
    expect(kiesActieveAdministratie('a1', [])).toBeNull()
  })
})

describe('wachtSindsTekst + vragenChipTekst', () => {
  const nu = new Date(2026, 7, 27, 14, 0) // 27-08-2026 14:00 lokaal
  it('vandaag / gisteren / N dagen op kalenderdagen', () => {
    expect(wachtSindsTekst(new Date(2026, 7, 27, 8, 0).toISOString(), nu)).toBe('Oudste wacht sinds vandaag')
    expect(wachtSindsTekst(new Date(2026, 7, 26, 23, 30).toISOString(), nu)).toBe('Oudste wacht sinds gisteren')
    expect(wachtSindsTekst(new Date(2026, 7, 20, 9, 0).toISOString(), nu)).toBe('Oudste wacht al 7 dagen')
    expect(wachtSindsTekst(null, nu)).toBeNull()
    expect(wachtSindsTekst('geen datum', nu)).toBeNull()
  })
  it('enkelvoud/meervoud', () => {
    expect(vragenChipTekst(1)).toBe('💬 1 vraag aan u')
    expect(vragenChipTekst(3)).toBe('💬 3 vragen aan u')
  })
})
