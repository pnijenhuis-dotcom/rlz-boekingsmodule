// Schermtests meldingen (berichten-bouwsteen 2026-08-15): permissie-flow via expliciete klik
// (banner in de wachtrij), status-varianten, en de ?document=-deep-link uit mail/push.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} }))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    // @ts-expect-error opruimen van de test-stub
    delete navigator.serviceWorker
  })

  it('toont de aanzet-knop en registreert SW + subscriptie pas ná de klik', async () => {
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
    expect(await screen.findByText(/Dagelijkse herinnering · 09:00/)).toBeInTheDocument()
  })

  it('toont de geblokkeerd-uitleg als de browserpermissie geweigerd is', async () => {
    stubPushOmgeving('denied')
    stubFetch(basisRoutes([ITEM]))
    renderFlow()
    expect(await screen.findByText(/geblokkeerd in je browserinstellingen/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Zet meldingen aan' })).not.toBeInTheDocument()
  })

  it('verbergt de banner als push niet ondersteund wordt (geen SW/Push API)', async () => {
    stubFetch(basisRoutes([ITEM]))
    renderFlow()
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
    expect(screen.queryByText(/Dagelijkse herinnering/)).not.toBeInTheDocument()
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
