// OTA (16-09): manifest alleen voor de eigen runtime, 15-minutengrens, download → next / verplicht → set mét melding,
// rollback-melding naar de server, buiten de schil een no-op; Android in-app-update alleen mét plugin.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { APP_MARKETING_VERSIE } from './appVersie'
import {
  OTA_LAATSTE_CHECK_SLEUTEL,
  OTA_VERPLICHT_MELDING,
  androidInAppUpdate,
  bekendeBundelId,
  controleerOta,
  huidigeBundelId,
  meldRollback,
  otaBijStart,
  resetOtaVoorTests,
} from './ota'

const opslag = new Map<string, string>()
beforeAll(() => {
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: {
      getItem: (k: string) => opslag.get(k) ?? null,
      setItem: (k: string, v: string) => void opslag.set(k, String(v)),
      removeItem: (k: string) => void opslag.delete(k),
      clear: () => opslag.clear(),
    },
  })
})

function plugin(overrides: Record<string, unknown> = {}, platform = 'ios') {
  const download = vi.fn(async (o: { version: string }) => ({ id: `id-${o.version}`, version: o.version }))
  const next = vi.fn(async () => undefined)
  const set = vi.fn(async () => undefined)
  const notifyAppReady = vi.fn(async () => undefined)
  const luisteraars: Record<string, (i: unknown) => void> = {}
  const addListener = vi.fn((naam: string, cb: (i: unknown) => void) => {
    luisteraars[naam] = cb
    return { remove: () => undefined }
  })
  const p = { getCurrent: async () => ({ bundle: { id: 'b0', version: 'builtin' } }), download, next, set, notifyAppReady, addListener, ...overrides }
  ;(window as { Capacitor?: unknown }).Capacitor = { isNativePlatform: () => true, getPlatform: () => platform, Plugins: { CapacitorUpdater: p } }
  return { download, next, set, notifyAppReady, addListener, luisteraars }
}

function fetchMock(body: unknown, status = 200) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

beforeEach(() => {
  resetOtaVoorTests()
  opslag.clear()
})
afterEach(() => {
  delete (window as { Capacitor?: unknown }).Capacitor
  vi.unstubAllGlobals()
})

describe('controleerOta', () => {
  it('buiten de schil: geen plugin, niets gebeurt', async () => {
    vi.stubGlobal('fetch', fetchMock({}))
    expect(await controleerOta()).toEqual({ stand: 'geen_plugin' })
    expect(fetch).not.toHaveBeenCalled()
    expect(await huidigeBundelId()).toBeNull()
  })

  it('vraagt het manifest voor de eigen runtime en zet de bundel klaar voor de volgende start', async () => {
    const p = plugin()
    const f = fetchMock({ geen_update: false, bundel_id: 'b-1', url: 'https://x/app/bundels/b-1.zip', sha256: 'ab'.repeat(32), verplicht: false, runtime: APP_MARKETING_VERSIE })
    vi.stubGlobal('fetch', f)
    const u = await controleerOta({ forceer: true })
    expect(u).toEqual({ stand: 'gedownload', bundel: 'b-1' })
    const url = String((f.mock.calls[0] as unknown[])[0])
    expect(url).toContain(`runtime=${encodeURIComponent(APP_MARKETING_VERSIE)}`)
    expect(url).toContain('platform=ios')
    expect(url).toContain('huidig=builtin')
    expect(p.download).toHaveBeenCalledWith({ url: 'https://x/app/bundels/b-1.zip', version: 'b-1', checksum: 'ab'.repeat(32) })
    expect(p.next).toHaveBeenCalledWith({ id: 'id-b-1' })
    expect(p.set).not.toHaveBeenCalled()
    expect(bekendeBundelId()).toBe('builtin')
    expect(opslag.get(OTA_LAATSTE_CHECK_SLEUTEL)).toBeTruthy()
  })

  it('verplicht = direct toepassen mét melding', async () => {
    const p = plugin()
    vi.stubGlobal('fetch', fetchMock({ geen_update: false, bundel_id: 'b-v', url: 'https://x/b-v.zip', sha256: 'cd'.repeat(32), verplicht: true }))
    const melding = vi.fn()
    expect(await controleerOta({ forceer: true, melding })).toEqual({ stand: 'toegepast', bundel: 'b-v' })
    expect(melding).toHaveBeenCalledWith(OTA_VERPLICHT_MELDING)
    expect(p.set).toHaveBeenCalledWith({ id: 'id-b-v' })
    expect(p.next).not.toHaveBeenCalled()
  })

  it('weigert een bundel van een andere runtime en respecteert geen_update', async () => {
    const p = plugin()
    vi.stubGlobal('fetch', fetchMock({ geen_update: false, bundel_id: 'b-2', url: 'https://x/b-2.zip', runtime: '9.9' }))
    expect((await controleerOta({ forceer: true })).stand).toBe('geen_update')
    expect(p.download).not.toHaveBeenCalled()
    vi.stubGlobal('fetch', fetchMock({ geen_update: true, reden: 'uitgeschakeld' }))
    expect(await controleerOta({ forceer: true })).toEqual({ stand: 'geen_update', reden: 'uitgeschakeld' })
  })

  it('niet vaker dan eens per 15 minuten; fouten zijn zacht', async () => {
    plugin()
    const f = fetchMock({ geen_update: true, reden: 'actueel' })
    vi.stubGlobal('fetch', f)
    await controleerOta({ forceer: true })
    expect(await controleerOta()).toEqual({ stand: 'te_vroeg' })
    expect(f).toHaveBeenCalledTimes(1)
    vi.stubGlobal('fetch', fetchMock({ detail: 'kapot' }, 500))
    expect((await controleerOta({ forceer: true })).stand).toBe('fout')
  })
})

