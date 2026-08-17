// Schermtests meldingen (berichten-bouwsteen 2026-08-15; UX-besluit Peter 2026-08-17):
// permissie-flow via expliciete klik op de EENMALIGE wachtrij-kaart, keuze per apparaat
// onthouden (aan/uit/mislukt — kaart verdwijnt na élke uitkomst), eerlijke fout + één
// herkansing, het 🔔-hoekje als blijvende beheerplek, en de ?document=-deep-link.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { GoedkeurenFlow } from './GoedkeurenFlow'
import type { WachtrijItemDto } from './accordeurApi'

const ITEM: WachtrijItemDto = {
  document_id: 'd1',
  administratie_id: 'a1',
  administratie_naam: 'BLOW B.V.',
  leverancier_naam: 'Essent Zakelijk',
  referentie: 'E-2026-07-8841',
  factuurdatum: '2026-07-01',
  totaalbedrag: '847.00',
  aangeboden_op: '2026-07-02T09:00:00Z',
  laag_volgnummer: 1,
  boeking_omschrijving: 'Gas, water en elektra · btw 21%',
  staande_regel_kandidaat: false,
}

// Node 22+ schaduwt window.localStorage in de jsdom-testomgeving met zijn eigen (lege)
// experimental global — in-memory vervanger, zelfde patroon als AccordeurApp.test.tsx.
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
})

type FetchAntwoorden = Record<string, (init?: RequestInit) => Response>

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

function basisRoutes(items: WachtrijItemDto[]): FetchAntwoorden {
  return {
    '/auth/token/vernieuwen': () => new Response(null, { status: 401 }),
    '/accordering/wachtrij': () => jsonResponse({ items }),
    '/auth/administraties': () => jsonResponse({ administraties: [{ id: 'a1', naam: 'BLOW B.V.' }] }),
    '/administraties/a1/documenten/d1/bestand': () =>
      new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 }),
    '/notificaties/push/config': () => jsonResponse({ publieke_sleutel: 'sleutel-b64url' }),
  }
}

interface PushStub {
  subscribeAanroepen: number
  registraties: string[]
}

/** jsdom kent geen SW/Push API — expliciete stubs; permission instelbaar per test. */
function stubPushOmgeving(permissie: NotificationPermission, naPrompt: NotificationPermission = 'granted'): PushStub {
  const stub: PushStub = { subscribeAanroepen: 0, registraties: [] }
  const subscription = {
    endpoint: 'https://push.example/sub1',
    toJSON: () => ({ endpoint: 'https://push.example/sub1', keys: { p256dh: 'p', auth: 'a' } }),
    unsubscribe: () => Promise.resolve(true),
  }
  const registratie = {
    pushManager: {
      getSubscription: () => Promise.resolve(null),
      subscribe: () => {
        stub.subscribeAanroepen += 1
        return Promise.resolve(subscription)
      },
    },
  }
  vi.stubGlobal('Notification', {
    permission: permissie,
    requestPermission: () => Promise.resolve(naPrompt),
  })
  vi.stubGlobal('PushManager', function PushManager() {})
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: {
      register: (pad: string) => {
        stub.registraties.push(pad)
        return Promise.resolve(registratie)
      },
      getRegistration: () => Promise.resolve(undefined),
      getRegistrations: () => Promise.resolve([]),
    },
  })
  return stub
}

