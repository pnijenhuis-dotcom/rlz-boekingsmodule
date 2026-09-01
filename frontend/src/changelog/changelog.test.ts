// Guard "Wat is nieuw" (D1, 01-09): het changelog-bestand heeft de afgesproken vorm (nieuwste bovenaan,
// unieke ids, punten per release) en de gelezen-stand per gebruiker werkt zonder server.
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { isOngelezen, markeerGelezen, nieuwsteRelease, parseChangelog, RELEASES } from './changelog'

// Node 22+/jsdom: geen bruikbare window.localStorage — in-memory vervanger (patroon WerkvoorraadScreen.test.tsx).
function installeerLocalStorage() {
  const opslag = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (sleutel: string) => opslag.get(sleutel) ?? null,
      setItem: (sleutel: string, waarde: string) => void opslag.set(sleutel, String(waarde)),
      removeItem: (sleutel: string) => void opslag.delete(sleutel),
      clear: () => opslag.clear(),
    },
  })
}

describe('changelog — bestandsvorm', () => {
  it('bevat minstens één release, nieuwste bovenaan, unieke ids en punten per release', () => {
    expect(RELEASES.length).toBeGreaterThan(0)
    const datums = RELEASES.map((r) => r.datum)
    expect([...datums].sort().reverse()).toEqual(datums)
    expect(new Set(RELEASES.map((r) => r.id)).size).toBe(RELEASES.length)
    for (const r of RELEASES) {
      expect(r.punten.length, `release ${r.id} zonder punten`).toBeGreaterThan(0)
      expect(r.titel.length).toBeGreaterThan(3)
    }
  })

  it('punten zijn klantleesbaar: geen bestandsnamen, migratienummers of code-jargon', () => {
    const verboden = [/\.(tsx?|py|md|sql)\b/, /migratie \d{4}/i, /\bendpoint\b/i, /\bRLS\b/, /\bDTO\b/]
    for (const r of RELEASES) for (const p of r.punten) for (const v of verboden) expect(p, `"${p}" bevat jargon (${v})`).not.toMatch(v)
  })

  it('parser: kop + bullets → release; vormfouten zijn luid', () => {
    const r = parseChangelog('<!-- x -->\n## 2026-09-01 — Titel één\n- punt a\n- punt b\n\n## 2026-08-30 — Twee\n- c\n')
    expect(r).toHaveLength(2)
    expect(r[0]).toMatchObject({ id: '2026-09-01-titel-een', datum: '2026-09-01', punten: ['punt a', 'punt b'] })
    expect(() => parseChangelog('- los punt')).toThrow(/punt zonder release-kop/)
    expect(() => parseChangelog('## 2026-09-01 — T\nlosse tekst')).toThrow(/onbekende regel/)
  })
})

describe('changelog — gelezen-stand per gebruiker (localStorage)', () => {
  beforeAll(() => installeerLocalStorage())
  afterEach(() => window.localStorage.clear())

  it('nieuwe gebruiker = ongelezen; openen markeert; een nieuwe release maakt weer ongelezen; per gebruiker gescheiden', () => {
    const releases = [
      { id: 'b', datum: '2026-09-02', titel: 'B', punten: ['x'] },
      { id: 'a', datum: '2026-09-01', titel: 'A', punten: ['y'] },
    ]
    expect(isOngelezen('u1', releases)).toBe(true)
    markeerGelezen('u1', releases)
    expect(isOngelezen('u1', releases)).toBe(false)
    expect(isOngelezen('u2', releases)).toBe(true)
    const nieuwer = [{ id: 'c', datum: '2026-09-03', titel: 'C', punten: ['z'] }, ...releases]
    expect(isOngelezen('u1', nieuwer)).toBe(true)
    expect(nieuwsteRelease(nieuwer)?.id).toBe('c')
    expect(isOngelezen(null, releases)).toBe(true)
  })
})
