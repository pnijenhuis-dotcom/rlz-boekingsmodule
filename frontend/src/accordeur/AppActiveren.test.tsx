// Activatiescherm (app-auth zonder passkey en TOTP, besluit Peter 08-09-2026, contract §5b/§5g):
// code-invoer + normalisatie, foutpaden 400/409/429/offline, het link-pad ("Welkom {naam}" → "Dit
// toestel activeren"), en de doorloop naar PincodeKiezen → slot → sessie. Draait in de PWA-slotmodus
// (jsdom op /accordeur + fake IndexedDB + WebCrypto), zonder native schil tenzij gestubd.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { webcrypto } from 'node:crypto'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { bewaarCredentialId, haalCredentialId, isAppSlotIngesteld, isOntgrendeld, vergrendel, wisAppSlotLokaal } from '../api/appSlot'
import { setAccessToken } from '../api/client'
import { installeerFakeIndexedDb } from '../api/fakeIndexedDb.testhulp'
import { SLOT_MODUS_SLEUTEL } from '../api/webVeiligeOpslag'
import type { TokenPaarResponseDto } from '../api/types'
import { GEEN_VERBINDING_MELDING } from './appAuthApi'
import { AppActiveren } from './AppActiveren'

if (!globalThis.crypto?.subtle) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
}

