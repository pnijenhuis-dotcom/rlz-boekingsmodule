// Native-push-seam (store-app fase 3): plugin-detectie (fail-closed), het device-token-
// event als belofte (nooit eeuwig "Bezig…"), het native meldingenpad in pushClient
// (registreren/intrekken via /notificaties/push/subscripties/native) en de tap-afhandeling
// (alleen /accordeur-deep-links).

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { haalDeviceToken, installeerNativeTapAfhandeling, nativePushPlugin, nativePushSoort } from './nativePush'
import { haalMeldingenStatus, zetMeldingenAan, zetMeldingenUit } from './pushClient'

type Listener = (payload: unknown) => void

/** Werkende fake van @capacitor/push-notifications: permissies + registration-event. */
function maakFakePlugin(
  overrides: Partial<{ receive: 'prompt' | 'granted' | 'denied'; registerLevert: string | Error }> = {},
) {
  const listeners = new Map<string, Listener[]>()
  const plugin = {
    checkPermissions: vi.fn(() => Promise.resolve({ receive: overrides.receive ?? 'granted' })),
    requestPermissions: vi.fn(() => Promise.resolve({ receive: overrides.receive ?? 'granted' })),
    register: vi.fn(() => {
      const uitkomst = overrides.registerLevert ?? 'device-token-1'
      queueMicrotask(() => {
        if (uitkomst instanceof Error) {
          for (const l of listeners.get('registrationError') ?? []) l({ error: uitkomst.message })
        } else {
          for (const l of listeners.get('registration') ?? []) l({ value: uitkomst })
        }
      })
      return Promise.resolve()
    }),
    addListener: vi.fn((naam: string, listener: Listener) => {
      listeners.set(naam, [...(listeners.get(naam) ?? []), listener])
      return Promise.resolve({
        remove: () => {
          listeners.set(naam, (listeners.get(naam) ?? []).filter((l) => l !== listener))
          return Promise.resolve()
        },
      })
    }),
    _vuurTap: (payload: unknown) => {
      for (const l of listeners.get('pushNotificationActionPerformed') ?? []) l(payload)
    },
  }
  return plugin
}

