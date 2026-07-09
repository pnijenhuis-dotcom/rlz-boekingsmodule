import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ActivateScreen } from './ActivateScreen'
import { AuthProvider } from './AuthContext'

const OTPAUTH_URI =
  'otpauth://totp/RLZ%20Boekingsmodule:peter%40nijenhuis.nl?secret=ABCDEFGHIJKLMNOP&issuer=RLZ%20Boekingsmodule'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('ActivateScreen — TOTP-enrollment', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
        if (url === '/auth/uitnodigingen/accepteren') {
          return Promise.resolve(
            jsonResponse({ totp_setup_token: 'setup-token', otpauth_uri: OTPAUTH_URI, secret: 'ABCDEFGHIJKLMNOP' }),
          )
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('rendert een scanbare QR-code op basis van de otpauth-URI, met het secret als terugval', async () => {
    const gebruiker = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/activeren?token=abc']}>
        <AuthProvider>
          <ActivateScreen />
        </AuthProvider>
      </MemoryRouter>,
    )

    await gebruiker.type(screen.getByLabelText(/Nieuw wachtwoord/), 'een-heel-lang-wachtwoord')
    await gebruiker.type(screen.getByLabelText('Bevestig wachtwoord'), 'een-heel-lang-wachtwoord')
    await gebruiker.click(screen.getByRole('button', { name: 'Wachtwoord instellen' }))

    await waitFor(() => expect(screen.getByLabelText('QR-code voor de authenticator-app')).toBeInTheDocument())

    const qrContainer = screen.getByLabelText('QR-code voor de authenticator-app')
    expect(qrContainer.querySelector('svg')).toBeInTheDocument()

    // Terugval: de geheime sleutel blijft zichtbaar naast de QR-code.
    expect(screen.getByText('ABCD EFGH IJKL MNOP')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /otpauth-link openen/ })).toHaveAttribute('href', OTPAUTH_URI)
  })
})