function inMemoryOpslag(): Storage {
  const opslag = new Map<string, string>()
  return {
    getItem: (k: string) => opslag.get(k) ?? null,
    setItem: (k: string, v: string) => void opslag.set(k, String(v)),
    removeItem: (k: string) => void opslag.delete(k),
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

let idb: ReturnType<typeof installeerFakeIndexedDb>

beforeEach(() => {
  idb = installeerFakeIndexedDb()
  window.history.pushState({}, '', '/accordeur')
  setAccessToken(null)
  vergrendel()
})

afterEach(async () => {
  await wisAppSlotLokaal()
  vi.unstubAllGlobals()
  delete (window as { Capacitor?: unknown }).Capacitor
  idb.herstel()
  window.history.pushState({}, '', '/')
  localStorage.clear()
})

function fakeToken(claims: Record<string, unknown>): string {
  return `kop.${btoa(JSON.stringify(claims))}.handtekening`
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

interface Aanroep {
  methode: string
  pad: string
  headers: Headers
  body: unknown
}

const ACTIVATIE_OK = {
  access_token: fakeToken({ rol: 'klant_accordeur', sub: 'u1' }),
  token_type: 'bearer',
  refresh_token: 'rt-1',
  apparaat_credential_id: 'cred-1',
  naam: 'Jan',
  herstel: false,
}

function stubFetch(overrides: Record<string, (aanroep: Aanroep) => Promise<Response>> = {}): Aanroep[] {
  const aanroepen: Aanroep[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
      const pad = String(invoer).split('?')[0]
      const aanroep: Aanroep = {
        methode: init?.method ?? 'GET',
        pad,
        headers: new Headers(init?.headers),
        body: typeof init?.body === 'string' ? (JSON.parse(init.body) as unknown) : null,
      }
      aanroepen.push(aanroep)
      if (overrides[pad]) return overrides[pad](aanroep)
      switch (pad) {
        case '/auth/app/activeren':
          return Promise.resolve(jsonResponse(ACTIVATIE_OK))
        case '/auth/webauthn/config':
          return Promise.resolve(jsonResponse({ dev_stub: false, rp_id: 'localhost' }))
        case '/auth/uitnodigingen/info':
          return Promise.resolve(jsonResponse({ flow: 'app', naam: 'Jan', herstel: false, verloopt_op: '2026-09-11T10:00:00Z' }))
        case '/auth/accordeur/voorwaarden-akkoord':
          return Promise.resolve(new Response(null, { status: 204 }))
        case '/auth/app-lock/hulp':
          return Promise.resolve(new Response(null, { status: 204 }))
        default:
          return Promise.resolve(new Response(null, { status: 404 }))
      }
    }),
  )
  return aanroepen
}

function LocationSpion() {
  const loc = useLocation()
  return <div data-testid="locatie">{`${loc.pathname}${loc.search}`}</div>
}

function renderScherm(props: Partial<React.ComponentProps<typeof AppActiveren>> = {}, begin = '/accordeur') {
  const naGeactiveerd = vi.fn<(paar: TokenPaarResponseDto) => void>()
  render(
    <MemoryRouter initialEntries={[begin]}>
      <AppActiveren naGeactiveerd={naGeactiveerd} {...props} />
      <LocationSpion />
    </MemoryRouter>,
  )
  return naGeactiveerd
}

async function tikCode(code: string) {
  for (const c of code) await userEvent.click(screen.getByRole('button', { name: c }))
}

describe('AppActiveren — activatiecode-scherm', () => {
  it('toont kop, titel, uitleg en de linkregel; web zonder store-links toont geen "Link plakken"', async () => {
    stubFetch()
    renderScherm()
    expect(screen.getByText('Activatiecode invoeren')).toBeInTheDocument()
    expect(screen.getByText('Je vindt de code in de uitnodigingsmail van het kantoor.')).toBeInTheDocument()
    expect(screen.getByText('Link uit de uitnodiging ontvangen? Tik erop — de app opent dan vanzelf.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Activeren' }).className).toContain('acc-btn primair')
    expect(screen.queryByRole('button', { name: 'Link plakken' })).toBeNull()
    // Het veld: 16px-klasse van .acc input geldt; auto-hoofdletters + one-time-code.
    const veld = screen.getByLabelText('Activatiecode')
    expect(veld).toHaveAttribute('autocapitalize', 'characters')
    expect(veld).toHaveAttribute('inputmode', 'text')
    await waitFor(() => expect(document.querySelector('[data-testid="store-links"]')).toBeNull())
  })

  it('normaliseert de invoer (hoofdletters, spaties/koppeltekens weg) en toont XXXX-XXXX; POST draagt de kale code, toestel en platform', async () => {
    const aanroepen = stubFetch()
    renderScherm()
    const veld = screen.getByLabelText('Activatiecode')
    await userEvent.type(veld, 'abcd efgh')
    expect(veld).toHaveValue('ABCD-EFGH')
    await userEvent.click(screen.getByRole('button', { name: 'Activeren' }))
    const post = await waitFor(() => {
      const p = aanroepen.find((a) => a.pad === '/auth/app/activeren')
      expect(p).toBeDefined()
      return p!
    })
    expect(post.methode).toBe('POST')
    expect(post.body).toMatchObject({ activatiecode: 'ABCDEFGH', token: null, platform: 'web' })
    expect(typeof (post.body as { toestel_naam: unknown }).toestel_naam).toBe('string')
    // PWA-slotmodus: de client-aankondiging voor de token-levering in de body.
    expect(post.headers.get('X-App-Slot')).toBe('1')
    expect(post.headers.has('X-Native-Client')).toBe(false)
  })

  it('te korte code → eigen melding, geen request', async () => {
    const aanroepen = stubFetch()
    renderScherm()
    await userEvent.type(screen.getByLabelText('Activatiecode'), 'ABC')
    await userEvent.click(screen.getByRole('button', { name: 'Activeren' }))
    expect(await screen.findByText('Voer de volledige activatiecode van 8 tekens in.')).toBeInTheDocument()
    expect(aanroepen.some((a) => a.pad === '/auth/app/activeren')).toBe(false)
  })

  it.each([
    [400, 'Deze activatiecode of link is niet (meer) geldig', 'Deze activatiecode of link is niet (meer) geldig'],
    [
      409,
      'Deze uitnodiging is al op een ander toestel gebruikt — vraag het kantoor om een nieuwe uitnodiging',
      // Servertekst draagt de hint al → niet verdubbelen.
      'Deze uitnodiging is al op een ander toestel gebruikt — vraag het kantoor om een nieuwe uitnodiging',
    ],
    [
      429,
      'Te veel pogingen — probeer het over een uur opnieuw of vraag het kantoor om een nieuwe uitnodiging',
      'Te veel pogingen — probeer het over een uur opnieuw of vraag het kantoor om een nieuwe uitnodiging',
    ],
  ])('%i → de servertekst op het scherm (409 mét kantoor-hint), scherm blijft bruikbaar', async (status, detail, verwacht) => {
    stubFetch({ '/auth/app/activeren': () => Promise.resolve(jsonResponse({ detail }, status)) })
    const naGeactiveerd = renderScherm()
    await userEvent.type(screen.getByLabelText('Activatiecode'), 'ABCDEFGH')
    await userEvent.click(screen.getByRole('button', { name: 'Activeren' }))
    expect(await screen.findByText(verwacht)).toBeInTheDocument()
    expect(naGeactiveerd).not.toHaveBeenCalled()
    // Hulpblok klapt open ná een mislukte poging, zonder account-enumeratie-uitleg.
    expect(screen.getByTestId('acc-activatie-hulp')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Activeren' })).toBeEnabled()
  })

  it('offline (fetch gooit) → "Geen verbinding — …"', async () => {
    stubFetch({ '/auth/app/activeren': () => Promise.reject(new TypeError('Load failed')) })
    renderScherm()
    await userEvent.type(screen.getByLabelText('Activatiecode'), 'ABCDEFGH')
    await userEvent.click(screen.getByRole('button', { name: 'Activeren' }))
    expect(await screen.findByText(GEEN_VERBINDING_MELDING)).toBeInTheDocument()
  })

  it('verlopen-melding + "Kantoor vragen om nieuwe uitnodiging" → POST /auth/app-lock/hulp op het bewaarde toestel-id', async () => {
    await bewaarCredentialId('cred-oud')
    const aanroepen = stubFetch()
    renderScherm({ melding: 'Je toegang is verlopen of ingetrokken — activeer de app opnieuw met een nieuwe uitnodiging van het kantoor.' })
    expect(screen.getByRole('status')).toHaveTextContent('Je toegang is verlopen of ingetrokken')
    await userEvent.click(screen.getByRole('button', { name: 'Kantoor vragen om nieuwe uitnodiging' }))
    expect(await screen.findByText('✓ Het kantoor is op de hoogte en stuurt je een nieuwe uitnodiging.')).toBeInTheDocument()
    const hulp = aanroepen.find((a) => a.pad === '/auth/app-lock/hulp')
    expect(hulp?.body).toEqual({ credential_id: 'cred-oud' })
  })

  it('native: "Link plakken" → geplakte mail-link → in-app-activatieroute', async () => {
    vi.stubGlobal('Capacitor', { isNativePlatform: () => true, getPlatform: () => 'ios', Plugins: {} })
    stubFetch()
    renderScherm()
    await userEvent.click(screen.getByRole('button', { name: 'Link plakken' }))
    await userEvent.type(screen.getByLabelText('Uitnodigingslink uit de e-mail'), 'https://app.administratiekantoornijenhuis.nl/activeren?token=abc&herstel=1')
    await userEvent.click(screen.getByRole('button', { name: 'Naar de activatie' }))
    expect(screen.getByTestId('locatie')).toHaveTextContent('/accordeur/activeren?uitnodiging=abc&herstel=1')
  })
})

describe('AppActiveren — link-pad (universal link)', () => {
  it('toont eerst "Welkom, Jan — Dit toestel activeren" zonder de link te verzilveren; de knop doet de POST mét token', async () => {
    const aanroepen = stubFetch()
    renderScherm({ token: 'tok-1' })
    expect(await screen.findByText('Welkom, Jan')).toBeInTheDocument()
    expect(aanroepen.some((a) => a.pad === '/auth/uitnodigingen/info')).toBe(true)
    expect(aanroepen.some((a) => a.pad === '/auth/app/activeren')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Dit toestel activeren' }))
    await waitFor(() => expect(aanroepen.some((a) => a.pad === '/auth/app/activeren')).toBe(true))
    expect(aanroepen.find((a) => a.pad === '/auth/app/activeren')!.body).toMatchObject({ token: 'tok-1', activatiecode: null })
    // Door naar de toegangscode (PincodeKiezen, "Welkom, Jan" + 5 cijfers).
    expect(await screen.findByText('Kies een code van 5 cijfers. Hiermee open je voortaan de app.')).toBeInTheDocument()
  })

  it('herstel=1 → titel "Toestel opnieuw koppelen"', async () => {
    stubFetch({
      '/auth/uitnodigingen/info': () => Promise.resolve(jsonResponse({ flow: 'app', naam: 'Jan', herstel: true, verloopt_op: 'x' })),
    })
    renderScherm({ token: 'tok-1', herstel: true })
    expect(await screen.findByText('Toestel opnieuw koppelen')).toBeInTheDocument()
  })

  it('ongeldige/verlopen link → servertekst + "Deze uitnodiging werkt niet meer" + weg naar de code-invoer', async () => {
    stubFetch({
      '/auth/uitnodigingen/info': () => Promise.resolve(jsonResponse({ detail: 'Deze activatiecode of link is niet (meer) geldig' }, 400)),
    })
    renderScherm({ token: 'tok-dood' }, '/accordeur/activeren?uitnodiging=tok-dood')
    expect(await screen.findByText('Deze uitnodiging werkt niet meer')).toBeInTheDocument()
    expect(screen.getByText('Deze activatiecode of link is niet (meer) geldig')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Activatiecode invoeren' }))
    expect(screen.getByTestId('locatie')).toHaveTextContent('/accordeur')
  })

  it('409 op de link → servertekst + kantoor-hint, knop "Ik kom er niet uit — meld het kantoor" meldt op het token', async () => {
    const aanroepen = stubFetch({
      '/auth/app/activeren': () =>
        Promise.resolve(jsonResponse({ detail: 'Deze uitnodiging is al op een ander toestel gebruikt.' }, 409)),
      '/auth/uitnodigingen/activatie-probleem': () => Promise.resolve(jsonResponse({ ok: true })),
    })
    renderScherm({ token: 'tok-1' })
    await userEvent.click(await screen.findByRole('button', { name: 'Dit toestel activeren' }))
    expect(await screen.findByText('Deze uitnodiging is al op een ander toestel gebruikt. Vraag het kantoor om een nieuwe uitnodiging.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Ik kom er niet uit — meld het kantoor' }))
    expect(await screen.findByText('✓ Het kantoor is op de hoogte en neemt contact met je op.')).toBeInTheDocument()
    expect(aanroepen.find((a) => a.pad === '/auth/uitnodigingen/activatie-probleem')?.body).toEqual({ token: 'tok-1' })
  })
})

describe('AppActiveren — doorloop code → toegangscode → slot → sessie', () => {
  it('ná 200: PincodeKiezen (2×) → toestel-id bewaard, slot ingesteld + open, voorwaarden-akkoord met Bearer, naGeactiveerd(paar), slot-vlag gezet', async () => {
    const aanroepen = stubFetch()
    const naGeactiveerd = renderScherm()
    await userEvent.type(screen.getByLabelText('Activatiecode'), 'ABCD-EFGH')
    await userEvent.click(screen.getByRole('button', { name: 'Activeren' }))
    expect(await screen.findByText('Welkom, Jan')).toBeInTheDocument()
    await tikCode('13579')
    expect(await screen.findByText('Nog één keer')).toBeInTheDocument()
    await tikCode('13579')
    await waitFor(() => expect(naGeactiveerd).toHaveBeenCalledTimes(1))
    expect(naGeactiveerd.mock.calls[0][0]).toMatchObject({ access_token: ACTIVATIE_OK.access_token, refresh_token: 'rt-1' })
    expect(await isAppSlotIngesteld()).toBe(true)
    expect(isOntgrendeld()).toBe(true)
    expect(await haalCredentialId()).toBe('cred-1')
    const akkoord = aanroepen.find((a) => a.pad === '/auth/accordeur/voorwaarden-akkoord')
    expect(akkoord?.methode).toBe('POST')
    expect(akkoord?.headers.get('Authorization')).toBe(`Bearer ${ACTIVATIE_OK.access_token}`)
    expect(localStorage.getItem(SLOT_MODUS_SLEUTEL)).toBe('1')
    // Biometrie zit NIET in de activatieflow: nergens een Face ID-vraag.
    expect(screen.queryByText(/Face ID/)).toBeNull()
  })

  it('herstel-activatie → neutrale kop "Kies een code" (geen "Welkom")', async () => {
    stubFetch({ '/auth/app/activeren': () => Promise.resolve(jsonResponse({ ...ACTIVATIE_OK, herstel: true })) })
    renderScherm()
    await userEvent.type(screen.getByLabelText('Activatiecode'), 'ABCDEFGH')
    await userEvent.click(screen.getByRole('button', { name: 'Activeren' }))
    expect(await screen.findByText('Kies een code')).toBeInTheDocument()
  })
})
