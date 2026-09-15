import { describe, expect, it } from 'vitest'
import { formatVerloop } from './gebruikersApi'

// Bug Peter 15-09 (Gebruikers › Klant-accordeurs): "herstel-link verloopt over 633724 uur" (demo-link tot 2099).
const NU = new Date('2026-09-15T12:00:00Z')
const over = (uren: number) => new Date(NU.getTime() + uren * 3_600_000).toISOString()

describe('formatVerloop', () => {
  it('onder 48 uur: uren; ≤ 1 uur: binnen een uur; verstreken: verlopen', () => {
    expect(formatVerloop(over(0.5), NU)).toBe('verloopt binnen een uur')
    expect(formatVerloop(over(1), NU)).toBe('verloopt binnen een uur')
    expect(formatVerloop(over(47), NU)).toBe('verloopt over 47 uur')
    expect(formatVerloop(over(72), NU)).toBe('verloopt over 3 dagen')
    expect(formatVerloop(over(-2), NU)).toBe('verlopen')
  })

  it('tot 30 dagen: dagen; daarboven: de datum', () => {
    expect(formatVerloop(over(48), NU)).toBe('verloopt over 2 dagen')
    expect(formatVerloop(over(30 * 24), NU)).toBe('verloopt over 30 dagen')
    expect(formatVerloop('2026-11-01T10:00:00Z', NU)).toBe('verloopt op 01-11-2026')
  })

  it('demo-link tot 2099: "verloopt niet" in plaats van 633724 uur', () => {
    expect(formatVerloop('2099-01-01T00:00:00Z', NU)).toBe('verloopt niet')
    expect(formatVerloop('niet-een-datum', NU)).toBe('')
  })
})
