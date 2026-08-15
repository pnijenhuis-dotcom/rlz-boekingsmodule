// Schermtest uitloggen (kliktest 2026-08-12): de PWA-header heeft een uitlog-knop die het
// logout-endpoint onder het cookie-pad aanroept (dáár stuurt de browser de path-gebonden
// refresh-cookie mee, zie AuthContext), het ontgrendeld-vlaggetje opruimt en terugvalt op
// het login-scherm.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import AccordeurApp from './AccordeurApp'

// Node 22+ schaduwt window.localStorage/sessionStorage in de jsdom-testomgeving met zijn
// eigen (lege) experimental global — in-memory vervanger, zelfde patroon als
// ReviewSplitter.test.tsx.
function inMemoryOpslag(): Storage {
  const opslag = new Map<string, string>()
  return {
    getItem: (sleutel: string) => opslag.get(sleutel) ?? null,
    setItem: (sleutel: string, waarde: string) => void opslag.set(sleutel, String(waarde)),
    removeItem: (sleutel: string) => void opslag.delete(sleutel),
    clear: () => opslag.clear(),
    key: (i: number) => [...opslag.keys()][i] ?? null,
    get length() {
      return opslag.size
    },
  }
}

beforeAll(() => {
  Object.defineProperty(window, 'localStorage', { configurable: true, value: inMemoryOpslag() })
  Object.defineProperty(window, 'sessionStorage', { configurable: true, value: inMemoryOpslag() })
})

/** Alleen de payload wordt client-side gedecodeerd (decodeerJwtPayload) — een fake
 * handtekening volstaat voor de test. */
function fakeToken(claims: Record<string, unknown>): string {
  return `kop.${btoa(JSON.stringify(claims))}.handtekening`
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
  // vi.unstubAllGlobals ruimt Object.defineProperty niet op — navigator.credentials-mocks
  // (echte-async-pad-tests hieronder) mogen niet in andere tests doorlekken.
  delete (window.navigator as { credentials?: unknown }).credentials
  sessionStorage.clear()
  localStorage.clear()
})

describe('AccordeurApp — uitloggen', () => {
  it('uitlog-knop → POST op het cookie-pad, vlag weg, terug naar het login-scherm', async () => {
    const aangeroepen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
        const pad = String(invoer).split('?')[0]
        aangeroepen.push(`${init?.method ?? 'GET'} ${pad}`)
        switch (pad) {
          case '/auth/token/vernieuwen':
            return Promise.resolve(
              jsonResponse({ access_token: fakeToken({ rol: 'klant_accordeur', sub: 'u1' }) }),
            )
          case '/auth/token/vernieuwen/logout':
            return Promise.resolve(new Response(null, { status: 204 }))
          case '/accordering/wachtrij':
            return Promise.resolve(jsonResponse({ items: [] }))
          case '/auth/administraties':
            return Promise.resolve(jsonResponse({ administraties: [{ id: 'a1', naam: 'BLOW B.V.' }] }))
          case '/auth/webauthn/config':
            return Promise.resolve(jsonResponse({ dev_stub: false, rp_id: 'localhost' }))
          default:
            return Promise.resolve(new Response(null, { status: 404 }))
        }
      }),
    )
    // Binnen dezelfde app-sessie al ontgrendeld — de flow rendert dan direct.
    sessionStorage.setItem('accordeur-ontgrendeld', '1')

    render(
      <MemoryRouter initialEntries={['/accordeur']}>
        <AuthProvider>
          <AccordeurApp />
        </AuthProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Alles afgehandeld')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Uitloggen' }))

    // Server-side intrekken via het cookie-pad, daarna het login-scherm.
    await waitFor(() => expect(aangeroepen).toContain('POST /auth/token/vernieuwen/logout'))
    expect(await screen.findByRole('button', { name: 'Inloggen' })).toBeInTheDocument()
    expect(sessionStorage.getItem('accordeur-ontgrendeld')).toBeNull()
  })
})

