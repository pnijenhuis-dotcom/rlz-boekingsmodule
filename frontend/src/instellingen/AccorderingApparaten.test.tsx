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
                  soort: 'toestel',
                  platform: 'ios',
                  niet_meer_gebruikt_op: null,
                },
                // App-auth 08-09: oude passkey van een app-gebruiker, door de CLI gemarkeerd — grijs, nooit weg, intrekbaar.
                {
                  id: 'ap0',
                  apparaat_naam: 'Oude iPhone',
                  is_dev_stub: false,
                  aangemaakt_op: '2026-08-01T10:00:00Z',
                  laatst_gebruikt_op: '2026-08-20T12:00:00Z',
                  ingetrokken_op: null,
                  soort: 'passkey',
                  platform: null,
                  niet_meer_gebruikt_op: '2026-09-08T08:00:00Z',
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

    expect(await screen.findByText('Gekoppelde toestellen en apparaten')).toBeInTheDocument()
    expect(await screen.findByText('iPhone')).toBeInTheDocument()
    expect(screen.getByText('Toestel (iOS)')).toBeInTheDocument()
    expect(screen.getByText('actief')).toBeInTheDocument()
    // De oude passkey staat er grijs bij mét "niet meer gebruikt" én houdt zijn intrek-knop (kill-switch voor beide).
    expect(screen.getByText('passkey — niet meer gebruikt')).toBeInTheDocument()
    expect(screen.getByText('niet meer gebruikt')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Toegang intrekken' })).toHaveLength(2)

    await userEvent.click(screen.getAllByRole('button', { name: 'Toegang intrekken' })[0])
    await waitFor(() => expect(ingetrokken).toContain('ap1'))
    expect(await screen.findByText('ingetrokken')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Toegang intrekken' })).toHaveLength(1)
  })
})
