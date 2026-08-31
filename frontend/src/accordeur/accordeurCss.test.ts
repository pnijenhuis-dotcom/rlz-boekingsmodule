// @vitest-environment node
// Node-omgeving (patroon boekingsregelsCss.test.ts / contrast.test.ts): import.meta.url is onder
// jsdom geen file-URL.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/** iPad-ronde 29-08 (iPad blijft ondersteund, besluit Peter): de accordeur-app is een telefoonkolom
 * die op brede schermen gecentreerd staat. Op een tablet krijgt die kolom een bredere maat, zodat
 * factuurbeeld en kaarten niet in een 430px-strook op een 13"-scherm blijven hangen. jsdom heeft
 * geen layout, dus de stylesheet wordt als tekst getoetst: de telefoonmaat blijft de basis, de
 * tabletmaat leeft uitsluitend achter een min-width-breakpoint en blijft ruim binnen de kleinste
 * iPad-portretbreedte (iPad mini = 744pt) zodat er nooit horizontale overflow ontstaat. */
const css = readFileSync(fileURLToPath(new URL('./accordeur.css', import.meta.url)), 'utf8')
const cssZonderCommentaar = css.replace(/\/\*[\s\S]*?\*\//g, '')

function maxBreedte(blok: string): number {
  const m = /max-width:\s*(\d+)px/.exec(blok)
  if (!m) throw new Error(`geen max-width in blok: ${blok}`)
  return Number(m[1])
}

function basisBlok(): string {
  const start = cssZonderCommentaar.indexOf('.acc-phone {')
  if (start === -1) throw new Error('.acc-phone-basisregel niet gevonden')
  return cssZonderCommentaar.slice(start, cssZonderCommentaar.indexOf('}', start))
}

function tabletBreakpoint(): { minWidth: number; blok: string } {
  const re = /@media \(min-width:\s*(\d+)px\)\s*\{\s*\.acc-phone\s*\{([^}]*)\}/g
  let m: RegExpExecArray | null
  while ((m = re.exec(cssZonderCommentaar)) !== null) {
    if (/max-width/.test(m[2])) return { minWidth: Number(m[1]), blok: m[2] }
  }
  throw new Error('geen tablet-breakpoint met max-width op .acc-phone gevonden')
}

describe('accordeur.css — telefoonkolom + tablet-breakpoint (iPad-ronde 29-08)', () => {
  it('de basiskolom blijft de telefoonmaat (430px) en 100% breed op smalle schermen', () => {
    const blok = basisBlok()
    expect(maxBreedte(blok)).toBe(430)
    expect(blok).toMatch(/width:\s*100%/)
  })

  it('op tablets wordt de kolom breder, maar de maat blijft onder de kleinste iPad-portretbreedte', () => {
    const { minWidth, blok } = tabletBreakpoint()
    const tablet = maxBreedte(blok)
    expect(tablet).toBeGreaterThan(430)
    // iPad mini portret = 744pt: de bredere kolom moet dáár al gelden én erin passen.
    expect(minWidth).toBeLessThanOrEqual(744)
    expect(tablet).toBeLessThanOrEqual(744)
    // Nooit onder de telefoonbreedte activeren (een iPhone in portret houdt de telefoonkolom).
    expect(minWidth).toBeGreaterThan(430)
  })
})

/** Vindt het regelblok van één selector (zelfde tekst-patroon als hierboven). */
function blokVan(selector: string): string {
  const start = cssZonderCommentaar.indexOf(`${selector} {`)
  if (start === -1) throw new Error(`${selector}-regel niet gevonden`)
  return cssZonderCommentaar.slice(start, cssZonderCommentaar.indexOf('}', start))
}

describe('accordeur.css — centreer-wrapper subschermen (iPad-kliktest 30-08)', () => {
  it('.acc-subvlak bestaat mét max-width en auto-marges: smalle subschermen centreren op het tablet-breakpoint', () => {
    const blok = blokVan('.acc-subvlak')
    expect(blok).toMatch(/max-width:\s*\d+px/)
    expect(blok).toMatch(/margin:\s*0 auto/)
    // Nooit breder dan de telefoonkolom — de wrapper is juist de telefoonmaat op een tablet.
    expect(maxBreedte(blok)).toBeLessThanOrEqual(430)
  })
})

describe('accordeur.css — uploadknop i.p.v. kale file-input (overlap-bug iPad 30-08)', () => {
  it('.acc-bestandknop verankert de verborgen absolute input op zichzelf (position:relative + overflow:hidden)', () => {
    const blok = blokVan('.acc-bestandknop')
    expect(blok).toMatch(/position:\s*relative/)
    expect(blok).toMatch(/overflow:\s*hidden/)
    expect(blok).toMatch(/width:\s*100%/)
  })

  it('.acc-bestandknop-naam kapt een lange bestandsnaam af met ellipsis', () => {
    const blok = blokVan('.acc-bestandknop-naam')
    expect(blok).toMatch(/overflow:\s*hidden/)
    expect(blok).toMatch(/text-overflow:\s*ellipsis/)
    expect(blok).toMatch(/white-space:\s*nowrap/)
    expect(blok).toMatch(/max-width:\s*100%/)
  })

  it('de oude .acc-fotoknop (input verankerde fragiel op .acc-phone) is volledig gemigreerd', () => {
    expect(cssZonderCommentaar).not.toContain('.acc-fotoknop')
  })
})
