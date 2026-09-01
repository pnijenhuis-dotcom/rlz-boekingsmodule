// App-icoon-badge (D4, 01-09): native plugin eerst, anders de Badging API; fail-stil zonder ondersteuning.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { zetAppBadge } from './appBadge'

describe('zetAppBadge', () => {
  afterEach(() => {
    delete (window as { Capacitor?: unknown }).Capacitor
    vi.unstubAllGlobals()
  })

  it('native: roept AppSlot.zetBadge aan met het (niet-negatieve, gehele) aantal', async () => {
    const zetBadge = vi.fn().mockResolvedValue(undefined)
    ;(window as { Capacitor?: unknown }).Capacitor = { isNativePlatform: () => true, Plugins: { AppSlot: { zetBadge } } }
    await zetAppBadge(3)
    await zetAppBadge(-2.7)
    expect(zetBadge.mock.calls).toEqual([[{ aantal: 3 }], [{ aantal: 0 }]])
  })

  it('web: Badging API — setAppBadge(n) of clearAppBadge() bij 0', async () => {
    const setAppBadge = vi.fn().mockResolvedValue(undefined)
    const clearAppBadge = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, setAppBadge, clearAppBadge })
    await zetAppBadge(5)
    await zetAppBadge(0)
    expect(setAppBadge).toHaveBeenCalledWith(5)
    expect(clearAppBadge).toHaveBeenCalledTimes(1)
  })

  it('zonder ondersteuning of bij een fout: stil', async () => {
    vi.stubGlobal('navigator', { ...navigator, setAppBadge: () => Promise.reject(new Error('nee')) })
    await expect(zetAppBadge(1)).resolves.toBeUndefined()
    vi.stubGlobal('navigator', {})
    await expect(zetAppBadge(1)).resolves.toBeUndefined()
  })
})
