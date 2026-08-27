// @vitest-environment node
// Node-omgeving (zelfde reden als contrast.test.ts): import.meta.url is onder jsdom geen file-URL.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

/** Addendum kantoor-run 27-08 punt 4 — CSS-kant van het regressievangnet tegen kolom-implosie.
 * jsdom heeft geen layout, dus de stylesheet wordt als tekst getoetst (patroon contrast.test.ts):
 * de omschrijving-cel en het omschrijving-veld mogen NOOIT per letter breken (`anywhere` /
 * `break-all`), en de tabel-min-width leeft niet meer als losse CSS-constante (die stond op 560 px
 * en drukte de rest-kolom kapot) maar komt uit boekingsregelsKolommen.ts via een inline style. */
const css = readFileSync(fileURLToPath(new URL('./components.css', import.meta.url)), 'utf8')

// Commentaar eruit vóór het matchen — de toelichting in de CSS noemt bewust wat er NIET meer
// mag staan ("anywhere"), dat mag de assertie niet vals rood maken.
const cssZonderCommentaar = css.replace(/\/\*[\s\S]*?\*\//g, '')

function blok(selector: string): string {
  const start = cssZonderCommentaar.indexOf(`${selector} {`)
  if (start === -1) throw new Error(`Selector niet gevonden: ${selector}`)
  const eind = cssZonderCommentaar.indexOf('}', start)
  return cssZonderCommentaar.slice(start, eind)
}

describe('boekingsregels-tabel CSS (punt 4, tabel-implosie)', () => {
  it('de omschrijving-cel wrapt op woordgrenzen: break-word, nooit anywhere/break-all', () => {
    const cel = blok('.boekingsregels-tabel td.omschrijving')
    expect(cel).toMatch(/overflow-wrap:\s*break-word/)
    expect(cel).not.toMatch(/anywhere|break-all/)
  })

  it('het omschrijving-veld (textarea) wrapt eveneens op woordgrenzen', () => {
    const veld = blok('.regel-omschrijving-veld')
    expect(veld).toMatch(/overflow-wrap:\s*break-word/)
    expect(veld).not.toMatch(/anywhere|break-all/)
  })

  it('de tabel heeft geen losse CSS-min-width meer (één bron: boekingsregelsKolommen.ts) en blijft table-layout fixed', () => {
    const tabel = blok('.boekingsregels-tabel')
    expect(tabel).toMatch(/table-layout:\s*fixed/)
    expect(tabel).not.toMatch(/min-width/)
  })
})
