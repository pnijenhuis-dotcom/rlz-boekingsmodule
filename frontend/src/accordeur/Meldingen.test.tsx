// Schermtests meldingen (berichten-bouwsteen 2026-08-15; UX-besluit Peter 2026-08-17, HERZIEN
// 26-08 blok B3): de wel/geen-meldingen-keuze zit UITSLUITEND nog éénmalig in de activeringsflow
// (ná het voorwaarden-akkoord); het 🔔-hoekje, de meldingen-popup en de wachtrij-kaart bestaan niet
// meer — om-/uitzetten gebeurt in de telefooninstellingen. Permissie pas ná de expliciete klik,
// keuze per apparaat onthouden (aan/uit/mislukt), eerlijke fout + één herkansing, ?document=-deep-link.

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

/** Activeringsflow-stubs: wachtrij eist eerst het voorwaarden-akkoord (403), daarna items. */
function activeringsRoutes(items: WachtrijItemDto[]): FetchAntwoorden {
  let akkoord = false
  return {
    ...basisRoutes(items),
    '/accordering/wachtrij': () =>
      akkoord ? jsonResponse({ items }) : jsonResponse({ detail: 'voorwaarden_akkoord_vereist' }, 403),
    '/accordering/vragen': () => jsonResponse({ items: [] }),
    '/auth/accordeur/voorwaarden': () =>
      jsonResponse({ tekst_versie: '2026-08', tekst: 'Voorwaardentekst', akkoord_gegeven: false, administratie_namen: ['BLOW B.V.'] }),
    '/auth/accordeur/voorwaarden-akkoord': () => {
      akkoord = true
      return new Response(null, { status: 204 })
    },
  }
}

async function doorloopVoorwaarden() {
  await userEvent.click(await screen.findByRole('checkbox'))
  await userEvent.click(screen.getByRole('button', { name: 'Akkoord en beginnen' }))
}

describe('Meldingen (éénmalig in de activeringsflow — blok B3 26-08)', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} }))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    // @ts-expect-error opruimen van de test-stub
    delete navigator.serviceWorker
  })

  it('wachtrij heeft géén 🔔-hoekje, géén meldingen-popup en géén eenmalige kaart meer', async () => {
    stubPushOmgeving('default')
    const routes = { ...basisRoutes([ITEM]), '/accordering/vragen': () => jsonResponse({ items: [] }) }
    stubFetch(routes)
    renderFlow()
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Meldingen' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Dagelijkse herinnering · 09:00/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Zet meldingen aan' })).not.toBeInTheDocument()
    // compacte header (feedbackpunt 1): geen administraties-namenlijst
    expect(screen.queryByText('BLOW B.V.')).not.toBeInTheDocument()
  })

  it('activeringsflow: voorstel ná het voorwaarden-akkoord, registratie pas ná de klik, keuze "aan" onthouden', async () => {
    const push = stubPushOmgeving('default')
    const routes = activeringsRoutes([ITEM])
    const subscripties: unknown[] = []
    routes['/notificaties/push/subscripties'] = (init) => {
      subscripties.push(JSON.parse(String(init?.body)))
      return jsonResponse({ id: 's1', endpoint: 'https://push.example/sub1', aangemaakt_op: '2026-08-15T09:00:00Z' }, 201)
    }
    stubFetch(routes)
    renderFlow()
    await doorloopVoorwaarden()

    const knop = await screen.findByRole('button', { name: 'Zet meldingen aan' })
    expect(screen.getByText('Meldingen aanzetten?')).toBeInTheDocument()
    // de tekst verwijst niet meer naar een 🔔-hoekje maar naar de telefooninstellingen
    expect(screen.getByText(/instellingen van uw telefoon/)).toBeInTheDocument()
    expect(push.registraties).toHaveLength(0)
    await userEvent.click(knop)

    await waitFor(() => expect(subscripties).toHaveLength(1))
    expect(push.registraties).toEqual(['/accordeur-sw.js'])
    expect(localStorage.getItem('accordeur_meldingen_keuze')).toBe('aan')
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
  })

  it('activeringsflow: "Niet nu" onthoudt "uit" en het voorstel komt nooit meer terug', async () => {
    stubPushOmgeving('default')
    stubFetch(activeringsRoutes([ITEM]))
    renderFlow()
    await doorloopVoorwaarden()
    await userEvent.click(await screen.findByRole('button', { name: 'Niet nu' }))
    expect(localStorage.getItem('accordeur_meldingen_keuze')).toBe('uit')
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Zet meldingen aan' })).not.toBeInTheDocument()
  })

  it('activeringsflow: mislukken = eerlijke fout-toast + één herkansing; tweede mislukking onthoudt "mislukt"', async () => {
    stubPushOmgeving('default')
    const routes = activeringsRoutes([ITEM])
    routes['/notificaties/push/subscripties'] = () => jsonResponse({ detail: 'serverfout' }, 500)
    stubFetch(routes)
    renderFlow()
    await doorloopVoorwaarden()
    await userEvent.click(await screen.findByRole('button', { name: 'Zet meldingen aan' }))
    expect(await screen.findByText(/Meldingen aanzetten mislukte/)).toBeInTheDocument()
    expect(localStorage.getItem('accordeur_meldingen_keuze')).toBeNull()
    await userEvent.click(await screen.findByRole('button', { name: 'Zet meldingen aan' }))
    await waitFor(() => expect(localStorage.getItem('accordeur_meldingen_keuze')).toBe('mislukt'))
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
  })

  it('geen voorstel meer zodra er op dit apparaat een keuze ligt', async () => {
    localStorage.setItem('accordeur_meldingen_keuze', 'uit')
    stubPushOmgeving('default')
    stubFetch(activeringsRoutes([ITEM]))
    renderFlow()
    await doorloopVoorwaarden()
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
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