describe('AccordeurApp — beginscherm (feedback Peter 2026-08-14)', () => {
  it('"Ontgrendelen" is de enige primaire knop; "Opnieuw inloggen" is een tekstlink, geen knop', async () => {
    // jsdom heeft geen PublicKeyCredential — stub zodat het echte-passkey-pad rendert.
    vi.stubGlobal('PublicKeyCredential', class {})
    vi.stubGlobal('isSecureContext', true)
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL) => {
        const pad = String(invoer).split('?')[0]
        switch (pad) {
          case '/auth/token/vernieuwen':
            return Promise.resolve(
              jsonResponse({ access_token: fakeToken({ rol: 'klant_accordeur', sub: 'u1' }) }),
            )
          case '/auth/webauthn/config':
            return Promise.resolve(jsonResponse({ dev_stub: false, rp_id: 'localhost' }))
          default:
            return Promise.resolve(new Response(null, { status: 404 }))
        }
      }),
    )
    // Ontgrendeld-vlag bewust NIET gezet: verse app-opening → beginscherm.

    render(
      <MemoryRouter initialEntries={['/accordeur']}>
        <AuthProvider>
          <AccordeurApp />
        </AuthProvider>
      </MemoryRouter>,
    )

    const ontgrendelKnop = await screen.findByRole('button', { name: 'Ontgrendelen' })
    expect(ontgrendelKnop.className).toContain('acc-btn')

    // De nooduitgang blijft bestaan (passkey kwijt/ander account/kill-switch), maar is
    // gedegradeerd tot subtiele tekstlink — precies één acc-btn op het scherm.
    const opnieuw = screen.getByRole('button', { name: 'Opnieuw inloggen' })
    expect(opnieuw.className).toContain('acc-tekstlink')
    expect(opnieuw.className).not.toContain('acc-btn')
    expect(document.querySelectorAll('.acc-btn')).toHaveLength(1)

    await userEvent.click(opnieuw)
    expect(await screen.findByRole('button', { name: 'Inloggen' })).toBeInTheDocument()
  })
})

// ---- passkey-registratie in de activeringsflow (kliktest Peter 2026-08-15, 2e reproductie) ----
// Bewust op het ÉCHTE async-pad: navigator.credentials wordt gemockt (met een echte await-gap),
// niet de dev-stub — de stub verhulde twee keer dat het scherm na een geslaagde registratie op
// de registratiestap bleef staan.

const REGISTRATIE_OPTIES = JSON.stringify({
  challenge: 'dGVzdA',
  rp: { id: 'localhost', name: 'RLZ' },
  user: { id: 'dXNlcg', name: 'a@b.nl', displayName: 'a@b.nl' },
  pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
  excludeCredentials: [],
})

const ASSERTIE_OPTIES = JSON.stringify({
  challenge: 'dGVzdA',
  rpId: 'localhost',
  allowCredentials: [{ id: 'Y3JlZA', type: 'public-key' }],
})

function fakeAttestatie(): unknown {
  return {
    id: 'cred-1',
    rawId: new Uint8Array([1, 2, 3]).buffer,
    type: 'public-key',
    getClientExtensionResults: () => ({}),
    response: {
      clientDataJSON: new Uint8Array([4]).buffer,
      attestationObject: new Uint8Array([5]).buffer,
      getTransports: () => ['internal'],
    },
  }
}

function fakeAssertie(): unknown {
  return {
    id: 'cred-1',
    rawId: new Uint8Array([1, 2, 3]).buffer,
    type: 'public-key',
    getClientExtensionResults: () => ({}),
    response: {
      clientDataJSON: new Uint8Array([4]).buffer,
      authenticatorData: new Uint8Array([6]).buffer,
      signature: new Uint8Array([7]).buffer,
      userHandle: null,
    },
  }
}

/** Fetch-mock voor de activeringsflow: activatie = nog geen sessie (refresh 401), webauthn-
 * endpoints + de wachtrij waarin de flow ná registratie moet landen. */
