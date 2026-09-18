// @vitest-environment node
/** Run A punt 7 (leesbaarheid buiten): binnen de veld-app (`.acc-veld`) geen tekst < 14 px en tikdoelen ≥ 48 px —
 * geborgd in de CSS-bron (jsdom meet geen pixels; dit toetst de regels die de browser toepast). */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const css = readFileSync(fileURLToPath(new URL('../accordeur/accordeur.css', import.meta.url)), 'utf8')

function blok(selectorDeel: string): string {
  const i = css.indexOf(selectorDeel)
  expect(i, `selector ${selectorDeel} ontbreekt`).toBeGreaterThan(-1)
  return css.slice(i, css.indexOf('}', i))
}

describe('veld-app tekst en tikdoelen (.acc-veld)', () => {
  it('meta, chips, small, sectielabels, hulptekst en tekstlinks staan binnen .acc-veld op 14 px', () => {
    const regel = blok('.acc-veld .acc-meta,')
    for (const sel of ['.acc-veld .acc-chip', '.acc-veld small', '.acc-veld .acc-seclabel', '.acc-veld .acc-qcount', '.acc-veld .acc-notitie', '.acc-veld .acc-tekstlink']) {
      expect(regel, sel).toContain(sel)
    }
    expect(regel).toMatch(/font-size:\s*14px/)
  })
  it('geen font-size onder 14 px binnen een .acc-veld-regel; knoppen, plus en tabs ≥ 48 px', () => {
    const veldRegels = css.split('}').filter((r) => r.includes('.acc-veld'))
    for (const r of veldRegels) {
      for (const m of r.matchAll(/font-size:\s*([\d.]+)px/g)) expect(Number(m[1]), r.trim().slice(0, 60)).toBeGreaterThanOrEqual(14)
    }
    expect(blok('.acc-veld .acc-btn,')).toMatch(/min-height:\s*48px/)
    for (const sel of ['.acc-tik {', '.acc-ingeklapt {']) expect(blok(sel)).toMatch(/min-height:\s*48px/)
  })
})
