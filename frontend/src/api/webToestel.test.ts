/** SPOED 18-09 — web-toestel: persistente opslag, weergavemodus, diagnose-staart, beginscherm-nudge. Alles lokaal. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  OPSLAG_GEWIST_MELDING,
  beginschermNudgeWeg,
  beginschermStappen,
  leesOpslagPersistent,
  noteerTokenVerlenging,
  toonBeginschermNudge,
  vraagPersistenteOpslag,
  webDiagnoseStaart,
  weergaveModus,
} from './webToestel'

// In-memory localStorage als de omgeving er geen bruikbare heeft (zelfde vangnet als appSlot.test.ts).
function polyfillStorage(naam: 'localStorage' | 'sessionStorage'): void {
  const huidig = (globalThis as Record<string, unknown>)[naam] as Storage | undefined
  if (huidig && typeof huidig.getItem === 'function') return
  const kv = new Map<string, string>()
  Object.defineProperty(globalThis, naam, {
    configurable: true,
    value: {
      getItem: (k: string) => kv.get(k) ?? null,
      setItem: (k: string, v: string) => void kv.set(k, String(v)),
      removeItem: (k: string) => void kv.delete(k),
      clear: () => kv.clear(),
    },
  })
}
polyfillStorage('localStorage')

beforeEach(() => {
  delete (globalThis as { Capacitor?: unknown }).Capacitor
  localStorage.clear()
})

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  delete (globalThis as { Capacitor?: unknown }).Capacitor
})

describe('webToestel', () => {
  it('persistente opslag: persist() true → ja, false → nee, ontbreekt → onbekend; uitkomst lokaal bewaard', async () => {
    Object.defineProperty(navigator, 'storage', { value: { persist: async () => true }, configurable: true })
    expect(await vraagPersistenteOpslag()).toBe('ja')
    expect(leesOpslagPersistent()).toBe('ja')
    Object.defineProperty(navigator, 'storage', { value: { persist: async () => false }, configurable: true })
    expect(await vraagPersistenteOpslag()).toBe('nee')
    Object.defineProperty(navigator, 'storage', { value: undefined, configurable: true })
    expect(await vraagPersistenteOpslag()).toBe('onbekend')
  })

  it('al persistent (persisted() true) hoeft niet opnieuw gevraagd te worden', async () => {
    const persist = vi.fn(async () => false)
    Object.defineProperty(navigator, 'storage', { value: { persisted: async () => true, persist }, configurable: true })
    expect(await vraagPersistenteOpslag()).toBe('ja')
    expect(persist).not.toHaveBeenCalled()
  })

  it('weergavemodus: browsertab standaard, PWA bij display-mode standalone, native bij Capacitor', () => {
    expect(weergaveModus()).toBe('browser')
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('standalone') }))
    expect(weergaveModus()).toBe('pwa')
    vi.stubGlobal('Capacitor', { isNativePlatform: () => true })
    expect(weergaveModus()).toBe('native')
  })

  it('diagnose-staart noemt modus, opslag en laatste tokenverlenging (of "nog geen")', () => {
    expect(webDiagnoseStaart()).toBe(' · modus: browsertab · opslag persistent: niet gevraagd · laatste tokenverlenging: nog geen')
    localStorage.setItem('accordeur-opslag-persistent', 'nee')
    noteerTokenVerlenging(new Date(2026, 8, 18, 9, 24))
    expect(webDiagnoseStaart()).toBe(' · modus: browsertab · opslag persistent: nee · laatste tokenverlenging: 18-09 09:24')
  })

  it('beginscherm-nudge alleen in een browsertab en tot "niet meer tonen"; stappen per browser', () => {
    expect(toonBeginschermNudge()).toBe(true)
    beginschermNudgeWeg()
    expect(toonBeginschermNudge()).toBe(false)
    localStorage.clear()
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('standalone') }))
    expect(toonBeginschermNudge()).toBe(false)
    expect(beginschermStappen('Mozilla/5.0 (X11; Linux x86_64) Chrome/139 Safari/537.36 Edg/139.0.3405.102')).toContain('Edge')
    expect(beginschermStappen('Mozilla/5.0 (Linux; Android 10; K) Chrome/153 Mobile Safari/537.36')).toContain('Chrome')
    expect(beginschermStappen('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari')).toContain('Safari')
  })

  it('de melding bij gewiste opslag zegt wat er gebeurde en wat je doet (geen stil uitloggen)', () => {
    expect(OPSLAG_GEWIST_MELDING).toMatch(/niet meer gekoppeld/)
    expect(OPSLAG_GEWIST_MELDING).toMatch(/koppelcode van een ander toestel/)
    expect(OPSLAG_GEWIST_MELDING).toMatch(/herstel-link/)
    expect(OPSLAG_GEWIST_MELDING).toMatch(/beginscherm/)
  })
})
