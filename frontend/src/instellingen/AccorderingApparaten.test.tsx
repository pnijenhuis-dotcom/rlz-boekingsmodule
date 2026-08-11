// Blok 4 accordeur-PWA: apparatenbeheer + kill-switch in Instellingen → accordering.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccorderingInstellingen } from './AccorderingInstellingen'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('AccorderingInstellingen — apparaten/kill-switch', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont per accordeur de geregistreerde apparaten en trekt in via de kill-switch', async () => {
    const ingetrokken: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
        const pad = String(invoer).split('?')[0]
        if (pad === '/administraties/a1/accordering/instellingen')
          return Promise.resolve(jsonResponse({ ingeschakeld: true, lagen: [] }))
        if (pad === '/administraties/a1/accordering/kandidaten')
          return Promise.resolve(jsonResponse({ kandidaten: [{ id: 'g1', naam: 'S. Bakker' }] }))
        if (pad === '/administraties/a1/accordering/staande-regels')
          return Promise.resolve(jsonResponse({ regels: [] }))
        if (pad === '/auth/gebruikers/g1/apparaten')
          return Promise.resolve(
            jsonResponse({
              apparaten: [
                {
                  id: 'ap1',
                  apparaat_naam: 'iPhone',
                  is_dev_stub: false,
                  aangemaakt_op: '2026-08-11T10:00:00Z',
                  laatst_gebruikt_op: '2026-08-11T12:00:00Z',
                  ingetrokken_op: ingetrokken.includes('ap1') ? '2026-08-11T13:00:00Z' : null,
                },
              ],
            }),
          )
        if (pad === '/auth/apparaten/ap1/intrekken' && init?.method === 'POST') {
          ingetrokken.push('ap1')
          return Promise.resolve(new Response(null, { status: 204 }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )

    render(<AccorderingInstellingen administraties={[{ id: 'a1', naam: 'BLOW B.V.' }]} />)
    // Sectie per administratie is een <details>; openen triggert het laden.
    await userEvent.click(screen.getByText('BLOW B.V.'))

    expect(await screen.findByText('Geregistreerde apparaten (passkeys)')).toBeInTheDocument()
    expect(await screen.findByText('iPhone')).toBeInTheDocument()
    expect(screen.getByText('actief')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Toegang intrekken' }))
    await waitFor(() => expect(ingetrokken).toContain('ap1'))
    expect(await screen.findByText('ingetrokken')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Toegang intrekken' })).not.toBeInTheDocument()
  })
})
