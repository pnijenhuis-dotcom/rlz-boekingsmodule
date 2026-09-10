// Shell-vertakkingen (app-auth zonder passkey en TOTP, besluit Peter 08-09-2026, contract §5c):
// verse installatie → activatiescherm; slot vergrendeld → AppSlotScherm → toegangscode → stille
// refresh mét slot-headers → flow; 5× fout → uitgesloten + melding; sessie server-side dood → slot
// gewist + activatiescherm mét melding; universal link mét ?document= → activatie → toegangscode →
// /accordeur?document=; legacy toestel (plain token, geen slot) → PincodeKiezen; header-"Vergrendelen"
// = vergrendelen. Draait in de PWA-slotmodus (jsdom op /accordeur + fake IndexedDB + WebCrypto);
// het legacy-pad stubt de native schil.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { webcrypto } from 'node:crypto'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { MAX_FOUTEN, bewaarCredentialId, isAppSlotIngesteld, resterendePogingen, stelCodeIn, vergrendel, wisAppSlotLokaal } from '../api/appSlot'
import { setAccessToken } from '../api/client'
import { installeerFakeIndexedDb } from '../api/fakeIndexedDb.testhulp'
import { bewaarNatiefRefreshToken } from '../api/nativeSessie'
import { AuthProvider } from '../auth/AuthContext'
import AccordeurApp from './AccordeurApp'
import { TOEGANG_VERLOPEN_MELDING } from './AppActiveren'

if (!globalThis.crypto?.subtle) {
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true })
}

// Node 22+ schaduwt window.localStorage/sessionStorage in de jsdom-testomgeving met zijn eigen (lege)
// experimental global — in-memory vervanger, zelfde patroon als ReviewSplitter.test.tsx.
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
  sessionStorage.clear()
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

const SESSIE = { access_token: fakeToken({ rol: 'klant_accordeur', sub: 'u1' }), token_type: 'bearer', refresh_token: 'rt-nieuw' }

function stubFetch(overrides: Record<string, (a: Aanroep) => Promise<Response>> = {}): Aanroep[] {
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
        case '/auth/token/vernieuwen':
          return Promise.resolve(jsonResponse(SESSIE))
        case '/auth/token/vernieuwen/logout':
          return Promise.resolve(new Response(null, { status: 204 }))
        case '/auth/app/activeren':
          return Promise.resolve(
            jsonResponse({ ...SESSIE, refresh_token: 'rt-1', apparaat_credential_id: 'cred-1', naam: 'Jan', herstel: false }),
          )
        case '/auth/uitnodigingen/info':
          return Promise.resolve(jsonResponse({ flow: 'app', naam: 'Jan', herstel: false, verloopt_op: 'x' }))
        case '/auth/accordeur/voorwaarden-akkoord':
        case '/auth/app-lock/uitgesloten':
        case '/auth/app-lock/hulp':
          return Promise.resolve(new Response(null, { status: 204 }))
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
  return aanroepen
}

function LocationSpion() {
  const loc = useLocation()
  return <div data-testid="locatie">{`${loc.pathname}${loc.search}`}</div>
}

function renderApp(begin = '/accordeur') {
  return render(
    <MemoryRouter initialEntries={[begin]}>
      <AuthProvider>
        <AccordeurApp />
        <LocationSpion />
      </AuthProvider>
    </MemoryRouter>,
  )
}

/** Geactiveerd toestel mét dicht slot (koude start): slot + versleuteld refresh-token + toestel-id. */
async function geactiveerdToestelMetDichtSlot(code = '13579') {
  await stelCodeIn(code)
  await bewaarNatiefRefreshToken('rt-oud')
  await bewaarCredentialId('cred-1')
  vergrendel()
}

async function tikCode(code: string) {
  for (const c of code) await userEvent.click(screen.getByRole('button', { name: c }))
}