function stubActivatieFetch(overrides: Record<string, () => Promise<Response>> = {}): string[] {
  const aangeroepen: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
      const pad = String(invoer).split('?')[0]
      aangeroepen.push(`${init?.method ?? 'GET'} ${pad}`)
      if (overrides[pad]) return overrides[pad]()
      switch (pad) {
        case '/auth/token/vernieuwen':
          return Promise.resolve(jsonResponse({ detail: 'geen sessie' }, 401))
        case '/auth/webauthn/config':
          return Promise.resolve(jsonResponse({ dev_stub: false, rp_id: 'localhost' }))
        case '/auth/webauthn/registratie/opties':
          return Promise.resolve(jsonResponse({ opties: REGISTRATIE_OPTIES }))
        case '/auth/webauthn/registratie/voltooien':
          return Promise.resolve(
            jsonResponse({ access_token: fakeToken({ rol: 'klant_accordeur', sub: 'u1' }) }),
          )
        case '/accordering/wachtrij':
          return Promise.resolve(jsonResponse({ items: [] }))
        case '/auth/administraties':
          return Promise.resolve(jsonResponse({ administraties: [{ id: 'a1', naam: 'BLOW B.V.' }] }))
        default:
          return Promise.resolve(new Response(null, { status: 404 }))
      }
    }),
  )
  return aangeroepen
}