function stubCapacitor(plugin: unknown, platform = 'ios') {
  vi.stubGlobal('Capacitor', {
    isNativePlatform: () => true,
    getPlatform: () => platform,
    Plugins: { PushNotifications: plugin },
  })
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

beforeEach(() => {
  // Deze jsdom-setup heeft geen localStorage — simpele in-memory variant (pushClient is
  // er zelf al defensief op, maar de aan-status-marker hoort in de tests wél te werken).
  const opslag = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => opslag.get(k) ?? null,
    setItem: (k: string, v: string) => void opslag.set(k, v),
    removeItem: (k: string) => void opslag.delete(k),
    clear: () => opslag.clear(),
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('nativePushPlugin — detectie en platform', () => {
  it('geeft null buiten de schil en bij een half plugin-oppervlak', () => {
    expect(nativePushPlugin()).toBeNull()
    stubCapacitor({ register: () => Promise.resolve() })
    expect(nativePushPlugin()).toBeNull()
  })

  it('kiest de adapter-soort op platform: ios → apns, anders fcm', () => {
    stubCapacitor(maakFakePlugin(), 'ios')
    expect(nativePushSoort()).toBe('apns')
    stubCapacitor(maakFakePlugin(), 'android')
    expect(nativePushSoort()).toBe('fcm')
  })
})

describe('haalDeviceToken', () => {
  it('levert het token uit het registration-event', async () => {
    const plugin = maakFakePlugin({ registerLevert: 'tok-42' })
    await expect(haalDeviceToken(plugin)).resolves.toBe('tok-42')
  })

  it('werkt óók als addListener een PLAIN handle teruggeeft (Capacitor bridge-shim, bug ".then is not a function" 26-08)', async () => {
    const plugin = maakFakePlugin({ registerLevert: 'tok-shim' })
    const listeners = new Map<string, Listener[]>()
    // de shim uit native-bridge.js: synchroon een { remove } zonder Promise
    plugin.addListener = vi.fn((naam: string, listener: Listener) => {
      listeners.set(naam, [...(listeners.get(naam) ?? []), listener])
      return { remove: () => Promise.resolve() }
    }) as never
    plugin.register = vi.fn(() => {
      queueMicrotask(() => {
        for (const l of listeners.get('registration') ?? []) l({ value: 'tok-shim' })
      })
      return Promise.resolve()
    })
    await expect(haalDeviceToken(plugin)).resolves.toBe('tok-shim')
  })

  it('faalt zichtbaar op een registratiefout — nooit eeuwig hangen', async () => {
    const plugin = maakFakePlugin({ registerLevert: new Error('APNS onbereikbaar') })
    await expect(haalDeviceToken(plugin)).rejects.toThrow('APNS onbereikbaar')
  })
})

describe('pushClient in de native schil', () => {
  it('meldingen aanzetten registreert het token bij de backend (soort per platform) → aan', async () => {
    stubCapacitor(maakFakePlugin({ registerLevert: 'apns-tok' }), 'ios')
    let verzonden: unknown = null
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
        expect(String(invoer)).toBe('/notificaties/push/subscripties/native')
        verzonden = JSON.parse(String(init?.body))
        return Promise.resolve(jsonResponse({ id: 'x', endpoint: 'apns-tok', aangemaakt_op: '' }, 201))
      }),
    )
    await expect(zetMeldingenAan()).resolves.toBe('aan')
    expect(verzonden).toEqual({ soort: 'apns', token: 'apns-tok' })
    await expect(haalMeldingenStatus()).resolves.toBe('aan')
  })

  it('server zonder native-push-config (409) → nette niet-geconfigureerd-status', async () => {
    stubCapacitor(maakFakePlugin(), 'android')
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse({ detail: 'Native push (fcm) is niet geconfigureerd' }, 409))),
    )
    await expect(zetMeldingenAan()).resolves.toBe('niet-geconfigureerd')
  })

  it('geweigerde permissie → geweigerd, geen registratie', async () => {
    const plugin = maakFakePlugin({ receive: 'denied' })
    stubCapacitor(plugin)
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    await expect(zetMeldingenAan()).resolves.toBe('geweigerd')
    expect(plugin.register).not.toHaveBeenCalled()
    expect(fetchSpy).not.toHaveBeenCalled()
    await expect(haalMeldingenStatus()).resolves.toBe('geweigerd')
  })

  it('meldingen uitzetten trekt het token server-side in en wist de lokale status', async () => {
    stubCapacitor(maakFakePlugin({ registerLevert: 'tok-uit' }), 'ios')
    const aanroepen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
        aanroepen.push(String(invoer))
        if (String(invoer).endsWith('/intrekken')) {
          expect(JSON.parse(String(init?.body))).toEqual({ endpoint: 'tok-uit' })
          return Promise.resolve(new Response(null, { status: 204 }))
        }
        return Promise.resolve(jsonResponse({ id: 'x', endpoint: 'tok-uit', aangemaakt_op: '' }, 201))
      }),
    )
    await zetMeldingenAan()
    await zetMeldingenUit()
    expect(aanroepen).toContain('/notificaties/push/subscripties/intrekken')
    await expect(haalMeldingenStatus()).resolves.toBe('uit')
  })
})

describe('tap-afhandeling', () => {
  it('opent alleen /accordeur-deep-links, al het andere wordt genegeerd', async () => {
    const plugin = maakFakePlugin()
    stubCapacitor(plugin)
    const navigeer = vi.fn()
    installeerNativeTapAfhandeling(navigeer)
    await Promise.resolve() // addListener is async
    plugin._vuurTap({ notification: { data: { url: '/accordeur?document=d1' } } })
    plugin._vuurTap({ notification: { data: { url: 'https://kwaadaardig.example/phish' } } })
    plugin._vuurTap({ notification: { data: {} } })
    expect(navigeer).toHaveBeenCalledTimes(1)
    expect(navigeer).toHaveBeenCalledWith('/accordeur?document=d1')
  })
})
