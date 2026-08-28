import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
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
        if (url.startsWith('/auth/uitnodigingen/info')) {
          return Promise.resolve(
            jsonResponse({ flow: 'totp', naam: 'Kantoor K.', herstel: false, verloopt_op: '2026-09-01T00:00:00Z' }),
          )
        }
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

    await gebruiker.type(await screen.findByLabelText(/Nieuw wachtwoord/), 'een-heel-lang-wachtwoord')
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

function infoResponse(flow: 'passkey' | 'totp', herstel = false): Response {
  return jsonResponse({ flow, naam: 'Haci Y.', herstel, verloopt_op: '2026-09-01T00:00:00Z' })
}

function stubInfoFetch(flow: 'passkey' | 'totp', herstel = false, extra?: (url: string) => Response | null) {
  const aangeroepen: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      aangeroepen.push(`${init?.method ?? 'GET'} ${url}`)
      if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
      if (url.startsWith('/auth/uitnodigingen/info')) return Promise.resolve(infoResponse(flow, herstel))
      if (url === '/auth/webauthn/config') return Promise.resolve(jsonResponse({ dev_stub: false, rp_id: 'localhost' }))
      const anders = extra?.(url)
      if (anders) return Promise.resolve(anders)
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

function Locatie() {
  const locatie = useLocation()
  return <div data-testid="locatie">{locatie.pathname + locatie.search}</div>
}

function renderActiveren(pad: string) {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <AuthProvider>
        <Routes>
          <Route path="/activeren" element={<ActivateScreen />} />
          <Route path="/accordeur/activeren" element={<Locatie />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('ActivateScreen — mobiel-first activatie externe rollen (besluit 28-08, mockup activatie-mobiel.html)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('externe link op een desktop (jsdom-UA, geen platform-authenticator) → stop-scherm mét QR van dezelfde link, GEEN wachtwoordveld', async () => {
    const aangeroepen = stubInfoFetch('passkey')
    renderActiveren('/activeren?token=abc')
    expect(await screen.findByTestId('activatie-stopscherm')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Open deze uitnodiging op uw telefoon' })).toBeInTheDocument()
    expect(screen.getByLabelText('QR-code met dezelfde activatielink').querySelector('svg')).toBeInTheDocument()
    expect(screen.queryByLabelText(/wachtwoord/i)).toBeNull()
    expect(screen.getByText(/niets is nog vastgelegd/)).toBeInTheDocument()
    // De link verzilvert hier niets: alleen de info-route is geraakt, nooit accepteren.
    expect(aangeroepen.some((a) => a.includes('/auth/uitnodigingen/accepteren'))).toBe(false)
  })

  it('externe link op een telefoon mét platform-authenticator → door naar de app-flow, mét de link in de URL', async () => {
    stubInfoFetch('passkey')
    vi.stubGlobal('navigator', {
      ...window.navigator,
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1',
    })
    vi.stubGlobal('PublicKeyCredential', { isUserVerifyingPlatformAuthenticatorAvailable: async () => true })
    renderActiveren('/activeren?token=abc')
    expect(await screen.findByTestId('locatie')).toHaveTextContent('/accordeur/activeren?uitnodiging=abc')
  })

  it('telefoon-UA maar onbekende capability = twijfel → stop-scherm (fail-safe richting telefoon)', async () => {
    stubInfoFetch('passkey')
    vi.stubGlobal('navigator', {
      ...window.navigator,
      userAgent: 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Mobile Safari/537.36',
    })
    renderActiveren('/activeren?token=abc')
    expect(await screen.findByTestId('activatie-stopscherm')).toBeInTheDocument()
  })

  it('herstel-link is altijd extern → mobiel-first mét herstel=1 in de app-URL', async () => {
    stubInfoFetch('passkey', true)
    vi.stubGlobal('navigator', {
      ...window.navigator,
      userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148',
    })
    vi.stubGlobal('PublicKeyCredential', { isUserVerifyingPlatformAuthenticatorAvailable: async () => true })
    renderActiveren('/activeren?token=abc&herstel=1')
    expect(await screen.findByTestId('locatie')).toHaveTextContent('/accordeur/activeren?uitnodiging=abc&herstel=1')
  })

  it('ongeldige/verbruikte link → duidelijke melding, geen formulier', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
        if (url.startsWith('/auth/uitnodigingen/info')) {
          return Promise.resolve(jsonResponse({ detail: 'Uitnodiging is al gebruikt' }, 400))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    renderActiveren('/activeren?token=abc')
    expect(await screen.findByRole('heading', { name: 'Activatielink werkt niet meer' })).toBeInTheDocument()
    expect(screen.getByText('Uitnodiging is al gebruikt')).toBeInTheDocument()
    expect(screen.queryByLabelText(/wachtwoord/i)).toBeNull()
  })
})