describe('AccordeurApp — verse installatie', () => {
  it('geen slot en geen sessie → activatiescherm, zónder vernieuwen-POST (slot-opslag zonder token = geen rondje)', async () => {
    const aanroepen = stubFetch()
    renderApp()
    expect(await screen.findByText('Activatiecode invoeren')).toBeInTheDocument()
    expect(aanroepen.some((a) => a.pad === '/auth/token/vernieuwen')).toBe(false)
    // Geen enkel spoor van het oude login-scherm.
    expect(screen.queryByRole('button', { name: 'Inloggen' })).toBeNull()
    expect(screen.queryByLabelText('E-mailadres')).toBeNull()
  })
})

describe('AccordeurApp — slot vergrendeld (koude start van een geactiveerd toestel)', () => {
  it('toegangscode → stille refresh mét X-App-Slot + X-Refresh-Token (geen X-Native-Client) → flow; het geroteerde token gaat achter het slot', async () => {
    await geactiveerdToestelMetDichtSlot()
    const aanroepen = stubFetch()
    renderApp()
    expect(await screen.findByText('Voer je code in')).toBeInTheDocument()
    await tikCode('13579')
    expect(await screen.findByText('Alles is bij', undefined, { timeout: 3000 })).toBeInTheDocument()
    const refresh = aanroepen.find((a) => a.pad === '/auth/token/vernieuwen')!
    expect(refresh.methode).toBe('POST')
    expect(refresh.headers.get('X-App-Slot')).toBe('1')
    expect(refresh.headers.get('X-Refresh-Token')).toBe('rt-oud')
    expect(refresh.headers.has('X-Native-Client')).toBe(false)
    await waitFor(() => expect(idb.data.get('accordeur-slot')?.get('kv')?.get('refresh_token')).toMatch(/^slot\.v1\./))
  })

  it('5× foute code → slot + sessie lokaal gewist, uitsluiting gemeld op het toestel-id, "Activatiecode invoeren" → activatiescherm mét melding', async () => {
    await geactiveerdToestelMetDichtSlot()
    const aanroepen = stubFetch()
    renderApp()
    await screen.findByText('Voer je code in')
    // Elke poging wacht op de PBKDF2-verificatie (200k iteraties) vóór de volgende — anders vallen
    // cijfers weg zolang de vorige poging nog loopt (het scherm negeert invoer bij 5 gevulde dots).
    for (let i = 0; i < MAX_FOUTEN; i++) {
      await tikCode('00001')
      if (i < MAX_FOUTEN - 1) await waitFor(async () => expect(await resterendePogingen()).toBe(MAX_FOUTEN - i - 1), { timeout: 3000 })
    }
    expect(await screen.findByText('Even opnieuw beginnen', undefined, { timeout: 3000 })).toBeInTheDocument()
    await waitFor(() => expect(aanroepen.find((a) => a.pad === '/auth/app-lock/uitgesloten')?.body).toEqual({ credential_id: 'cred-1' }))
    expect(await isAppSlotIngesteld()).toBe(false)
    expect(screen.getByRole('button', { name: 'Kantoor vragen om nieuwe uitnodiging' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Activatiecode invoeren' }))
    expect(await screen.findByRole('status')).toHaveTextContent(TOEGANG_VERLOPEN_MELDING)
    expect(aanroepen.some((a) => a.pad === '/auth/token/vernieuwen')).toBe(false)
  })

  it('code goed maar sessie server-side dood (401 op vernieuwen: kill-switch/7 dagen) → slot gewist → activatiescherm mét melding', async () => {
    await geactiveerdToestelMetDichtSlot()
    stubFetch({ '/auth/token/vernieuwen': () => Promise.resolve(jsonResponse({ detail: 'ingetrokken' }, 401)) })
    renderApp()
    await screen.findByText('Voer je code in')
    await tikCode('13579')
    expect(await screen.findByRole('status')).toHaveTextContent(TOEGANG_VERLOPEN_MELDING)
    expect(screen.getByText('Activatiecode invoeren')).toBeInTheDocument()
    expect(await isAppSlotIngesteld()).toBe(false)
  })

  it('header-"Vergrendelen" in de flow = vergrendelen: terug naar het slot, géén logout-POST, toestel blijft gekoppeld', async () => {
    await geactiveerdToestelMetDichtSlot()
    const aanroepen = stubFetch()
    renderApp()
    await screen.findByText('Voer je code in')
    await tikCode('13579')
    await screen.findByText('Alles is bij', undefined, { timeout: 3000 })
    await userEvent.click(screen.getByRole('button', { name: 'Vergrendelen' }))
    expect(await screen.findByText('Voer je code in')).toBeInTheDocument()
    expect(aanroepen.some((a) => a.pad === '/auth/token/vernieuwen/logout')).toBe(false)
    expect(await isAppSlotIngesteld()).toBe(true)
  })
})

describe('AccordeurApp — universal link', () => {
  it('/accordeur/activeren?uitnodiging=…&document=42 → Welkom → activeren → toegangscode → /accordeur?document=42', async () => {
    const aanroepen = stubFetch()
    renderApp('/accordeur/activeren?uitnodiging=tok-1&document=42')
    await userEvent.click(await screen.findByRole('button', { name: 'Dit toestel activeren' }))
    expect(await screen.findByText('Welkom, Jan')).toBeInTheDocument()
    await tikCode('13579')
    await screen.findByText('Nog één keer')
    await tikCode('13579')
    await waitFor(() => expect(screen.getByTestId('locatie')).toHaveTextContent('/accordeur?document=42'))
    expect(aanroepen.find((a) => a.pad === '/auth/app/activeren')?.body).toMatchObject({ token: 'tok-1' })
    expect(screen.queryByText('Activatiecode invoeren')).toBeNull()
    expect(await isAppSlotIngesteld()).toBe(true)
  })
})

describe('AccordeurApp — legacy native toestel (plain refresh-token, geen slot)', () => {
  it('levende sessie → PincodeKiezen (verplicht) → token achter het slot → flow', async () => {
    const opslag = new Map<string, string>([['refresh_token', 'rt-plain']])
    vi.stubGlobal('Capacitor', {
      isNativePlatform: () => true,
      getPlatform: () => 'ios',
      Plugins: {
        VeiligeOpslag: {
          zet: ({ sleutel, waarde }: { sleutel: string; waarde: string }) => {
            opslag.set(sleutel, waarde)
            return Promise.resolve()
          },
          haal: ({ sleutel }: { sleutel: string }) => Promise.resolve({ waarde: opslag.get(sleutel) ?? null }),
          verwijder: ({ sleutel }: { sleutel: string }) => {
            opslag.delete(sleutel)
            return Promise.resolve()
          },
        },
      },
    })
    const aanroepen = stubFetch()
    renderApp()
    expect(await screen.findByText('Kies een code')).toBeInTheDocument()
    const refresh = aanroepen.find((a) => a.pad === '/auth/token/vernieuwen')!
    expect(refresh.headers.get('X-Native-Client')).toBe('1')
    expect(refresh.headers.get('X-Refresh-Token')).toBe('rt-plain')
    await tikCode('13579')
    await screen.findByText('Nog één keer')
    await tikCode('13579')
    expect(await screen.findByText('Alles is bij', undefined, { timeout: 3000 })).toBeInTheDocument()
    expect(opslag.get('refresh_token')).toMatch(/^slot\.v1\./)
  })

  it('eerste opslag van de code mislukt (Keystore weigert appslot_slot) → melding + diagnoseregel, NIET door naar de flow; "Opnieuw proberen" → PincodeKiezen → tweede poging slaagt → flow (bugfix 10-09 (2))', async () => {
    const opslag = new Map<string, string>([['refresh_token', 'rt-plain']])
    let weigerSlotSchrijf = true
    vi.stubGlobal('Capacitor', {
      isNativePlatform: () => true,
      getPlatform: () => 'android',
      Plugins: {
        VeiligeOpslag: {
          zet: ({ sleutel, waarde }: { sleutel: string; waarde: string }) => {
            if (sleutel === 'appslot_slot' && weigerSlotSchrijf) return Promise.reject(new Error('KeyStoreException: write failed'))
            opslag.set(sleutel, waarde)
            return Promise.resolve()
          },
          haal: ({ sleutel }: { sleutel: string }) => Promise.resolve({ waarde: opslag.get(sleutel) ?? null }),
          verwijder: ({ sleutel }: { sleutel: string }) => {
            opslag.delete(sleutel)
            return Promise.resolve()
          },
        },
      },
    })
    stubFetch()
    renderApp()
    expect(await screen.findByText('Kies een code')).toBeInTheDocument()
    await tikCode('13579')
    await screen.findByText('Nog één keer')
    await tikCode('13579')
    expect(await screen.findByText('Toegangscode niet opgeslagen')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('De toegangscode kon niet veilig op dit toestel worden opgeslagen')
    const diagnose = screen.getByTestId('acc-diagnose').textContent ?? ''
    expect(diagnose).toContain('laatste slotfout: schrijf appslot_slot (Error: KeyStoreException: write failed)')
    expect(diagnose).not.toContain('13579')
    // Niet door: geen wachtrij, token nog plain (de stille refresh roteerde 'm, maar hij is NIET met een nergens
    // bewaard anker versleuteld — anders was hij ná de koude start onleesbaar), geen slot.
    expect(screen.queryByText('Alles is bij')).toBeNull()
    expect(opslag.get('refresh_token')).not.toMatch(/^slot\.v1\./)
    expect(opslag.has('appslot_slot')).toBe(false)
    weigerSlotSchrijf = false
    await userEvent.click(screen.getByRole('button', { name: 'Opnieuw proberen' }))
    expect(await screen.findByText('Kies een code')).toBeInTheDocument()
    await tikCode('13579')
    await screen.findByText('Nog één keer')
    await tikCode('13579')
    expect(await screen.findByText('Alles is bij', undefined, { timeout: 3000 })).toBeInTheDocument()
    expect(opslag.get('refresh_token')).toMatch(/^slot\.v1\./)
    expect(opslag.get('appslot_slot')).toMatch(/^v2\./)
  })

  it('negeert ontgrendeling_nodig: true van de server (upgrade 89 → 90 op een passkey-rij): geen ceremonie, wél PincodeKiezen', async () => {
    // Migratie 0125 zet bestaande app-credentials niet om; de server rekent op zo'n rij het oude
    // 24-uursvenster nog uit. Build 90 kent geen ontgrendel-ceremonie meer en mag daar niets mee doen.
    const opslag = new Map<string, string>([['refresh_token', 'rt-plain']])
    vi.stubGlobal('Capacitor', {
      isNativePlatform: () => true,
      getPlatform: () => 'ios',
      Plugins: {
        VeiligeOpslag: {
          zet: ({ sleutel, waarde }: { sleutel: string; waarde: string }) => {
            opslag.set(sleutel, waarde)
            return Promise.resolve()
          },
          haal: ({ sleutel }: { sleutel: string }) => Promise.resolve({ waarde: opslag.get(sleutel) ?? null }),
          verwijder: ({ sleutel }: { sleutel: string }) => {
            opslag.delete(sleutel)
            return Promise.resolve()
          },
        },
      },
    })
    const aanroepen = stubFetch({
      '/auth/token/vernieuwen': () => Promise.resolve(jsonResponse({ ...SESSIE, ontgrendeling_nodig: true })),
    })
    renderApp()
    expect(await screen.findByText('Kies een code')).toBeInTheDocument()
    await tikCode('13579')
    await screen.findByText('Nog één keer')
    await tikCode('13579')
    expect(await screen.findByText('Alles is bij', undefined, { timeout: 3000 })).toBeInTheDocument()
    // Geen passkey-/ontgrendel-verkeer en geen ontgrendel- of inlogtekst: de vlag is dood voor de app.
    expect(aanroepen.some((a) => a.pad.startsWith('/auth/token/vernieuwen/ontgrendel'))).toBe(false)
    expect(aanroepen.some((a) => a.pad.startsWith('/auth/webauthn/') && a.pad !== '/auth/webauthn/config')).toBe(false)
    expect(screen.queryByText(/ontgrendel/i)).toBeNull()
    expect(screen.queryByText(/passkey|inloggen/i)).toBeNull()
    expect(opslag.get('refresh_token')).toMatch(/^slot\.v1\./)
  })
})
