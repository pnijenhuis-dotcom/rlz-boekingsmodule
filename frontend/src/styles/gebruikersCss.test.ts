// @vitest-environment node
// Node-omgeving (zelfde reden als contrast.test.ts): import.meta.url is onder jsdom geen file-URL.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/** Blok 2 vervolgrun 10-09 avond — CSS-kant van het regressievangnet tegen kolom-implosie op
 * Gebruikers & toegang. jsdom heeft geen layout, dus de stylesheet wordt als tekst getoetst (patroon
 * boekingsregelsCss.test.ts): koppen nooit afgekapt (nowrap, géén ellipsis), fixed layout met de
 * min-width uit gebruikersKolommen.ts (inline, niet als losse CSS-constante), chips in één flex-regel. */
const css = readFileSync(fileURLToPath(new URL('./components.css', import.meta.url)), 'utf8')
const cssZonderCommentaar = css.replace(/\/\*[\s\S]*?\*\//g, '')

function blok(selector: string): string {
  const start = cssZonderCommentaar.indexOf(`${selector} {`)
  if (start === -1) throw new Error(`Selector niet gevonden: ${selector}`)
  const eind = cssZonderCommentaar.indexOf('}', start)
  return cssZonderCommentaar.slice(start, eind)
}

describe('gebruikers-tabel CSS (blok 2 10-09, kolomminima)', () => {
  it('koppen zijn nowrap en krijgen nooit een ellipsis', () => {
    const kop = blok('.gebruikers-tabel th')
    expect(kop).toMatch(/white-space:\s*nowrap/)
    expect(kop).not.toMatch(/ellipsis/)
  })

  it('de tabel is table-layout fixed zonder losse CSS-min-width (één bron: gebruikersKolommen.ts, inline)', () => {
    const tabel = blok('.gebruikers-tabel')
    expect(tabel).toMatch(/table-layout:\s*fixed/)
    expect(tabel).not.toMatch(/min-width/)
  })

  it('beveiligings-/statuschips staan in een flex-regel met gap; de chips zelf blijven nowrap (Badge/apparaat-chip)', () => {
    const regel = blok('.gebruikers-tabel .chips-regel')
    expect(regel).toMatch(/display:\s*flex/)
    expect(regel).toMatch(/gap:/)
  })

  it('de actiekolom is één regel: flex + nowrap (één primaire knop + ⋯)', () => {
    const acties = blok('.gebruikers-tabel .rij-acties')
    expect(acties).toMatch(/display:\s*flex/)
    expect(acties).toMatch(/white-space:\s*nowrap/)
  })
})
