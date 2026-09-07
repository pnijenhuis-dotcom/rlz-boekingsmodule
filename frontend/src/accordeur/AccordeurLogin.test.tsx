// Activatie-hulp op het login-scherm (blok E2 06-09, casus detacheerder 04-09): ná een mislukte
// login (generieke 409 "geen passkey" / 401 wachtwoord — bewust niet te onderscheiden van "niet
// geactiveerd", 0022-lijn) verschijnt een eerlijk uitlegblok mét handelingsperspectief; native
// daarnaast "Mail-app openen" en "Link plakken" dat door DEZELFDE token-poort gaat als de mail-link.

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccordeurLogin } from './AccordeurLogin'
import { activatiePadVanGeplakteLink, GEEN_UITNODIGINGSLINK, LINK_ZONDER_CODE, mailAppUrl } from './ActivatieHulp'

type FetchAntwoorden = Record<string, (init?: RequestInit) => Response | Promise<Response>>

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stubFetch(routes: FetchAntwoorden): ReturnType<typeof vi.fn> {
  const mock = vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
    const pad = String(invoer).split('?')[0]
    const handler = routes[pad]
    if (!handler) return Promise.resolve(new Response(null, { status: 404 }))
    return Promise.resolve(handler(init))
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

const CONFIG = () => jsonResponse({ rp_id: 'localhost', dev_stub: false, store_link_ios: null, store_link_android: null })

/** Native schil: VeiligeOpslag-plugin (→ passkey-loginvorm) + platform. */
function stubNative(platform: 'ios' | 'android') {
  vi.stubGlobal('Capacitor', {
    isNativePlatform: () => true,
    getPlatform: () => platform,
    Plugins: {
      VeiligeOpslag: {
        zet: () => Promise.resolve(),
        haal: () => Promise.resolve({ waarde: null }),
        verwijder: () => Promise.resolve(),
      },
    },
  })
}

function ActivatieProbe() {
  const loc = useLocation()
  return <div data-testid="activatie-probe">{loc.search}</div>
}

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/accordeur']}>
      <Routes>
        <Route path="/accordeur" element={<AccordeurLogin naIngelogd={() => {}} />} />
        <Route path="/accordeur/activeren" element={<ActivatieProbe />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('AccordeurLogin — activatie-hulp (E2)', () => {
  it('web: dichtgevouwen tekstlink; ná een mislukte wachtwoord-login (401) het uitlegblok, zonder native knoppen', async () => {
    stubFetch({
      '/auth/webauthn/config': CONFIG,
      '/auth/accordeur/login': () => jsonResponse({ detail: 'Onjuiste inloggegevens' }, 401),
    })
    renderLogin()
    expect(screen.getByRole('button', { name: 'Nog niet geactiveerd?' })).toBeInTheDocument()
    expect(screen.queryByTestId('acc-activatie-hulp')).not.toBeInTheDocument()

    await userEvent.type(screen.getByLabelText('E-mailadres'), 'x@test.local')
    await userEvent.type(screen.getByLabelText('Wachtwoord'), 'geheim-wachtwoord')
    await userEvent.click(screen.getByRole('button', { name: 'Inloggen' }))

    expect(await screen.findByText('Onjuiste inloggegevens')).toBeInTheDocument()
    const hulp = screen.getByTestId('acc-activatie-hulp')
    expect(hulp).toHaveTextContent('Nog niet geactiveerd?')
    expect(hulp).toHaveTextContent('uitnodigingslink uit de e-mail op dít toestel')
    expect(hulp).toHaveTextContent('opnieuw te mailen')
    expect(screen.queryByRole('button', { name: 'Mail-app openen' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Link plakken' })).not.toBeInTheDocument()
  })

  it('tekstlink "Nog niet geactiveerd?" vouwt het blok ook zónder mislukte poging uit', async () => {
    stubFetch({ '/auth/webauthn/config': CONFIG })
    renderLogin()
    await userEvent.click(screen.getByRole('button', { name: 'Nog niet geactiveerd?' }))
    expect(screen.getByTestId('acc-activatie-hulp')).toBeInTheDocument()
  })

  it('native (passkey-login 409 generiek): uitlegblok + "Mail-app openen" + "Link plakken" → geldige link navigeert door de token-poort', async () => {
    stubNative('ios')
    stubFetch({
      '/auth/webauthn/config': CONFIG,
      '/auth/accordeur/passkey-login/opties': () =>
        jsonResponse({ detail: 'Geen passkey voor dit adres — vraag het kantoor om een nieuwe activatielink' }, 409),
    })
    renderLogin()
    await userEvent.type(screen.getByLabelText('E-mailadres'), 'x@test.local')
    await userEvent.click(screen.getByRole('button', { name: 'Inloggen met passkey' }))

    expect(await screen.findByText(/Geen passkey voor dit adres/)).toBeInTheDocument()
    expect(screen.getByTestId('acc-activatie-hulp')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mail-app openen' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Link plakken' }))
    await userEvent.type(
      screen.getByLabelText('Uitnodigingslink uit de e-mail'),
      'https://app.administratiekantoornijenhuis.nl/activeren?token=abc%2F123',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Naar de activatie' }))
    expect(await screen.findByTestId('activatie-probe')).toHaveTextContent('?uitnodiging=abc%2F123')
  })

  it('native: een ongeldige of code-loze link geeft een fout en navigeert niet', async () => {
    stubNative('android')
    stubFetch({ '/auth/webauthn/config': CONFIG })
    renderLogin()
    await userEvent.click(screen.getByRole('button', { name: 'Nog niet geactiveerd?' }))
    await userEvent.click(screen.getByRole('button', { name: 'Link plakken' }))
    const veld = screen.getByLabelText('Uitnodigingslink uit de e-mail')

    await userEvent.type(veld, 'https://voorbeeld.nl/iets')
    await userEvent.click(screen.getByRole('button', { name: 'Naar de activatie' }))
    expect(screen.getByText(GEEN_UITNODIGINGSLINK)).toBeInTheDocument()

    await userEvent.clear(veld)
    await userEvent.type(veld, 'https://app.administratiekantoornijenhuis.nl/activeren')
    await userEvent.click(screen.getByRole('button', { name: 'Naar de activatie' }))
    expect(screen.getByText(LINK_ZONDER_CODE)).toBeInTheDocument()
    expect(screen.queryByTestId('activatie-probe')).not.toBeInTheDocument()
  })
})

describe('activatiePadVanGeplakteLink + mailAppUrl (puur)', () => {
  it('accepteert alleen de twee link-vormen mét code; trimt en haalt <> weg', () => {
    expect(activatiePadVanGeplakteLink('  <https://app.administratiekantoornijenhuis.nl/activeren?token=t1&herstel=1>  ')).toEqual({
      pad: '/accordeur/activeren?uitnodiging=t1&herstel=1',
    })
    expect(activatiePadVanGeplakteLink('https://x.nl/accordeur/activeren?uitnodiging=t2')).toEqual({
      pad: '/accordeur/activeren?uitnodiging=t2',
    })
    expect(activatiePadVanGeplakteLink('https://x.nl/accordeur?document=1')).toEqual({ fout: GEEN_UITNODIGINGSLINK })
    expect(activatiePadVanGeplakteLink('https://x.nl/accordeur/activeren')).toEqual({ fout: LINK_ZONDER_CODE })
    expect(activatiePadVanGeplakteLink('')).toEqual({ fout: GEEN_UITNODIGINGSLINK })
    expect(activatiePadVanGeplakteLink('abc')).toEqual({ fout: GEEN_UITNODIGINGSLINK })
  })

  it('mail-inbox-URL per platform; web = geen knop', () => {
    expect(mailAppUrl('ios')).toBe('message://')
    expect(mailAppUrl('android')).toContain('android.intent.category.APP_EMAIL')
    expect(mailAppUrl('web')).toBeNull()
  })
})

// Blok 13 (07-09, Play-afwijzing variant B): Android zonder passkey-beheerder → eerlijke melding met
// handelingsperspectief i.p.v. de kale Credential-Manager-fout; iOS ongewijzigd (zelfde fouttekst blijft).
describe('AccordeurLogin — Credential-Manager-fout bij passkey-registratie (blok 13)', () => {
  const CM_FOUT = 'Passkey-registratie mislukt: No create options available.'

  function stubNativeMetPasskeyPlugin(platform: 'ios' | 'android') {
    stubNative(platform)
    const cap = (window as unknown as { Capacitor: { Plugins: Record<string, unknown> } }).Capacitor
    cap.Plugins.NatievePasskey = {
      registreer: () => Promise.reject(new Error(CM_FOUT)),
      onderteken: () => Promise.reject(new Error('Passkey-verificatie geannuleerd')),
    }
  }

  function loginRoutes(): FetchAntwoorden {
    return {
      '/auth/webauthn/config': CONFIG,
      '/auth/accordeur/login': () => jsonResponse({ passkey_setup_token: 'setup-1', heeft_passkeys: false }),
      '/auth/webauthn/registratie/opties': () => jsonResponse({ opties: '{"challenge":"x"}' }),
    }
  }

  async function logInMetWachtwoord() {
    await userEvent.click(screen.getByRole('button', { name: 'Inloggen met wachtwoord' }))
    await userEvent.type(screen.getByLabelText('E-mailadres'), 'reviewer@test.local')
    await userEvent.type(screen.getByLabelText('Wachtwoord'), 'geheim-wachtwoord')
    await userEvent.click(screen.getByRole('button', { name: 'Inloggen' }))
  }

  it('android: "geen passkey-beheerder" — Google-account / schermvergrendeling / ander toestel; kale fout verdwijnt', async () => {
    stubNativeMetPasskeyPlugin('android')
    stubFetch(loginRoutes())
    renderLogin()
    await logInMetWachtwoord()
    const melding = await screen.findByText(/geen passkey-beheerder actief/)
    expect(melding).toHaveTextContent('voeg een Google-account toe of zet schermvergrendeling aan')
    expect(melding).toHaveTextContent('gebruik een ander toestel')
    expect(screen.queryByText(/No create options available/)).not.toBeInTheDocument()
    // Geen alternatieve loginroute: het uitlegblok blijft het bestaande hulpblok, geen extra knop.
    expect(screen.queryByRole('button', { name: /zonder passkey/i })).not.toBeInTheDocument()
  })

  it('iOS: dezelfde fouttekst blijft ongewijzigd staan (geen Android-melding)', async () => {
    stubNativeMetPasskeyPlugin('ios')
    stubFetch(loginRoutes())
    renderLogin()
    await logInMetWachtwoord()
    expect(await screen.findByText(CM_FOUT)).toBeInTheDocument()
    expect(screen.queryByText(/geen passkey-beheerder actief/)).not.toBeInTheDocument()
  })

  it('android: een gewone annulering blijft "geannuleerd" (geen valse beheerder-melding)', async () => {
    stubNativeMetPasskeyPlugin('android')
    const cap = (window as unknown as { Capacitor: { Plugins: Record<string, unknown> } }).Capacitor
    cap.Plugins.NatievePasskey = {
      registreer: () => Promise.reject(new Error('Passkey-registratie geannuleerd')),
      onderteken: () => Promise.reject(new Error('Passkey-verificatie geannuleerd')),
    }
    stubFetch(loginRoutes())
    renderLogin()
    await logInMetWachtwoord()
    expect(await screen.findByText('Passkey-registratie geannuleerd')).toBeInTheDocument()
    expect(screen.queryByText(/geen passkey-beheerder actief/)).not.toBeInTheDocument()
  })
})
