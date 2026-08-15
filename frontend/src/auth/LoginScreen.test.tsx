import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from './AuthContext'
import { LoginScreen } from './LoginScreen'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function fakeAccessToken(rol: string): string {
  const payload = btoa(JSON.stringify({ sub: 'gebruiker-id', rol })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<div>WERKVOORRAAD-SCHERM</div>} />
          <Route path="/login" element={<LoginScreen />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('LoginScreen — passkey eerste lijn (besluit 0020)', () => {
  beforeEach(() => {
    // AuthProvider probeert bij het laden altijd een stille refresh via de cookie — in een
    // schone testomgeving is er geen cookie, dus dit moet als "niet ingelogd" afhandelen.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(null, { status: 401 }))),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('start met alleen het e-mailveld (usernameless mag niet) en een terugval-link', () => {
    renderScherm()

    expect(screen.getByLabelText('E-mailadres')).toBeInTheDocument()
    expect(screen.queryByLabelText('Wachtwoord')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('TOTP-code')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Verder met passkey' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Inloggen met wachtwoord + TOTP' })).toBeInTheDocument()
  })

  it('de terugval-link toont het volledige wachtwoord + TOTP-formulier (TOTP-pad ongewijzigd)', async () => {
    renderScherm()

    await userEvent.click(screen.getByRole('button', { name: 'Inloggen met wachtwoord + TOTP' }))
    expect(screen.getByLabelText('E-mailadres')).toBeInTheDocument()
    expect(screen.getByLabelText('Wachtwoord')).toBeInTheDocument()
    expect(screen.getByLabelText('TOTP-code')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Inloggen' })).toBeInTheDocument()
  })

  it('valt stil terug op wachtwoord + TOTP als er geen bruikbare passkey is (409)', async () => {
    // jsdom heeft geen PublicKeyCredential → het scherm vraagt eerst de webauthn-config op;
    // met dev_stub aan gaat het door naar de opties-route, die hier 409 antwoordt.
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
        if (url === '/auth/webauthn/config') {
          return Promise.resolve(jsonResponse({ dev_stub: true, rp_id: 'localhost' }))
        }
        if (url === '/auth/webauthn/kantoor/login/opties' && init?.method === 'POST') {
          return Promise.resolve(
            jsonResponse({ detail: 'Geen passkey voor dit adres — log in met wachtwoord + TOTP' }, 409),
          )
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    renderScherm()

    await userEvent.type(screen.getByLabelText('E-mailadres'), 'p@test.local')
    await userEvent.click(screen.getByRole('button', { name: 'Verder met passkey' }))

    expect(await screen.findByLabelText('Wachtwoord')).toBeInTheDocument()
    expect(screen.getByLabelText('TOTP-code')).toBeInTheDocument()
    // Stil doorschuiven: geen foutmelding — dit is het normale pad voor passkey-loze gebruikers.
    expect(screen.queryByText(/mislukt/i)).not.toBeInTheDocument()
  })

  it('logt in via de dev-stub-route als er geen echte WebAuthn beschikbaar is', async () => {
    const aanroepen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push(url)
        if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
        if (url === '/auth/webauthn/config') {
          return Promise.resolve(jsonResponse({ dev_stub: true, rp_id: 'localhost' }))
        }
        if (url === '/auth/webauthn/kantoor/login/opties' && init?.method === 'POST') {
          return Promise.resolve(jsonResponse({ opties: null, dev_stub: true }))
        }
        if (url === '/auth/webauthn/kantoor/login/voltooien' && init?.method === 'POST') {
          const body = JSON.parse(String(init.body)) as { e_mail: string; dev_stub?: boolean }
          expect(body.e_mail).toBe('p@test.local')
          expect(body.dev_stub).toBe(true)
          return Promise.resolve(jsonResponse({ access_token: fakeAccessToken('boekhouding') }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    renderScherm()

    await userEvent.type(screen.getByLabelText('E-mailadres'), 'p@test.local')
    await userEvent.click(screen.getByRole('button', { name: 'Verder met passkey' }))

    await waitFor(() => expect(screen.getByText('WERKVOORRAAD-SCHERM')).toBeInTheDocument())
    expect(aanroepen).toContain('/auth/webauthn/kantoor/login/voltooien')
  })

  it('toont een nette melding i.p.v. de kale proxy-fout als de backend onbereikbaar is', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(null, { status: 502, statusText: 'Bad Gateway' }))),
    )

    renderScherm()

    const melding = await screen.findByText(/backend is momenteel niet bereikbaar/i)
    expect(melding).toBeInTheDocument()
    expect(screen.queryByText('Bad Gateway')).not.toBeInTheDocument()
  })
})
