import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccordeurActiveren } from './AccordeurActiveren'

// Mobiele activatieflow, drie stappen, atomair (besluit 28-08, mockup activatie-mobiel.html §2).
// jsdom heeft geen WebAuthn → de dev-stub-knop is het registratiepad; de server-kant van de
// atomiciteit staat in backend/tests/auth/test_activatie_atomair.py.

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stubFetch(opties: { registratieStatus?: number; accepterenStatus?: number } = {}) {
  const aangeroepen: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const pad = url.split('?')[0]
      aangeroepen.push(`${init?.method ?? 'GET'} ${pad}`)
      switch (pad) {
        case '/auth/webauthn/config':
          return Promise.resolve(jsonResponse({ dev_stub: true, rp_id: 'localhost' }))
        case '/auth/uitnodigingen/info':
          return Promise.resolve(
            jsonResponse({ flow: 'passkey', naam: 'Haci', herstel: false, verloopt_op: '2026-09-01T00:00:00Z' }),
          )
        case '/auth/uitnodigingen/accepteren':
          if (opties.accepterenStatus) {
            return Promise.resolve(jsonResponse({ detail: 'Uitnodiging is al gebruikt' }, opties.accepterenStatus))
          }
          return Promise.resolve(jsonResponse({ soort: 'passkey', passkey_setup_token: 'setup-1' }))
        case '/auth/webauthn/registratie/voltooien':
          if (opties.registratieStatus) {
            return Promise.resolve(jsonResponse({ detail: 'Registratie mislukt' }, opties.registratieStatus))
          }
          return Promise.resolve(jsonResponse({ access_token: 'acc', refresh_token: 'ref' }))
        case '/auth/uitnodigingen/activatie-probleem':
          return Promise.resolve(new Response(null, { status: 204 }))
        default:
          return Promise.resolve(new Response(null, { status: 404 }))
      }
    }),
  )
  return aangeroepen
}

async function doorloopWachtwoordstap() {
  const gebruiker = userEvent.setup()
  expect(await screen.findByText('Welkom, Haci')).toBeInTheDocument()
  expect(screen.getByText('Stap 1 van 3')).toBeInTheDocument()
  await gebruiker.type(screen.getByLabelText(/^Wachtwoord/), 'een-heel-lang-wachtwoord')
  await gebruiker.type(screen.getByLabelText('Herhaal wachtwoord'), 'een-heel-lang-wachtwoord')
  await gebruiker.click(screen.getByRole('button', { name: 'Doorgaan' }))
  expect(await screen.findByText('Stap 2 van 3')).toBeInTheDocument()
  return gebruiker
}

describe('AccordeurActiveren — mobiel-first, drie stappen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('wachtwoord → passkey (dev-stub) → "Account actief" → Naar de app', async () => {
    const aangeroepen = stubFetch()
    const naIngelogd = vi.fn()
    render(<AccordeurActiveren uitnodigingToken="tok" naIngelogd={naIngelogd} />)
    const gebruiker = await doorloopWachtwoordstap()
    expect(screen.getByText('Beveilig met uw gezicht of vingerafdruk')).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Registreren (dev-stub)' }))
    expect(await screen.findByText('Account actief')).toBeInTheDocument()
    expect(screen.getByText('Stap 3 van 3')).toBeInTheDocument()
    expect(naIngelogd).not.toHaveBeenCalled()
    await gebruiker.click(screen.getByRole('button', { name: 'Naar de app' }))
    expect(naIngelogd).toHaveBeenCalledWith({ access_token: 'acc', refresh_token: 'ref' })
    expect(aangeroepen).toContain('POST /auth/uitnodigingen/accepteren')
    expect(aangeroepen).toContain('POST /auth/webauthn/registratie/voltooien')
  })

  it('wachtwoorden ongelijk of te kort → fout, geen server-call', async () => {
    const aangeroepen = stubFetch()
    render(<AccordeurActiveren uitnodigingToken="tok" naIngelogd={vi.fn()} />)
    const gebruiker = userEvent.setup()
    await screen.findByText('Welkom, Haci')
    await gebruiker.type(screen.getByLabelText(/^Wachtwoord/), 'kort')
    await gebruiker.type(screen.getByLabelText('Herhaal wachtwoord'), 'kort')
    await gebruiker.click(screen.getByRole('button', { name: 'Doorgaan' }))
    expect(await screen.findByText(/Kies een wachtwoord van minimaal 12 tekens/)).toBeInTheDocument()
    expect(aangeroepen).not.toContain('POST /auth/uitnodigingen/accepteren')
  })

  it('passkey mislukt → foutscherm conform mockup, "Opnieuw proberen" terug naar stap 2, "meld het kantoor" POST', async () => {
    const aangeroepen = stubFetch({ registratieStatus: 400 })
    render(<AccordeurActiveren uitnodigingToken="tok" naIngelogd={vi.fn()} />)
    const gebruiker = await doorloopWachtwoordstap()
    await gebruiker.click(screen.getByRole('button', { name: 'Registreren (dev-stub)' }))
    expect(await screen.findByText('Dat lukte niet')).toBeInTheDocument()
    expect(screen.getByText('Stap 2 van 3 — mislukt')).toBeInTheDocument()
    expect(screen.getByText(/niets half geregistreerd/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Ik kom er niet uit — meld het kantoor' }))
    expect(await screen.findByText(/Het kantoor is op de hoogte/)).toBeInTheDocument()
    expect(aangeroepen).toContain('POST /auth/uitnodigingen/activatie-probleem')
    await gebruiker.click(screen.getByRole('button', { name: 'Opnieuw proberen' }))
    expect(await screen.findByText('Beveilig met uw gezicht of vingerafdruk')).toBeInTheDocument()
  })

  it('setup-token verlopen (401) tijdens stap 2 → terug naar stap 1 mét uitleg, link zelf blijft', async () => {
    stubFetch({ registratieStatus: 401 })
    render(<AccordeurActiveren uitnodigingToken="tok" naIngelogd={vi.fn()} />)
    const gebruiker = await doorloopWachtwoordstap()
    await gebruiker.click(screen.getByRole('button', { name: 'Registreren (dev-stub)' }))
    expect(await screen.findByText(/Dat duurde te lang/)).toBeInTheDocument()
    expect(screen.getByText('Stap 1 van 3')).toBeInTheDocument()
  })

  it('verbruikte link → "werkt niet meer", geen formulier', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.startsWith('/auth/uitnodigingen/info')) {
          return Promise.resolve(jsonResponse({ detail: 'Uitnodiging is al gebruikt' }, 400))
        }
        if (url === '/auth/webauthn/config') return Promise.resolve(jsonResponse({ dev_stub: true, rp_id: 'l' }))
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    render(<AccordeurActiveren uitnodigingToken="tok" naIngelogd={vi.fn()} />)
    expect(await screen.findByText('Activatielink werkt niet meer')).toBeInTheDocument()
    expect(screen.getByText('Uitnodiging is al gebruikt')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Wachtwoord/)).toBeNull()
  })

  it('legacy-ingang (setup-token uit navigation-state) begint direct bij de registratie en logt meteen in', async () => {
    stubFetch()
    const naIngelogd = vi.fn()
    render(<AccordeurActiveren passkeySetupToken="setup-1" naIngelogd={naIngelogd} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Registreren (dev-stub)' }))
    await waitFor(() => expect(naIngelogd).toHaveBeenCalled())
    expect(screen.queryByText('Stap 2 van 3')).toBeNull()
  })
})
