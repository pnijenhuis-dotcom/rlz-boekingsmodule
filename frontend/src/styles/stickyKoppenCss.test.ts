// @vitest-environment node
// Node-omgeving (patroon boekingsregelsCss.test.ts / accordeurCss.test.ts): jsdom heeft geen
// layout, dus de stylesheet wordt als tekst getoetst.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/** Sticky kolomkoppen (kliktest Peter 01-09, administraties-v2): een focus-terugkeer (Radix-
 * dialoog sluiten, tabben) scrolt een rij minimaal in beeld — tot de contáinerrand en dus half
 * achter de sticky kop (headless-reproductie 01-09: overlap ≈ 34px = de kophoogte). De vaste
 * remedie is scroll-padding-top op de scroll-container, minstens zo hoog als de kop; deze test
 * bewaakt dat die declaratie niet stilletjes sneuvelt. Geldt voor álle sticky-koppen-tabellen
 * (administraties, gebruikers, leverancier-autoboeken). */
const css = readFileSync(fileURLToPath(new URL('./components.css', import.meta.url)), 'utf8')
const cssZonderCommentaar = css.replace(/\/\*[\s\S]*?\*\//g, '')

function blok(selector: string): string {
  const start = cssZonderCommentaar.indexOf(`${selector} {`)
  if (start === -1) throw new Error(`selector niet gevonden: ${selector}`)
  return cssZonderCommentaar.slice(start, cssZonderCommentaar.indexOf('}', start))
}

describe('components.css — sticky kolomkoppen (kliktest 01-09)', () => {
  it('de scroll-container declareert scroll-padding-top van minstens de kophoogte', () => {
    const container = blok('.tabel-scroll.sticky-koppen')
    const m = /scroll-padding-top:\s*(\d+)px/.exec(container)
    expect(m, 'scroll-padding-top ontbreekt op .tabel-scroll.sticky-koppen').not.toBeNull()
    // th ≈ 34px (padding 2×9px + kopregel); de padding moet de kop ruim dekken.
    expect(Number(m![1])).toBeGreaterThanOrEqual(34)
  })

  it('de koppen blijven sticky mét dekkende achtergrond (voorwaarde voor de scroll-padding-fix)', () => {
    const th = blok('.tabel-scroll.sticky-koppen th')
    expect(th).toMatch(/position:\s*sticky/)
    expect(th).toMatch(/background:/)
  })
})
