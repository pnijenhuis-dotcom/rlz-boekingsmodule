import { describe, expect, it } from 'vitest'
import { WORDT_GEBOEKT_VAST_MINUTEN, wordtGeboektLabel, wordtGeboektLooptVast, wordtGeboektMinuten } from './status'

// BUG 21-09: "Wordt geboekt…" was een eeuwige grijze stip (job rlz-boek-wachtrij startte drie dagen niet).
describe('wordtGeboektLabel (21-09)', () => {
  const t0 = Date.parse('2026-09-21T12:46:00Z')

  it('binnen de grens: gewoon "Wordt geboekt…"', () => {
    expect(wordtGeboektMinuten('2026-09-21T12:46:00Z', t0 + 2 * 60_000)).toBe(2)
    expect(wordtGeboektLooptVast('2026-09-21T12:46:00Z', t0 + 4 * 60_000 + 59_000)).toBe(false)
    expect(wordtGeboektLabel('2026-09-21T12:46:00Z', t0 + 2 * 60_000)).toBe('Wordt geboekt…')
  })

  it(`vanaf ${WORDT_GEBOEKT_VAST_MINUTEN} min: "(loopt vast — N min)"`, () => {
    expect(wordtGeboektLooptVast('2026-09-21T12:46:00Z', t0 + 5 * 60_000)).toBe(true)
    expect(wordtGeboektLabel('2026-09-21T12:46:00Z', t0 + 16 * 60_000)).toBe('Wordt geboekt… (loopt vast — 16 min)')
  })

  it('onleesbare of ontbrekende datum = nooit een vals "loopt vast"', () => {
    expect(wordtGeboektMinuten(null, t0)).toBe(0)
    expect(wordtGeboektMinuten('geen datum', t0)).toBe(0)
    expect(wordtGeboektLabel(undefined, t0)).toBe('Wordt geboekt…')
  })
})
