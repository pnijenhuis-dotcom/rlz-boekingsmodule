/** SPOED 18-09 — Android-terugknop in de web-flow: popstate verlaat de app niet, maar wordt `acc-terug`. */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ACC_TERUG_EVENT, installeerAndroidTerugVal } from './androidTerug'

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  delete (globalThis as { Capacitor?: unknown }).Capacitor
})

describe('installeerAndroidTerugVal', () => {
  it('zet één history-entry bij binnenkomst en vertaalt elke popstate naar acc-terug mét een nieuwe entry', () => {
    const push = vi.spyOn(window.history, 'pushState')
    const ontvangen: number[] = []
    const op = () => ontvangen.push(1)
    window.addEventListener(ACC_TERUG_EVENT, op)
    const weg = installeerAndroidTerugVal()
    expect(push).toHaveBeenCalledTimes(1)
    window.dispatchEvent(new PopStateEvent('popstate'))
    window.dispatchEvent(new PopStateEvent('popstate'))
    expect(ontvangen.length).toBe(2)
    expect(push).toHaveBeenCalledTimes(3) // 1 bij binnenkomst + 1 per terugknop
    weg()
    window.dispatchEvent(new PopStateEvent('popstate'))
    expect(ontvangen.length).toBe(2)
    window.removeEventListener(ACC_TERUG_EVENT, op)
  })

  it('native (Capacitor) slaat de val over — de schil heeft zijn eigen backButton-afhandeling', () => {
    vi.stubGlobal('Capacitor', { isNativePlatform: () => true })
    const push = vi.spyOn(window.history, 'pushState')
    installeerAndroidTerugVal()
    expect(push).not.toHaveBeenCalled()
  })
})
