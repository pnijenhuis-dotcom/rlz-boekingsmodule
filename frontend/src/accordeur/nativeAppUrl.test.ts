// Universal-link-vertaling (pincode-activatie 31-08): alleen /accordeur- en /activeren-paden,
// /activeren?token= → de in-app-activatieroute (?uitnodiging=) — zelfde vertaling als het
// kantoor-/activeren-scherm.

import { afterEach, describe, expect, it, vi } from 'vitest'
import { inAppPadVoorUrl, installeerNativeUrlAfhandeling } from './nativeAppUrl'

const BASIS = 'https://app.administratiekantoornijenhuis.nl'

describe('inAppPadVoorUrl', () => {
  it('vertaalt de activatielink naar de in-app-route', () => {
    expect(inAppPadVoorUrl(`${BASIS}/activeren?token=abc%2F123`)).toBe('/accordeur/activeren?uitnodiging=abc%2F123')
    expect(inAppPadVoorUrl(`${BASIS}/activeren?token=abc&herstel=1`)).toBe(
      '/accordeur/activeren?uitnodiging=abc&herstel=1',
    )
    expect(inAppPadVoorUrl(`${BASIS}/activeren`)).toBe('/accordeur/activeren')
  })

  it('laat accordeur-deep-links door mét querystring', () => {
    expect(inAppPadVoorUrl(`${BASIS}/accordeur?document=42`)).toBe('/accordeur?document=42')
    expect(inAppPadVoorUrl(`${BASIS}/accordeur/activeren?uitnodiging=x`)).toBe('/accordeur/activeren?uitnodiging=x')
  })

  it('negeert alles daarbuiten (hard principe: de app-lock/auth-cadans blijft de poort)', () => {
    expect(inAppPadVoorUrl(`${BASIS}/`)).toBeNull()
    expect(inAppPadVoorUrl(`${BASIS}/instellingen`)).toBeNull()
    expect(inAppPadVoorUrl(`${BASIS}/accordeurtje`)).toBeNull()
    expect(inAppPadVoorUrl('geen-url')).toBeNull()
  })
})

/** Blok E1 (06-09): de listener leeft in @capacitor/app — ontbreekt die plugin in een native
 * build, dan is dat luid (console.warn) i.p.v. stil; de koude start krijgt getLaunchUrl als
 * tweede vangnet, en dezelfde URL leidt nooit tot twee navigaties. */
describe('installeerNativeUrlAfhandeling', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('web: no-op, geen waarschuwing', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const nav = vi.fn()
    installeerNativeUrlAfhandeling(nav)
    expect(nav).not.toHaveBeenCalled()
    expect(warn).not.toHaveBeenCalled()
    warn.mockRestore()
  })

  it('native zónder App-plugin: waarschuwt zichtbaar (de casus van 04-09), navigeert niet', () => {
    vi.stubGlobal('Capacitor', { isNativePlatform: () => true, Plugins: {} })
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    installeerNativeUrlAfhandeling(vi.fn())
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('@capacitor/app ontbreekt'))
    warn.mockRestore()
  })

  it('native mét App-plugin: appUrlOpen én getLaunchUrl vertalen de link — dezelfde URL één keer', async () => {
    let listener: ((d: { url?: string }) => void) | null = null
    const url = `${BASIS}/activeren?token=abc`
    vi.stubGlobal('Capacitor', {
      isNativePlatform: () => true,
      Plugins: {
        App: {
          addListener: (_naam: string, cb: (d: { url?: string }) => void) => {
            listener = cb
            return {}
          },
          getLaunchUrl: () => Promise.resolve({ url }),
        },
      },
    })
    const nav = vi.fn()
    installeerNativeUrlAfhandeling(nav)
    listener!({ url })
    await new Promise((r) => setTimeout(r, 0))
    expect(nav).toHaveBeenCalledTimes(1)
    expect(nav).toHaveBeenCalledWith('/accordeur/activeren?uitnodiging=abc')
    // Een tweede, andere link (bv. een push-deep-link later) navigeert gewoon.
    listener!({ url: `${BASIS}/accordeur?document=7` })
    expect(nav).toHaveBeenCalledWith('/accordeur?document=7')
    // Buiten de app-paden: genegeerd.
    listener!({ url: `${BASIS}/instellingen` })
    expect(nav).toHaveBeenCalledTimes(2)
  })
})
