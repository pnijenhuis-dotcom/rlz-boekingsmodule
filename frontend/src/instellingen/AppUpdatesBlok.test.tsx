import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppUpdatesBlok } from './AppUpdatesBlok'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('AppUpdatesBlok (OTA 16-09)', () => {
  let puts: { url: string; body: unknown }[]
  beforeEach(() => {
    puts = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (init?.method === 'PUT') {
          puts.push({ url, body: JSON.parse(String(init.body)) })
          if (url.endsWith('/instellingen/app-updates')) return Promise.resolve(jsonResponse({ percentage: 50, uitgeschakeld: true, env_uitgeschakeld: false, min_runtime_versie: '1.1' }))
          return Promise.resolve(jsonResponse({ bundel_id: 'b-1', runtime: '1.1', platform: 'alle', sha256: 'x', bytes: 1, verplicht: false, actief: false, aangemaakt_op: '2026-09-17T01:00:00' }))
        }
        if (url.endsWith('/instellingen/app-updates')) return Promise.resolve(jsonResponse({ percentage: 100, uitgeschakeld: false, env_uitgeschakeld: false, min_runtime_versie: '1.1' }))
        if (url.endsWith('/instellingen/app-updates/bundels'))
          return Promise.resolve(
            jsonResponse([
              { bundel_id: 'b-1', runtime: '1.1', platform: 'alle', sha256: 'x', bytes: 1, verplicht: false, actief: true, aangemaakt_op: '2026-09-17T01:00:00' },
              { bundel_id: 'b-0', runtime: '1.1', platform: 'alle', sha256: 'y', bytes: 1, verplicht: true, actief: true, aangemaakt_op: '2026-09-16T01:00:00' },
            ]),
          )
        if (url.endsWith('/instellingen/app-updates/toestellen'))
          return Promise.resolve(jsonResponse([{ apparaat_id: 't1', apparaat_naam: 'iPhone Peter', platform: 'ios', app_versie: '1.2', bundel_id: 'b-1', bundel_gezien_op: '2026-09-17T02:00:00', laatst_gebruikt_op: null }]))
        return Promise.resolve(jsonResponse({ detail: `onverwacht: ${url}` }, 500))
      }),
    )
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('toont bundels (nieuwste actief), toestellen en de noodrem; wijzigingen vragen bevestiging en gaan als PUT', async () => {
    render(<AppUpdatesBlok />)
    expect(await screen.findByText('actief — wordt uitgedeeld')).toBeInTheDocument()
    expect(screen.getByText('ouder')).toBeInTheDocument()
    expect(screen.getByText('verplicht')).toBeInTheDocument()
    expect(screen.getByText('iPhone Peter')).toBeInTheDocument()
    expect(screen.getByText('updates aan')).toBeInTheDocument()
    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getByLabelText('Live updates uitgeschakeld (noodrem)'))
    expect(screen.getByText(/Live updates worden UITGEZET/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: /^Bevestigen$/ }))
    await waitFor(() => expect(puts).toEqual([{ url: '/instellingen/app-updates', body: { uitgeschakeld: true } }]))
    await gebruiker.click(screen.getAllByRole('button', { name: 'Terugtrekken…' })[0])
    await gebruiker.click(screen.getByRole('button', { name: /^Bevestigen$/ }))
    await waitFor(() => expect(puts[1]).toEqual({ url: '/instellingen/app-updates/bundels/b-1', body: { actief: false } }))
  })
})
