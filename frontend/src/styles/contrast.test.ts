// @vitest-environment node
// (pure bestandsparsing — onder jsdom is import.meta.url geen file-URL)
// Contrast-audit op de kleurtokens (designpass v2, punt 5 — Vastly-patroon): leest de
// tokendefinities rechtstreeks uit styles/tokens.css (kantoor, :root + .dark) en
// accordeur/accordeur.css (accordeur-/native-app, .acc dark-default + licht) en toetst de
// (voorgrond, achtergrond)-paren zoals de UI ze combineert, in BEIDE modi:
//   ≥ 4,5:1 voor tekst (WCAG 1.4.3), ≥ 3:1 voor chip-/icoonparen en grote tekst (1.4.11).
// Faalt een paar → het TOKEN bijstellen binnen de ontwerprichting, nooit de eis versoepelen.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { blend, contrastRatio, hexNaarRgb, lokaleTokens, relatieveLuminantie } from './contrast'

const kantoorCss = readFileSync(fileURLToPath(new URL('./tokens.css', import.meta.url)), 'utf8')
const accordeurCss = readFileSync(fileURLToPath(new URL('../accordeur/accordeur.css', import.meta.url)), 'utf8')

const lichtTokens = lokaleTokens(kantoorCss, ':root')
// .dark erft alles wat het niet zelf herdefinieert van :root (avatar-set, rail-accent).
const darkTokens = { ...lichtTokens, ...lokaleTokens(kantoorCss, '.dark') }

const accDark = lokaleTokens(accordeurCss, '.acc')
const accLicht = { ...accDark, ...lokaleTokens(accordeurCss, ".acc[data-thema='licht']") }

type Paar = [string, string]

/* ---------- Kantoor-console ---------- */

const KANTOOR_TEKST: Paar[] = [
  // basistekst op de drie vlakken
  ['text', 'bg'],
  ['text', 'panel'],
  ['text', 'panel-2'],
  ['muted', 'bg'],
  ['muted', 'panel'],
  ['muted', 'panel-2'],
  // faint = kolomkoppen/sectielabels (≥ 11px, vet) — als tekst getoetst
  ['faint', 'panel'],
  ['faint', 'bg'],
  // acties: primaire knop, links/actieve nav-tekst op vlakken, accent-chip
  ['primary-fg', 'primary'],
  ['primary', 'panel'],
  ['primary', 'bg'],
  ['primary', 'accent-bg'],
  // status-/signaalkleuren als tekst op scherm en paneel én op de eigen chip-tint
  ['ok', 'panel'],
  ['ok', 'bg'],
  ['ok', 'ok-bg'],
  ['warn', 'panel'],
  ['warn', 'bg'],
  ['warn', 'warn-bg'],
  ['danger', 'panel'],
  ['danger', 'bg'],
  ['danger', 'danger-bg'],
  ['danger-fg', 'danger'],
  ['info', 'panel'],
  ['info', 'bg'],
  ['info', 'info-bg'],
  ['purple', 'panel'],
  ['purple', 'bg'],
  ['purple', 'purple-bg'],
  // inkt-zijbalk: itemtekst, sectiekoppen, actief item, teller-badge
  ['rail-text', 'rail'],
  ['rail-muted', 'rail'],
  ['rail-text', 'rail-actief'],
  ['rail-accent', 'rail-actief'],
  ['rail-accent', 'rail-teller-bg'],
]

// Chip-tinten en status-stippen tegen hun vlak (niet-tekst → 3:1), plus de rail-accent-balk.
const KANTOOR_ICOON: Paar[] = [
  ['ok', 'panel'],
  ['warn', 'panel'],
  ['danger', 'panel'],
  ['info', 'panel'],
  ['purple', 'panel'],
  ['primary', 'panel'],
  ['rail-accent', 'rail'],
  ['primary', 'bg'],
]

/* ---------- Accordeur-/native-app ---------- */

const ACC_TEKST: Paar[] = [
  ['acc-text', 'acc-bg'],
  ['acc-text', 'acc-panel'],
  ['acc-muted', 'acc-bg'],
  ['acc-muted', 'acc-panel'],
  // acties: primaire knop (teal), terug-link/actieve tab op vlak en accent-chip
  ['acc-accent-fg', 'acc-accent'],
  ['acc-accent', 'acc-panel'],
  ['acc-accent', 'acc-bg'],
  ['acc-accent', 'acc-blue-bg'],
  // status/signaal op vlak + op eigen chip-tint
  ['acc-green', 'acc-panel'],
  ['acc-green', 'acc-green-bg'],
  ['acc-orange', 'acc-panel'],
  ['acc-orange', 'acc-orange-bg'],
  ['acc-red', 'acc-panel'],
  ['acc-red', 'acc-red-bg'],
  ['acc-red-fg', 'acc-red'],
  ['acc-purple', 'acc-panel'],
  ['acc-purple', 'acc-purple-bg'],
  ['acc-purple-fg', 'acc-purple'],
]

const ACC_ICOON: Paar[] = [
  ['acc-green', 'acc-panel'],
  ['acc-orange', 'acc-panel'],
  ['acc-red', 'acc-panel'],
  ['acc-accent', 'acc-panel'],
]

// App-chrome is modus-invariant donker (header + toast): alleen de dark-set telt.
const ACC_HEADER: Paar[] = [
  ['acc-head-text', 'acc-head-1'],
  ['acc-head-text', 'acc-head-2'],
  ['acc-head-muted', 'acc-head-1'],
  ['acc-accent', 'acc-head-1'],
  ['acc-viewer-text', 'acc-viewer-bg'],
]

