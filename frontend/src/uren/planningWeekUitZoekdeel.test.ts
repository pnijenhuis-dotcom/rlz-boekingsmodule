import { describe, expect, it } from 'vitest'
import { planningWeekUitZoekdeel } from './UrenFlow'

// 15-09: deep-link uit de bundelmelding "planning week N aangepast" (/accordeur?planning=JJJJ-Wnn).
describe('planningWeekUitZoekdeel', () => {
  it('leest jaar + week, weigert onzin', () => {
    expect(planningWeekUitZoekdeel('?planning=2026-W37')).toEqual({ jaar: 2026, weeknummer: 37 })
    expect(planningWeekUitZoekdeel('?planning=2026-W07&x=1')).toEqual({ jaar: 2026, weeknummer: 7 })
    expect(planningWeekUitZoekdeel('?planning=2026-W60')).toBeNull()
    expect(planningWeekUitZoekdeel('?planning=vorige')).toBeNull()
    expect(planningWeekUitZoekdeel('')).toBeNull()
  })
})
