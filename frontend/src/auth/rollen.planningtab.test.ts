/** Blok D feedback uitvoerder 18-09: planningstab in de veld-app alleen voor ZZP'er en detacheerder — allowlist,
 * nooit een complement (onbekende rol = geen tab). */
import { describe, expect, it } from 'vitest'
import { PLANNING_TAB_ROLLEN, toontPlanningTab } from './rollen'

describe('toontPlanningTab (18-09 blok D)', () => {
  it('ZZP\'er en detacheerder houden de planningstab', () => {
    expect(toontPlanningTab('zzper')).toBe(true)
    expect(toontPlanningTab('detacheerder')).toBe(true)
  })
  it('uitvoerder, kantoorrollen, onbekend en null krijgen géén planningstab (fail-closed)', () => {
    for (const rol of ['uitvoerder', 'beheerder', 'boekhouding', 'boekhouding_projecten', 'klant_accordeur', 'nieuw', null])
      expect(toontPlanningTab(rol), String(rol)).toBe(false)
  })
  it('de allowlist bevat de uitvoerder niet', () => {
    expect([...PLANNING_TAB_ROLLEN]).toEqual(['zzper', 'detacheerder'])
  })
})