function renderOpActiverenMetToken() {
  return render(
    <MemoryRouter
      initialEntries={[{ pathname: '/accordeur/activeren', state: { passkeySetupToken: 'setup-1' } }]}
    >
      <AuthProvider>
        <AccordeurApp />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('AccordeurApp — passkey-registratie schakelt door (kliktest 2026-08-15, 2e reproductie)', () => {
  it('geslaagde registratie op het echte async-pad → automatisch door naar de flow, niet terug naar login', async () => {
    vi.stubGlobal('PublicKeyCredential', class {})
    vi.stubGlobal('isSecureContext', true)
    // Echte async-gap zoals navigator.credentials.create op een toestel (Face ID-prompt):
    // de dev-stub had deze gap niet en verhulde daarmee de hangende registratiestap.
    const create = vi.fn(async () => {
      await new Promise((klaar) => setTimeout(klaar, 0))
      return fakeAttestatie()
    })
    Object.defineProperty(window.navigator, 'credentials', {
      configurable: true,
      value: { create, get: vi.fn() },
    })
    const aangeroepen = stubActivatieFetch()

    renderOpActiverenMetToken()

    await userEvent.click(await screen.findByRole('button', { name: 'Passkey aanmaken' }))

    // Dóór naar de wachtrij (voorwaarden-poort zit fail-closed in GoedkeurenFlow zelf) —
    // niet blijven hangen op "Dit apparaat registreren" en niet terug naar login.
    expect(await screen.findByText('Alles afgehandeld')).toBeInTheDocument()
    expect(screen.queryByText('Dit apparaat registreren')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Inloggen' })).toBeNull()
    expect(aangeroepen).toContain('POST /auth/webauthn/registratie/voltooien')
    expect(create).toHaveBeenCalledTimes(1)
  })

  it('registratie al gelukt + scherm herladen (token-loos /activeren, levende sessie) → zelfherstellend door', async () => {
    // Herladen ná een geslaagde registratie: navigation-state (setup-token) is weg, maar de
    // refresh-cookie leeft — de silent refresh is de server-side waarheid. Binnen dezelfde
    // tab-sessie overleeft ook het ontgrendeld-vlaggetje de reload.
    sessionStorage.setItem('accordeur-ontgrendeld', '1')
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL) => {
        const pad = String(invoer).split('?')[0]
        switch (pad) {
          case '/auth/token/vernieuwen':
            return Promise.resolve(
              jsonResponse({ access_token: fakeToken({ rol: 'klant_accordeur', sub: 'u1' }) }),
            )
          case '/auth/webauthn/config':
            return Promise.resolve(jsonResponse({ dev_stub: false, rp_id: 'localhost' }))
          case '/accordering/wachtrij':
            return Promise.resolve(jsonResponse({ items: [] }))
          case '/auth/administraties':
            return Promise.resolve(jsonResponse({ administraties: [{ id: 'a1', naam: 'BLOW B.V.' }] }))
          default:
            return Promise.resolve(new Response(null, { status: 404 }))
        }
      }),
    )

    render(
      <MemoryRouter initialEntries={['/accordeur/activeren']}>
        <AuthProvider>
          <AccordeurApp />
        </AuthProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Alles afgehandeld')).toBeInTheDocument()
    expect(screen.queryByText('Sessie verlopen')).toBeNull()
  })

  it('registratie server-side al gelukt maar antwoord verloren: NotAllowedError → assertion-zelfherstel → door', async () => {
    vi.stubGlobal('PublicKeyCredential', class {})
    vi.stubGlobal('isSecureContext', true)
    // excludeCredentials laat de authenticator een 2e registratie weigeren — exact de
    // NotAllowedError uit Peters reproductie. De assertion bewijst daarna server-side dat
    // dít apparaat de passkey al draagt.
    const create = vi.fn(async () => {
      await new Promise((klaar) => setTimeout(klaar, 0))
      throw new DOMException('al geregistreerd op dit apparaat', 'NotAllowedError')
    })
    const get = vi.fn(async () => {
      await new Promise((klaar) => setTimeout(klaar, 0))
      return fakeAssertie()
    })
    Object.defineProperty(window.navigator, 'credentials', {
      configurable: true,
      value: { create, get },
    })
    const aangeroepen = stubActivatieFetch({
      '/auth/webauthn/login/opties': () => Promise.resolve(jsonResponse({ opties: ASSERTIE_OPTIES })),
      '/auth/webauthn/login/voltooien': () =>
        Promise.resolve(jsonResponse({ access_token: fakeToken({ rol: 'klant_accordeur', sub: 'u1' }) })),
    })

    renderOpActiverenMetToken()

    await userEvent.click(await screen.findByRole('button', { name: 'Passkey aanmaken' }))

    expect(await screen.findByText('Alles afgehandeld')).toBeInTheDocument()
    expect(aangeroepen).toContain('POST /auth/webauthn/login/voltooien')
    expect(aangeroepen).not.toContain('POST /auth/webauthn/registratie/voltooien')
  })
})

describe('AccordeurApp — activeren zonder setup-token (kliktest 2026-08-15)', () => {
  it('toont "Sessie verlopen" + één actie naar het login-scherm i.p.v. een dode knop', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((invoer: RequestInfo | URL) => {
        const pad = String(invoer).split('?')[0]
        switch (pad) {
          case '/auth/token/vernieuwen':
            // Geen refresh-cookie tijdens de activatieflow: uitgelogd.
            return Promise.resolve(jsonResponse({ detail: 'geen sessie' }, 401))
          case '/auth/webauthn/config':
            return Promise.resolve(jsonResponse({ dev_stub: false, rp_id: 'localhost' }))
          default:
            return Promise.resolve(new Response(null, { status: 404 }))
        }
      }),
    )

    // /activeren zonder navigation-state = de refresh-situatie: het setup-token is weg.
    render(
      <MemoryRouter initialEntries={['/accordeur/activeren']}>
        <AuthProvider>
          <AccordeurApp />
        </AuthProvider>
      </MemoryRouter>,
    )

    expect(await screen.findByText('Sessie verlopen')).toBeInTheDocument()
    // Geen registratieknoppen op het token-loze pad — dat was de stil-falende knop.
    expect(screen.queryByRole('button', { name: /Passkey aanmaken|Registreren/ })).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'Opnieuw inloggen' }))
    // De nieuwe-apparaat-route (login met e-mail + wachtwoord) vangt de registratie daarna op.
    expect(await screen.findByRole('button', { name: 'Inloggen' })).toBeInTheDocument()
  })
})
