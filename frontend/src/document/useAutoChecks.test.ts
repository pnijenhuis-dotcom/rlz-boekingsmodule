import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAutoChecks } from './useAutoChecks'

/** Boeken sneller (Peter 18-09, stap 1.5): lokale checks direct ná de debounce (400 ms), externe run alleen als de
 * externe vingerafdruk (crediteur/referentie/datum/totaal) verandert; `checksBezig` splitst in lokaal/extern. */
describe('useAutoChecks — lokaal direct, extern alleen bij vingerafdruk-wijziging', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  function opzet(vingerafdruk: string) {
    const bijOpenen = vi.fn(() => Promise.resolve())
    const bijWijziging = vi.fn(() => Promise.resolve())
    const bijExtern = vi.fn(() => Promise.resolve())
    const hook = renderHook(
      ({ versie, vf }: { versie: number; vf: string }) =>
        useAutoChecks({ actief: true, wijzigingsVersie: versie, bijOpenen, bijWijziging, bijExtern, externeVingerafdruk: vf }),
      { initialProps: { versie: 0, vf: vingerafdruk } },
    )
    return { hook, bijOpenen, bijWijziging, bijExtern }
  }

  it('draait bij openen één keer (lokaal + extern in één) en onthoudt de vingerafdruk', async () => {
    const { bijOpenen, bijWijziging, bijExtern } = opzet('v1|F-1|2026-07-01|121.00')
    await act(async () => {})
    expect(bijOpenen).toHaveBeenCalledTimes(1)
    expect(bijWijziging).not.toHaveBeenCalled()
    expect(bijExtern).not.toHaveBeenCalled()
  })

  it('een wijziging die de vingerafdruk NIET raakt (omschrijving/grootboek/btw) draait alleen de lokale run', async () => {
    const { hook, bijWijziging, bijExtern } = opzet('v1|F-1|2026-07-01|121.00')
    await act(async () => {})
    hook.rerender({ versie: 1, vf: 'v1|F-1|2026-07-01|121.00' })
    await act(async () => {
      vi.advanceTimersByTime(399)
    })
    expect(bijWijziging).not.toHaveBeenCalled() // debounce 400 ms
    await act(async () => {
      vi.advanceTimersByTime(1)
    })
    await act(async () => {})
    expect(bijWijziging).toHaveBeenCalledTimes(1)
    expect(bijExtern).not.toHaveBeenCalled()
  })

  it('een wijziging van referentie/totaal draait ná de lokale run óók de externe run — één keer per vingerafdruk', async () => {
    const { hook, bijWijziging, bijExtern } = opzet('v1|F-1|2026-07-01|121.00')
    await act(async () => {})
    hook.rerender({ versie: 1, vf: 'v1|F-2|2026-07-01|121.00' })
    await act(async () => {
      vi.advanceTimersByTime(400)
    })
    await act(async () => {})
    expect(bijWijziging).toHaveBeenCalledTimes(1)
    expect(bijExtern).toHaveBeenCalledTimes(1)
    // Nog een wijziging met dezelfde vingerafdruk → geen tweede externe run.
    hook.rerender({ versie: 2, vf: 'v1|F-2|2026-07-01|121.00' })
    await act(async () => {
      vi.advanceTimersByTime(400)
    })
    await act(async () => {})
    expect(bijWijziging).toHaveBeenCalledTimes(2)
    expect(bijExtern).toHaveBeenCalledTimes(1)
  })

  it('zonder bijExtern gedraagt de hook zich als vóór 18-09 (één run per wijziging)', async () => {
    const bijOpenen = vi.fn(() => Promise.resolve())
    const bijWijziging = vi.fn(() => Promise.resolve())
    const hook = renderHook(
      ({ versie }: { versie: number }) => useAutoChecks({ actief: true, wijzigingsVersie: versie, bijOpenen, bijWijziging }),
      { initialProps: { versie: 0 } },
    )
    await act(async () => {})
    hook.rerender({ versie: 1 })
    await act(async () => {
      vi.advanceTimersByTime(400)
    })
    await act(async () => {})
    expect(bijWijziging).toHaveBeenCalledTimes(1)
    expect(hook.result.current.externBezig).toBe(false)
  })
})
