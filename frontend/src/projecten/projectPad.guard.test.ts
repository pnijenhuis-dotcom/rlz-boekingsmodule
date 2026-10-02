// @vitest-environment node
// Punt 10 run A (02-10): één routefunctie voor projectlinks (patroon documentPad 23-09). Deze guard faalt op een letterlijke
// `/projecten/${…}`-template buiten projectPad.ts en projectenApi.ts (API-paden); tests en dev-harnassen zijn uitgesloten.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { meerwerkBonPad, projectPad, projectResultaatPad } from './projectPad'

const SRC = fileURLToPath(new URL('..', import.meta.url))
// API-lagen die `/projecten/${…}`-ENDPOINTS aanroepen (geen links): projectenApi.ts, document/projectverdelingApi.ts.
const TOEGESTAAN = new Set(['projecten/projectPad.ts', 'projecten/projectenApi.ts', 'document/projectverdelingApi.ts'])
const LINK = /`\/projecten\/\$\{/

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

describe('projectPad — één bron voor project- en meerwerkbon-links', () => {
  it('geen letterlijke `/projecten/${…}`-link buiten projectPad.ts (API-paden in projectenApi.ts uitgezonderd)', () => {
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
    expect(fouten, 'gebruik projectPad(administratieId, projectId)').toEqual([])
  })

  it('paden', () => {
    expect(projectPad('a', 'p')).toBe('/projecten/a/p')
    expect(projectPad('a', 'p', { meerwerkId: 'm' })).toBe('/projecten/a/p?meerwerk=m')
    expect(projectResultaatPad('a', 'p')).toBe('/projecten/a/p/resultaat')
    expect(meerwerkBonPad('a', 'm')).toBe('/meerwerk?administratie=a&tab=meerwerk&meerwerk=m')
  })
})
