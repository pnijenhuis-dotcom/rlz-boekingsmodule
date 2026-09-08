// @vitest-environment node
// Guard app-bundel zonder passkey/TOTP/wachtwoord (contract §5f, besluit Peter 08-09-2026): de
// accordeur-/veldwerker-app kent nog precies één toegangspad (uitnodiging → activatie op het toestel →
// toegangscode). Deze test leest álle .ts/.tsx-bronbestanden (geen tests) onder src/accordeur, src/uren
// en de drie slot-modules onder src/api, strijkt commentaar weg en is rood zodra er nog een
// passkey-/WebAuthn-/TOTP-/wachtwoord-woord in code of schermtekst staat. Plus een tekstcheck op
// accordeur.css voor "passkey".
//
// ÉÉN gedocumenteerde uitzondering: het endpoint-pad `/auth/webauthn/config` (store-links + dev-stub-
// vlag voor de web-fallback van een universal link). Het pad blijft historisch zo heten (contract §5e:
// "hernoem de client-functie naar haalAppConfig; het endpoint-pad blijft") — de string wordt hier
// vóór de regex-toets weggestreept, uitsluitend die exacte letterlijke waarde.

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

const MAPPEN = ['accordeur', 'uren']
const LOSSE_BESTANDEN = ['api/appSlot.ts', 'api/nativeSessie.ts', 'api/webVeiligeOpslag.ts']

/** Het verboden vocabulaire van de app-oppervlakte (contract §5f). */
export const VERBODEN = /passkey|webauthn|navigator\.credentials|totp|verificatiecode|wachtwoord|Inloggen met|ontgrendel-opties|NatievePasskey/i

/** De enige toegestane uitzondering — exact dit pad, alleen als string-literal. */
const UITZONDERING_ENDPOINT = /(['"`])\/auth\/webauthn\/config\1/g

function alleBronbestanden(map: string): string[] {
  if (!fs.existsSync(map)) return []
  return fs.readdirSync(map, { withFileTypes: true }).flatMap((item) => {
    const volledig = path.join(map, item.name)
    if (item.isDirectory()) return alleBronbestanden(volledig)
    if (!/\.tsx?$/.test(item.name) || /\.test\.tsx?$/.test(item.name)) return []
    return [volledig]
  })
}

// Strijkt regel- en blokcommentaar weg (geen volledige parser: een dubbele schuine streep binnen
// een string-literal zou ook wegvallen — dat maakt de toets alleen strenger richting "niets
// gevonden" wanneer de verboden tekst vóór zo'n streep staat, wat in de praktijk niet voorkomt).
export function zonderCommentaar(bron: string): string {
  return bron.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`])\/\/.*$/gm, '$1')
}

function toetsbareInhoud(bestand: string): string {
  return zonderCommentaar(fs.readFileSync(bestand, 'utf8')).replace(UITZONDERING_ENDPOINT, '$1<app-config-endpoint>$1')
}

const bestanden = [
  ...MAPPEN.flatMap((m) => alleBronbestanden(path.join(SRC, m))),
  ...LOSSE_BESTANDEN.map((b) => path.join(SRC, b)).filter((b) => fs.existsSync(b)),
]

describe('app-bundel zonder passkey/TOTP/wachtwoord (guard §5f)', () => {
  it('scant een betekenisvolle set bestanden (guard tegen een stille lege scan)', () => {
    expect(bestanden.length).toBeGreaterThan(20)
    for (const los of LOSSE_BESTANDEN) expect(fs.existsSync(path.join(SRC, los)), los).toBe(true)
  })

  it.each(bestanden.map((b) => [path.relative(SRC, b), b]))('%s bevat geen verboden auth-vocabulaire', (_naam, bestand) => {
    const inhoud = toetsbareInhoud(bestand)
    const treffers = [...inhoud.matchAll(new RegExp(VERBODEN.source, 'gi'))].map((m) => {
      const regel = inhoud.slice(0, m.index).split('\n').length
      return `regel ${regel}: "${m[0]}"`
    })
    expect(treffers, `verboden vocabulaire in ${path.relative(SRC, bestand)}`).toEqual([])
  })

  it('de verwijderde modules bestaan niet meer onder src/accordeur', () => {
    for (const weg of [
      'AccordeurLogin.tsx',
      'AccordeurActiveren.tsx',
      'Ontgrendel.tsx',
      'webauthnClient.ts',
      'nativePasskey.ts',
      'passkeyFouten.ts',
    ]) {
      expect(fs.existsSync(path.join(SRC, 'accordeur', weg)), `${weg} hoort weg te zijn`).toBe(false)
    }
  })

  it('accordeur.css noemt "passkey" nergens (ook niet in commentaar)', () => {
    const css = fs.readFileSync(path.join(SRC, 'accordeur', 'accordeur.css'), 'utf8')
    expect(/passkey/i.test(css)).toBe(false)
  })

  it('zonderCommentaar strijkt beide commentaarvormen weg maar laat URL-strings staan', () => {
    expect(zonderCommentaar('const a = 1 // passkey hier\n/* webauthn daar */ const b = 2')).not.toMatch(VERBODEN)
    expect(zonderCommentaar("const u = 'https://x.nl/pad' // niets")).toContain('https://x.nl/pad')
  })

  it('de uitzondering dekt uitsluitend het exacte endpoint-pad', () => {
    expect("apiJson('/auth/webauthn/config')".replace(UITZONDERING_ENDPOINT, '$1x$1')).not.toMatch(VERBODEN)
    expect("apiJson('/auth/webauthn/configuratie')".replace(UITZONDERING_ENDPOINT, '$1x$1')).toMatch(VERBODEN)
  })
})