function toets(tokens: Record<string, string>, modus: string, paren: Paar[], eis: number) {
  for (const [voor, achter] of paren) {
    const voorHex = tokens[voor]
    const achterHex = tokens[achter]
    expect(voorHex, `token --${voor} ontbreekt in ${modus}`).toBeTruthy()
    expect(achterHex, `token --${achter} ontbreekt in ${modus}`).toBeTruthy()
    const ratio = contrastRatio(voorHex, achterHex)
    expect(
      ratio,
      `${modus}: --${voor} (${voorHex}) op --${achter} (${achterHex}) = ${ratio.toFixed(2)}:1, eis ${eis}:1`,
    ).toBeGreaterThanOrEqual(eis)
  }
}

describe('contrast-audit kleurtokens — kantoor-console (licht + donker)', () => {
  it('rekent de WCAG-voorbeelden na (sanity op de pure functies)', () => {
    expect(relatieveLuminantie('#ffffff')).toBeCloseTo(1, 5)
    expect(relatieveLuminantie('#000000')).toBeCloseTo(0, 5)
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 2)
    expect(contrastRatio('#777777', '#ffffff')).toBeCloseTo(4.48, 1)
    expect(hexNaarRgb('#fff')).toEqual({ r: 255, g: 255, b: 255 })
    expect(blend('#ffffff', 0.5, '#000000')).toBe('#808080')
  })

  it('leest de v2-fundering uit tokens.css (bewaakt tegen stille terugval naar de groenzweem)', () => {
    expect(lichtTokens.primary).toBe('#0e7a6e')
    expect(lichtTokens.bg).toBe('#f6f7f8')
    expect(darkTokens.bg).toBe('#0b0d0e')
    expect(darkTokens.panel).toBe('#151719')
    // Dark hergebruikt geen licht-waarden voor vlakken/randen (Vastly-les 24-08).
    for (const naam of ['bg', 'panel', 'panel-2', 'border', 'text', 'muted', 'primary', 'rail']) {
      expect(darkTokens[naam], `--${naam} dark ≠ licht`).not.toBe(lichtTokens[naam])
    }
  })

  it('licht: alle tekstparen ≥ 4,5:1', () => toets(lichtTokens, 'licht', KANTOOR_TEKST, 4.5))
  it('licht: chip-/icoonparen ≥ 3:1', () => toets(lichtTokens, 'licht', KANTOOR_ICOON, 3))
  it('donker: alle tekstparen ≥ 4,5:1', () => toets(darkTokens, 'donker', KANTOOR_TEKST, 4.5))
  it('donker: chip-/icoonparen ≥ 3:1', () => toets(darkTokens, 'donker', KANTOOR_ICOON, 3))

  it('avatar-set: wit initialenopschrift ≥ 4,5:1 op alle acht kleuren', () => {
    for (let i = 0; i < 8; i++) {
      const kleur = lichtTokens[`avatar-${i}`]
      expect(kleur, `--avatar-${i} ontbreekt`).toBeTruthy()
      const ratio = contrastRatio('#ffffff', kleur)
      expect(ratio, `wit op --avatar-${i} (${kleur}) = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('rail-teller-bg is de 22%-blend van rail-accent over rail (mockup color-mix), beide modi', () => {
    for (const [modus, t] of [
      ['licht', lichtTokens],
      ['donker', darkTokens],
    ] as const) {
      const verwacht = blend(t['rail-accent'], 0.22, t.rail)
      // ±1 per kanaal speling voor afronding
      const a = hexNaarRgb(verwacht)
      const b = hexNaarRgb(t['rail-teller-bg'])
      expect(Math.abs(a.r - b.r) + Math.abs(a.g - b.g) + Math.abs(a.b - b.b), `${modus}: ${t['rail-teller-bg']} vs ${verwacht}`).toBeLessThanOrEqual(3)
    }
  })

  it('geboekt-chip (14% muted over panel) blijft leesbaar in beide modi', () => {
    for (const [modus, t] of [
      ['licht', lichtTokens],
      ['donker', darkTokens],
    ] as const) {
      const vlak = blend(t.muted, 0.14, t.panel)
      const ratio = contrastRatio(t.muted, vlak)
      expect(ratio, `${modus}: muted op geboekt-chip (${vlak}) = ${ratio.toFixed(2)}:1`).toBeGreaterThanOrEqual(4.5)
    }
  })
})

describe('contrast-audit kleurtokens — accordeur-/native-app (donker default + licht)', () => {
  it('leest de grafiet-fundering uit accordeur.css (geen groenzweem, eigen hexen)', () => {
    expect(accDark['acc-bg']).toBe('#0b0d0e')
    expect(accDark['acc-accent']).toBe('#3ec9b8')
    for (const naam of ['acc-bg', 'acc-panel', 'acc-border', 'acc-text', 'acc-muted', 'acc-accent']) {
      expect(accLicht[naam], `--${naam} licht ≠ donker`).not.toBe(accDark[naam])
    }
  })

  it('donker: alle tekstparen ≥ 4,5:1', () => toets(accDark, 'acc-donker', ACC_TEKST, 4.5))
  it('donker: chip-/icoonparen ≥ 3:1', () => toets(accDark, 'acc-donker', ACC_ICOON, 3))
  it('licht: alle tekstparen ≥ 4,5:1', () => toets(accLicht, 'acc-licht', ACC_TEKST, 4.5))
  it('licht: chip-/icoonparen ≥ 3:1', () => toets(accLicht, 'acc-licht', ACC_ICOON, 3))
  it('app-chrome (modus-invariant donker): header-/toast-/viewer-tekst ≥ 4,5:1', () =>
    toets(accDark, 'acc-header', ACC_HEADER, 4.5))
})
