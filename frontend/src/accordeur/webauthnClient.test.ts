// Kliktest 2026-08-12: de activatie hing oneindig op "Bezig…" doordat de backend niet
// antwoordde. De passkey-submits lopen daarom via kaleAuthFetch — een dode/trage backend
// wordt binnen de timeout een nette onbereikbaar-melding die de schermen als foutregel tonen.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BACKEND_ONBEREIKBAAR_MELDING, REQUEST_TIMEOUT_MS } from '../api/client'
import { loginVoltooien, ontgrendelen, registratieVoltooien } from './webauthnClient'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

/** Stub die, net als echte fetch, nooit resolvet en pas faalt wanneer het AbortSignal afgaat. */
function stubHangendeFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('afgebroken', 'AbortError')))
        }),
    ),
  )
}

describe('accordeur-passkey-submits — nooit oneindig "Bezig…"', () => {
  it.each([
    ['registratie voltooien', () => registratieVoltooien('setup-tok', { dev_stub: true, apparaat_naam: 'test' })],
    ['login voltooien', () => loginVoltooien('setup-tok', { dev_stub: true })],
    ['ontgrendelen', () => ontgrendelen({ dev_stub: true })],
  ])('%s geeft na de timeout de onbereikbaar-melding', async (_naam, roep) => {
    stubHangendeFetch()

    const belofte = roep()
    const verwachting = expect(belofte).rejects.toThrow(BACKEND_ONBEREIKBAAR_MELDING)
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS + 100)
    await verwachting
  })
})
