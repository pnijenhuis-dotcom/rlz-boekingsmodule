// @vitest-environment node
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/** Aanvulling blok D 03-09 (screenshot Peter: "+ Doelentiteit" als grijs default-blok) — `.linkbtn` had géén
 * basisstijl, alleen context-varianten (.userbox, .anker-popup.rijmenu). jsdom heeft geen layout, dus de
 * stylesheet wordt als tekst getoetst (patroon boekingsregelsCss.test.ts). */
const css = readFileSync(fileURLToPath(new URL('./components.css', import.meta.url)), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

function blok(selector: string): string {
  const start = css.indexOf(`\n${selector} {`)
  if (start === -1) throw new Error(`Selector niet gevonden: ${selector}`)
  return css.slice(start, css.indexOf('}', start))
}

describe('.linkbtn basisstijl (blok D 03-09)', () => {
  it('heeft een eigen basisblok dat de browser-default wegneemt: geen rand, geen vulling, teal actiekleur', () => {
    const basis = blok('.linkbtn')
    expect(basis).toMatch(/background:\s*none/)
    expect(basis).toMatch(/border:\s*none/)
    expect(basis).toMatch(/color:\s*var\(--primary\)/)
    expect(basis).toMatch(/cursor:\s*pointer/)
  })
})
