// @vitest-environment node
// Documentlink volgt de soort (BUG 23-09, bundelrun 24-09 blok 7a): DE ENE bron voor "open dit document" is
// `werkvoorraad/format.ts::documentPad`. Deze guard leest alle bronbestanden onder src/ en faalt op een letterlijke
// `/documenten/${…}`-LINK (template-string die met /documenten/ begint) buiten format.ts. API-paden
// (`/administraties/${…}/documenten/${…}`, `/dossier/${…}/documenten/${…}`) beginnen niet met `/documenten/` en tellen
// niet; testbestanden en de dev-harnassen (mock-URL's) zijn uitgesloten.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { documentPad, documentRoute, heeftEigenReviewscherm } from './format'

const SRC = fileURLToPath(new URL('..', import.meta.url))
const TOEGESTAAN = new Set(['werkvoorraad/format.ts'])
const LINK = /`\/documenten\/\$\{/

function* bestanden(dir: string): Generator<string> {
  for (const naam of readdirSync(dir)) {
    const pad = join(dir, naam)
    if (statSync(pad).isDirectory()) {
      if (naam === 'dev') continue
      yield* bestanden(pad)
    } else if (/\.(ts|tsx)$/.test(naam) && !/\.test\.(ts|tsx)$/.test(naam)) {
      yield pad
    }
  }
}

describe('documentPad — één bron voor documentlinks', () => {
  it('geen letterlijke `/documenten/${…}`-link buiten werkvoorraad/format.ts', () => {
    const fouten: string[] = []
    for (const pad of bestanden(SRC)) {
      const rel = relative(SRC, pad)
      if (TOEGESTAAN.has(rel)) continue
      readFileSync(pad, 'utf8')
        .split('\n')
        .forEach((regel, i) => {
          if (LINK.test(regel)) fouten.push(`${rel}:${i + 1}: ${regel.trim()}`)
        })
    }
    expect(fouten, 'gebruik documentPad(administratieId, { id, soort })').toEqual([])
  })

  it('route volgt de soort; zonder soort valt de link terug op het inkoop-controlescherm', () => {
    expect(documentPad('a', { id: 'd' })).toBe('/documenten/a/d')
    expect(documentPad('a', { id: 'd', soort: 'inkoopfactuur' })).toBe('/documenten/a/d')
    expect(documentPad('a', { id: 'd', soort: 'kassarapport' })).toBe('/omzet/a/d')
    expect(documentPad('a', { id: 'd', soort: 'verkoopfactuur' })).toBe('/verkoop/a/d')
    expect(documentPad('a', { id: 'd', soort: 'waarborg' })).toBe('/waarborg/a/d')
    expect(documentPad('a', { id: 'd', soort: 'verplichting' })).toBe('/verplichting/a/d')
    expect(documentPad('a', { id: 'd', soort: 'kassarapport', status: 'vraag_open' })).toBe('/?administratie=a&sectie=vragen&document=d')
    expect(documentPad('a', { id: 'd', status: 'verwijderd' })).toBe('/documenten/a/d')
    expect(heeftEigenReviewscherm('kassarapport')).toBe(true)
    expect(heeftEigenReviewscherm('inkoopfactuur')).toBe(false)
    expect(heeftEigenReviewscherm(undefined)).toBe(false)
  })

  it('documentRoute is een dunne laag op documentPad (lijstcontext reist alleen naar het inkoopscherm)', () => {
    const context = { soort: 'inkoopfactuur', status: 'te_controleren', zoekterm: 'x' }
    expect(documentRoute('a', { id: 'd', soort: 'inkoopfactuur', status: 'te_controleren' } as never, context as never)).toMatch(/^\/documenten\/a\/d\?/)
    expect(documentRoute('a', { id: 'd', soort: 'kassarapport', status: 'te_controleren' } as never, context as never)).toBe('/omzet/a/d')
  })
})
