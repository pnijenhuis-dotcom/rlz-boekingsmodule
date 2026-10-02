/** Blok D feedback uitvoerder 18-09: de WEEK-planningstab (eigen planning) in de veld-app alleen voor ZZP'er en
 * detacheerder — allowlist, nooit een complement (onbekende rol = geen tab). Run B 02-10 punt 26 herziet dat
 * uitsluitend voor de rol uitvoerder mét een eigen DAG-planningstab (`toontDagplanningTab`), die "Mijn uren" vervangt. */
import { describe, expect, it } from 'vitest'
import { DAGPLANNING_TAB_ROLLEN, PLANNING_TAB_ROLLEN, toontDagplanningTab, toontPlanningTab } from './rollen'

describe('toontPlanningTab (18-09 blok D — weekweergave eigen planning)', () => {
  it("ZZP'er en detacheerder houden de weekplanningstab", () => {
    expect(toontPlanningTab('zzper')).toBe(true)
    expect(toontPlanningTab('detacheerder')).toBe(true)
  })
  it('uitvoerder, kantoorrollen, onbekend en null krijgen géén weekplanningstab (fail-closed)', () => {
    for (const rol of ['uitvoerder', 'beheerder', 'boekhouding', 'boekhouding_projecten', 'klant_accordeur', 'nieuw', null])
      expect(toontPlanningTab(rol), String(rol)).toBe(false)
  })
  it('de allowlist bevat de uitvoerder niet', () => {
    expect([...PLANNING_TAB_ROLLEN]).toEqual(['zzper', 'detacheerder'])
  })
})

describe('toontDagplanningTab (run B 02-10 punt 26 — dagplanning uitvoerder)', () => {
  it('alleen de uitvoerder krijgt de dagplanningstab', () => {
    expect(toontDagplanningTab('uitvoerder')).toBe(true)
    expect([...DAGPLANNING_TAB_ROLLEN]).toEqual(['uitvoerder'])
  })
  it("ZZP'er, detacheerder, kantoorrollen, onbekend en null niet (fail-closed; ZZP'er/detacheerder ongewijzigd)", () => {
    for (const rol of ['zzper', 'detacheerder', 'beheerder', 'boekhouding', 'boekhouding_projecten', 'klant_accordeur', 'nieuw', null])
      expect(toontDagplanningTab(rol), String(rol)).toBe(false)
  })
})