function renderFlow(startPad = '/accordeur') {
  return render(
    <MemoryRouter initialEntries={[startPad]}>
      <AuthProvider>
        <GoedkeurenFlow wisselThema={() => {}} uitloggen={() => Promise.resolve()} />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('Meldingen (push-permissieflow)', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} }))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    // @ts-expect-error opruimen van de test-stub
    delete navigator.serviceWorker
  })

  it('toont de eenmalige kaart, registreert SW + subscriptie pas ná de klik en onthoudt "aan"', async () => {
    const push = stubPushOmgeving('default')
    const routes = basisRoutes([ITEM])
    const subscripties: unknown[] = []
    routes['/notificaties/push/subscripties'] = (init) => {
      subscripties.push(JSON.parse(String(init?.body)))
      return jsonResponse({ id: 's1', endpoint: 'https://push.example/sub1', aangemaakt_op: '2026-08-15T09:00:00Z' }, 201)
    }
    stubFetch(routes)
    renderFlow()

    const knop = await screen.findByRole('button', { name: 'Zet meldingen aan' })
    // Nooit rauw bij het laden: vóór de klik géén registratie of permissieprompt-gevolg.
    expect(push.registraties).toHaveLength(0)
    await userEvent.click(knop)

    await waitFor(() => expect(subscripties).toHaveLength(1))
    expect(push.registraties).toEqual(['/accordeur-sw.js'])
    expect(push.subscribeAanroepen).toBe(1)
    expect(subscripties[0]).toEqual({ endpoint: 'https://push.example/sub1', p256dh: 'p', auth: 'a' })
    // Uitkomst "aan" onthouden → de kaart verdwijnt, de wachtrij blijft schoon.
    expect(localStorage.getItem('accordeur_meldingen_keuze')).toBe('aan')
    await waitFor(() => expect(screen.queryByText(/Dagelijkse herinnering · 09:00/)).not.toBeInTheDocument())
  })

  it('"niet nu" onthoudt de keuze per apparaat en laat de kaart blijvend verdwijnen', async () => {
    stubPushOmgeving('default')
    stubFetch(basisRoutes([ITEM]))
    renderFlow()
    await userEvent.click(await screen.findByRole('button', { name: 'niet nu' }))
    expect(localStorage.getItem('accordeur_meldingen_keuze')).toBe('uit')
    expect(screen.queryByText(/Dagelijkse herinnering/)).not.toBeInTheDocument()
  })

  it('toont de kaart niet meer zodra er een keuze onthouden is', async () => {
    localStorage.setItem('accordeur_meldingen_keuze', 'uit')
    stubPushOmgeving('default')
    stubFetch(basisRoutes([ITEM]))
    renderFlow()
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
    expect(screen.queryByText(/Dagelijkse herinnering/)).not.toBeInTheDocument()
  })

  it('mislukken = eerlijke fout-toast + één herkansing; tweede mislukking onthoudt "mislukt"', async () => {
    stubPushOmgeving('default')
    const routes = basisRoutes([ITEM])
    routes['/notificaties/push/subscripties'] = () => jsonResponse({ detail: 'serverfout' }, 500)
    stubFetch(routes)
    renderFlow()

    // Eerste poging: eerlijke fout, kaart blijft staan (de herkansing).
    await userEvent.click(await screen.findByRole('button', { name: 'Zet meldingen aan' }))
    expect(await screen.findByText(/Meldingen aanzetten mislukte/)).toBeInTheDocument()
    expect(localStorage.getItem('accordeur_meldingen_keuze')).toBeNull()
    const herkansing = await screen.findByRole('button', { name: 'Zet meldingen aan' })

    // Tweede mislukking: uitkomst "mislukt" onthouden, geen permanente banner.
    await userEvent.click(herkansing)
    await waitFor(() => expect(localStorage.getItem('accordeur_meldingen_keuze')).toBe('mislukt'))
    await waitFor(() => expect(screen.queryByText(/Dagelijkse herinnering/)).not.toBeInTheDocument())
  })

  it('geweigerde browserpermissie geeft géén permanente banner; de uitleg staat in het 🔔-hoekje', async () => {
    stubPushOmgeving('denied')
    stubFetch(basisRoutes([ITEM]))
    renderFlow()
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
    expect(screen.queryByText(/geblokkeerd/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Zet meldingen aan' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Meldingen' }))
    expect(await screen.findByText(/geblokkeerd in je toestel- of browserinstellingen/)).toBeInTheDocument()
  })

  it('meldingen later alsnog aanzetten kan via het 🔔-hoekje, ook mét onthouden "uit"-keuze', async () => {
    localStorage.setItem('accordeur_meldingen_keuze', 'uit')
    stubPushOmgeving('default')
    const routes = basisRoutes([ITEM])
    const subscripties: unknown[] = []
    routes['/notificaties/push/subscripties'] = (init) => {
      subscripties.push(JSON.parse(String(init?.body)))
      return jsonResponse({ id: 's1', endpoint: 'https://push.example/sub1', aangemaakt_op: '2026-08-15T09:00:00Z' }, 201)
    }
    stubFetch(routes)
    renderFlow()

    await screen.findByText('1 factuur wacht op je akkoord')
    await userEvent.click(screen.getByRole('button', { name: 'Meldingen' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Zet meldingen aan' }))
    await waitFor(() => expect(subscripties).toHaveLength(1))
    expect(localStorage.getItem('accordeur_meldingen_keuze')).toBe('aan')
  })

  it('verbergt kaart én sheet-aanzetknop als push niet ondersteund wordt (geen SW/Push API)', async () => {
    stubFetch(basisRoutes([ITEM]))
    renderFlow()
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
    expect(screen.queryByText(/Dagelijkse herinnering/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Zet meldingen aan' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Meldingen' }))
    expect(await screen.findByText(/niet ondersteund/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Zet meldingen aan' })).not.toBeInTheDocument()
  })

  it('?document=<id> deep-linkt naar het review-scherm van dat document', async () => {
    stubFetch(basisRoutes([ITEM]))
    renderFlow('/accordeur?document=d1')
    expect(await screen.findByText('Gas, water en elektra · btw 21%')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Akkoord ✓' })).toBeInTheDocument()
  })

  it('?document= met onbekend id valt gewoon terug op de wachtrij', async () => {
    stubFetch(basisRoutes([ITEM]))
    renderFlow('/accordeur?document=bestaat-niet')
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
  })
})
