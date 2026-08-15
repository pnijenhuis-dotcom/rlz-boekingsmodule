import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BeveiligingInstellingen } from './BeveiligingInstellingen'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const MIJN_APPARAAT = {
  id: 'aaaaaaaa-0000-0000-0000-000000000001',
  apparaat_naam: 'Werk-Mac',
  is_dev_stub: false,
  aangemaakt_op: '2026-08-15T09:00:00Z',
  laatst_gebruikt_op: '2026-08-15T10:00:00Z',
  ingetrokken_op: null,
}

function installFetchMock(opties: {
  mijnApparaten?: unknown[]
  kantoorApparaten?: unknown[]
  devStub?: boolean
  aanroepen?: { url: string; body?: unknown }[]
}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === '/auth/mijn/apparaten') {
        return Promise.resolve(jsonResponse({ apparaten: opties.mijnApparaten ?? [MIJN_APPARAAT] }))
      }
      if (url === '/auth/webauthn/config') {
        return Promise.resolve(jsonResponse({ dev_stub: opties.devStub ?? true, rp_id: 'localhost' }))
      }
      if (url === '/auth/apparaten/kantoor') {
        return Promise.resolve(jsonResponse({ apparaten: opties.kantoorApparaten ?? [] }))
      }
      if (url === '/auth/webauthn/kantoor/registratie/voltooien' && init?.method === 'POST') {
        opties.aanroepen?.push({ url, body: JSON.parse(String(init.body)) })
        return Promise.resolve(jsonResponse({ ...MIJN_APPARAAT, is_dev_stub: true }))
      }
      if (url.endsWith('/intrekken') && init?.method === 'POST') {
        opties.aanroepen?.push({ url })
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('BeveiligingInstellingen (kantoor-passkeys, besluit 0020)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont de eigen apparaten met naam, registratiedatum en status', async () => {
    installFetchMock({})
    render(<BeveiligingInstellingen isBeheerder={false} />)

    expect(await screen.findByText('Werk-Mac')).toBeInTheDocument()
    expect(screen.getByText('actief')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Intrekken' })).toBeInTheDocument()
    // Niet-Beheerder: geen medewerkers-overzicht.
    expect(screen.queryByText(/Apparaten van medewerkers/)).not.toBeInTheDocument()
  })

  it('registreert via de dev-stub-route als er geen echte WebAuthn is (jsdom)', async () => {
    const aanroepen: { url: string; body?: unknown }[] = []
    installFetchMock({ mijnApparaten: [], aanroepen })
    render(<BeveiligingInstellingen isBeheerder={false} />)

    expect(await screen.findByText(/Nog geen passkeys geregistreerd/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Passkey toevoegen (dit apparaat)' }))

    await waitFor(() => expect(aanroepen.some((a) => a.url === '/auth/webauthn/kantoor/registratie/voltooien')).toBe(true))
    const registratie = aanroepen.find((a) => a.url === '/auth/webauthn/kantoor/registratie/voltooien')
    const registratieBody = registratie?.body as { dev_stub: boolean } | undefined
    expect(registratieBody?.dev_stub).toBe(true)
  })

  it('zonder secure context én zonder dev-stub is toevoegen uitgeschakeld met uitleg', async () => {
    installFetchMock({ devStub: false })
    render(<BeveiligingInstellingen isBeheerder={false} />)

    expect(await screen.findByText('Werk-Mac')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Passkey toevoegen (dit apparaat)' })).toBeDisabled()
    expect(screen.getByText(/beveiligde verbinding/)).toBeInTheDocument()
  })

  it('intrekken roept het kill-switch-endpoint aan en herlaadt de lijst', async () => {
    const aanroepen: { url: string }[] = []
    installFetchMock({ aanroepen })
    render(<BeveiligingInstellingen isBeheerder={false} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Intrekken' }))
    await waitFor(() =>
      expect(aanroepen.some((a) => a.url === `/auth/apparaten/${MIJN_APPARAAT.id}/intrekken`)).toBe(true),
    )
  })

  it('Beheerder ziet daarnaast de apparaten van medewerkers', async () => {
    installFetchMock({
      kantoorApparaten: [
        { ...MIJN_APPARAAT, id: 'bbbbbbbb-0000-0000-0000-000000000002', gebruiker_id: 'g2', gebruiker_naam: 'M. de Boer' },
      ],
    })
    render(<BeveiligingInstellingen isBeheerder />)

    expect(await screen.findByText(/Apparaten van medewerkers/)).toBeInTheDocument()
    expect(screen.getByText('M. de Boer')).toBeInTheDocument()
  })
})
