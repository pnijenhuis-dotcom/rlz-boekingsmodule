import { describe, expect, it } from 'vitest'
import { catalogusAdministraties, isMonoKlant, landingsPad, planningMenuPad, type MijnToegangDto } from './useMijnToegang'

/* Slimme landing + Planning-menu (steigerbouw-run C1/C2): pure beslislogica, fail-closed. */
const A = { id: 'a1', naam: 'Universal Steigerbouw B.V.' }
const B = { id: 'a2', naam: 'Kempen Facilities B.V.' }
const basis: MijnToegangDto = { heeft_meerwerk_recht: false, administraties_met_opt_in: [], aantal_administraties_in_scope: 1, is_beheerder: false, heeft_veldwerkerbeheer_recht: false, is_beheerder_of_bp: false }

describe('landingsPad (C1)', () => {
  it('twijfel of fout → null (bestaande werkvoorraad)', () => {
    expect(landingsPad(undefined, [A])).toBeNull()
    expect(landingsPad(null, [A])).toBeNull()
    expect(landingsPad(basis, null)).toBeNull()
    expect(landingsPad({ ...basis, aantal_administraties_in_scope: 2 }, [A, B])).toBeNull()
    expect(landingsPad({ ...basis, is_beheerder: true }, [A])).toBeNull()
    // scope-teller en administratielijst oneens → fail-closed
    expect(landingsPad(basis, [A, B])).toBeNull()
  })
  it('mono-klant → klantpagina; mét recht + opt-in → steigerbouw-deel', () => {
    expect(landingsPad(basis, [A])).toBe('/?administratie=a1')
    expect(landingsPad({ ...basis, heeft_meerwerk_recht: true }, [A])).toBe('/?administratie=a1')
    expect(landingsPad({ ...basis, heeft_meerwerk_recht: true, administraties_met_opt_in: ['a1'] }, [A])).toBe('/meerwerk?administratie=a1')
    expect(isMonoKlant({ ...basis }, [A])).toBe(true)
  })
})

describe('planningMenuPad (C2)', () => {
  it('volgt module-recht + opt-in', () => {
    expect(planningMenuPad(null)).toBeNull()
    expect(planningMenuPad({ ...basis, heeft_meerwerk_recht: true })).toBeNull()
    expect(planningMenuPad({ ...basis, administraties_met_opt_in: ['a1'] })).toBeNull()
    expect(planningMenuPad({ ...basis, heeft_meerwerk_recht: true, administraties_met_opt_in: ['a1'] })).toBe('/planning?administratie=a1')
    expect(planningMenuPad({ ...basis, heeft_meerwerk_recht: true, administraties_met_opt_in: ['a1', 'a2'], is_beheerder: true })).toBe('/planning')
  })
})

describe('catalogusAdministraties (Odoo-afrondingsrun 04-09 blok B)', () => {
  it('leest `administraties_met_catalogus`; oudere response zonder dat veld = de opt-in-lijst; geen toegang = leeg', () => {
    expect(catalogusAdministraties(null)).toEqual([])
    expect(catalogusAdministraties(undefined)).toEqual([])
    expect(catalogusAdministraties({ ...basis, administraties_met_opt_in: ['a1'] })).toEqual(['a1'])
    expect(catalogusAdministraties({ ...basis, administraties_met_opt_in: ['a1'], administraties_met_catalogus: ['a1', 'a2'] })).toEqual(['a1', 'a2'])
    expect(catalogusAdministraties({ ...basis, administraties_met_opt_in: ['a1'], administraties_met_catalogus: [] })).toEqual([])
  })
})