describe('otaBijStart + rollback', () => {
  it('meldt appReady, luistert op updateFailed en stuurt de rollback naar de server', async () => {
    const p = plugin()
    const f = fetchMock({ geen_update: true, reden: 'actueel' })
    vi.stubGlobal('fetch', f)
    await otaBijStart()
    await new Promise((r) => setTimeout(r, 10)) // de startcheck (void) rondt af op de manifest-mock
    expect(p.notifyAppReady).toHaveBeenCalled()
    expect(p.addListener).toHaveBeenCalledWith('updateFailed', expect.any(Function))
    expect(String((f.mock.calls[0] as unknown[])[0])).toContain('/app/update-manifest')
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 204 })))
    p.luisteraars.updateFailed({ bundle: { id: 'b-kapot', version: 'b-kapot' } })
    await new Promise((r) => setTimeout(r, 10))
    const laatste = (vi.mocked(fetch).mock.calls.at(-1) ?? []) as unknown[]
    expect(String(laatste[0])).toContain('/app/update-melding')
    expect(JSON.parse(String((laatste[1] as RequestInit).body))).toEqual({ bundel_id: 'b-kapot', reden: 'updateFailed', app_versie: APP_MARKETING_VERSIE })
    expect(await meldRollback('x', 'test')).toBe(true)
  })
})

describe('androidInAppUpdate', () => {
  it('alleen op Android mét plugin; immediate bij update beschikbaar', async () => {
    expect(await androidInAppUpdate('immediate')).toBe('geen_plugin')
    const perform = vi.fn(async () => undefined)
    ;(window as { Capacitor?: unknown }).Capacitor = {
      isNativePlatform: () => true,
      getPlatform: () => 'android',
      Plugins: { AppUpdate: { getAppUpdateInfo: async () => ({ updateAvailability: 2, immediateUpdateAllowed: true }), performImmediateUpdate: perform } },
    }
    expect(await androidInAppUpdate('immediate')).toBe('gestart')
    expect(perform).toHaveBeenCalled()
    // flexible: max 1× per 24 u
    expect(await androidInAppUpdate('flexible')).toBe('geen')
    ;(window as { Capacitor?: unknown }).Capacitor = {
      isNativePlatform: () => true,
      getPlatform: () => 'android',
      Plugins: { AppUpdate: { getAppUpdateInfo: async () => ({ updateAvailability: 1 }) } },
    }
    resetOtaVoorTests()
    expect(await androidInAppUpdate('flexible')).toBe('geen')
  })
})
