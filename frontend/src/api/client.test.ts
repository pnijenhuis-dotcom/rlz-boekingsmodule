import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiJson, BACKEND_ONBEREIKBAAR_MELDING, BackendOnbereikbaarError, setAccessToken } from './client'

describe('apiJson — backend onbereikbaar', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    setAccessToken(null)
  })

  it('vertaalt een 502 (dev-proxy kan de backend niet bereiken) naar een nette melding', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(null, { status: 502, statusText: 'Bad Gateway' }))),
    )

    await expect(apiJson('/administraties')).rejects.toMatchObject({
      message: BACKEND_ONBEREIKBAAR_MELDING,
    })
  })

  it('vertaalt een echte netwerkfout (fetch gooit) naar dezelfde melding', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))),
    )

    await expect(apiJson('/administraties')).rejects.toBeInstanceOf(BackendOnbereikbaarError)
  })

  it('laat een gewone 404 van de backend zelf ongewijzigd door (geen onbereikbaarheids-melding)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: 'Onbekend document' }), { status: 404 }))),
    )

    await expect(apiJson('/administraties/x/documenten/y')).rejects.toMatchObject({
      message: 'Onbekend document',
    })
  })
})

describe('ApiError', () => {
  it('BackendOnbereikbaarError is een ApiError met status 0', () => {
    const err = new BackendOnbereikbaarError()
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(0)
  })
})
