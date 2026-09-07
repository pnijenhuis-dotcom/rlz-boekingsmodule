import { describe, expect, it } from 'vitest'
import { kiesStandaardAdministratie, standaardRedenLabel, urenMeerwerkOptIns } from './standaardAdministratie'

/* Fixrun 07-09 blok C3: de veldwerker-dialogen openen voorgeselecteerd — geen picker-poort meer
 * (kernprincipe 7). Drie regels op volgorde + "geen kandidaat". */

const A = { id: 'aaaaaaaa-0000-0000-0000-000000000001', naam: 'BLOW B.V.' }
const B = { id: 'aaaaaaaa-0000-0000-0000-000000000002', naam: 'Universal Steigerbouw Nederland B.V.' }
const C = { id: 'aaaaaaaa-0000-0000-0000-000000000003', naam: 'Kempen Facilities B.V.' }

describe('kiesStandaardAdministratie', () => {
  it('regel 1: precies één administratie in scope → die, ongeacht hints of opt-ins', () => {
    expect(kiesStandaardAdministratie([A], { recentstePlanning: B.id }, { urenMeerwerk: [B.id] })).toEqual({
      id: A.id,
      reden: 'enige_in_scope',
    })
  })

  it('regel 2: recentste planning wint van de opt-in; buiten scope telt een hint niet', () => {
    expect(kiesStandaardAdministratie([A, B, C], { recentstePlanning: C.id }, { urenMeerwerk: [B.id] })).toEqual({
      id: C.id,
      reden: 'recentste_planning',
    })
    // Hint naar een administratie buiten de scope → genegeerd, dan de opt-in-regel.
    expect(
      kiesStandaardAdministratie([A, B], { recentstePlanning: C.id }, { urenMeerwerk: [B.id] }),
    ).toEqual({ id: B.id, reden: 'enige_met_opt_in' })
  })

  it('regel 2: planning gaat vóór koppeling, tenzij voorkeur = koppeling (crediteur-dialoog)', () => {
    const hints = { recentstePlanning: A.id, recentsteKoppeling: C.id }
    expect(kiesStandaardAdministratie([A, B, C], hints)?.id).toBe(A.id)
    expect(kiesStandaardAdministratie([A, B, C], { ...hints, voorkeur: 'koppeling' })).toEqual({
      id: C.id,
      reden: 'recentste_koppeling',
    })
    // Alleen een koppeling-hint: die telt óók bij voorkeur planning.
    expect(kiesStandaardAdministratie([A, B, C], { recentsteKoppeling: C.id })?.reden).toBe('recentste_koppeling')
  })

  it('regel 3: precies één met uren-&-meerwerk-opt-in → die; meerdere → eerste alfabetisch', () => {
    expect(kiesStandaardAdministratie([A, B, C], {}, { urenMeerwerk: [B.id] })).toEqual({
      id: B.id,
      reden: 'enige_met_opt_in',
    })
    // Kempen < Universal alfabetisch — de lijstvolgorde zelf doet er niet toe.
    expect(kiesStandaardAdministratie([B, A, C], {}, { urenMeerwerk: [B.id, C.id] })).toEqual({
      id: C.id,
      reden: 'eerste_met_opt_in',
    })
  })

  it('geen kandidaat: meerdere in scope, geen hints, geen opt-in → null (dialoog valt terug op de lijst)', () => {
    expect(kiesStandaardAdministratie([A, B, C])).toBeNull()
    expect(kiesStandaardAdministratie([])).toBeNull()
    expect(kiesStandaardAdministratie([A, B], { recentstePlanning: null, recentsteKoppeling: undefined })).toBeNull()
  })

  it('urenMeerwerkOptIns leest de optionele DTO-vlag fail-closed (ontbrekend = geen opt-in)', () => {
    expect(urenMeerwerkOptIns([{ ...A }, { ...B, uren_meerwerk_ingeschakeld: true }, { ...C, uren_meerwerk_ingeschakeld: false }])).toEqual([B.id])
  })

  it('redenlabel: triviale keuze (enige in scope) krijgt geen uitleg, de rest wel', () => {
    expect(standaardRedenLabel('enige_in_scope')).toBeNull()
    expect(standaardRedenLabel('recentste_planning')).toContain('recentste planning')
    expect(standaardRedenLabel('eerste_met_opt_in')).toContain('wissel')
  })
})
