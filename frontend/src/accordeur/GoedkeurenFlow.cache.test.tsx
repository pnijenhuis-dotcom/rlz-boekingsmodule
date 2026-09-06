// Cache-first + parallel laden (blokken D2/D3 06-09, bankscherm-patroon): de laatst bekende stand
// van DEZE gebruiker staat er direct met "stand van HH:MM · verversen…", de geldknoppen staan tot de
// verse stand op slot, verse data vervangt stil (geen skeleton), een verdwenen item gaat mét toast
// terug naar de wachtrij; zonder cache de gewone laadstate; vragen-fetch start parallel; een
// voorgeladen stand wordt overgenomen (één wachtrij-call).

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { setAccessToken } from '../api/client'
import { AuthProvider, useAuth } from '../auth/AuthContext'
import type { WachtrijItemDto } from './accordeurApi'
import { besluitVerzender } from './besluitQueue'
import { GoedkeurenFlow } from './GoedkeurenFlow'
import { resetVoorTests as resetKoudeStart } from './koudeStart'
import { factuurCache } from './pdfCache'
import { bewaarStand, leesStand } from './standCache'
import { resetVoorladerVoorTests, voorlaadStand } from './voorlader'

const KEMPEN_1: WachtrijItemDto = {
  document_id: 'k1',
  administratie_id: 'kempen',
  administratie_naam: 'Kempen Facilities B.V.',
  leverancier_naam: 'LUSSO Interieurbouw',
  referentie: 'L-1',
  factuurdatum: '2026-08-20',
  totaalbedrag: '1132.51',
  aangeboden_op: '2026-08-25T09:00:00Z',
  laag_volgnummer: 1,
  boeking_omschrijving: 'Diverse inkopen',
  staande_regel_kandidaat: false,
}
const KEMPEN_2: WachtrijItemDto = { ...KEMPEN_1, document_id: 'k2', leverancier_naam: 'Boels Verhuur B.V.', totaalbedrag: '486.10' }

// Node 22+ schaduwt window.localStorage in de jsdom-testomgeving met zijn eigen (lege) experimental
// global — in-memory vervanger, zelfde patroon als AccordeurApp.test.tsx.
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

/** Ongetekend JWT met alleen de payload (decodeerJwtPayload verifieert bewust niet). */
function nepJwt(sub: string): string {
  const payload = btoa(JSON.stringify({ sub, rol: 'klant_accordeur' })).replace(/=+$/, '')
  return `kop.${payload}.sig`
}

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

const besluitOk = () =>
  jsonResponse({
    accordering: { id: 'x', document_id: 'd', status: 'afgerond', aangeboden_op: '', afgerond_op: null, stappen: [] },
    alles_akkoord: true,
    geboekt: true,
    boek_fout: null,
    staande_regel_id: null,
  })

interface Uitgesteld {
  geef: (items: WachtrijItemDto[]) => void
}

/** Routes mét een uitgestelde wachtrij (de test bepaalt wanneer de verse stand komt). */
function routes(gebruiker: string, uitgesteld: Uitgesteld | null, items: WachtrijItemDto[] = []): FetchAntwoorden {
  const pdf = () => new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 })
  return {
    '/auth/token/vernieuwen': () => jsonResponse({ access_token: nepJwt(gebruiker), token_type: 'bearer' }),
    '/accordering/wachtrij': () =>
      uitgesteld
        ? new Promise<Response>((r) => {
            uitgesteld.geef = (nieuw) => r(jsonResponse({ items: nieuw }))
          })
        : jsonResponse({ items }),
    '/accordering/vragen': () => jsonResponse({ items: [] }),
    '/auth/administraties': () => jsonResponse({ administraties: [] }),
    '/administraties/kempen/documenten/k1/bestand': pdf,
    '/administraties/kempen/documenten/k2/bestand': pdf,
    '/administraties/kempen/accordering/documenten/k1/akkoord': besluitOk,
  }
}

/** Zoals in de app: de flow monteert pas mét een sessie (gebruikers-id uit het JWT). */
function Gate() {
  const { status } = useAuth()
  return status === 'ingelogd' ? <GoedkeurenFlow wisselThema={() => {}} uitloggen={() => Promise.resolve()} /> : null
}

function renderFlow() {
  return render(
    <MemoryRouter initialEntries={['/accordeur']}>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </MemoryRouter>,
  )
}

const aantalCalls = (mock: ReturnType<typeof vi.fn>, pad: string) =>
  mock.mock.calls.filter((c) => String(c[0]).split('?')[0] === pad).length

describe('GoedkeurenFlow — cache-first (D2) + parallel laden (D3)', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} }))
    besluitVerzender.resetVoorTests()
    factuurCache.resetVoorTests()
    resetVoorladerVoorTests()
    resetKoudeStart()
    localStorage.clear()
    setAccessToken(null)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('toont de cache direct met "stand van HH:MM · verversen…", houdt de geldknoppen op slot en laat ze los zodra de verse stand er is', async () => {
    bewaarStand('u-1', [KEMPEN_1], [])
    const uitgesteld: Uitgesteld = { geef: () => {} }
    const mock = stubFetch(routes('u-1', uitgesteld))
    renderFlow()

    // Cache direct, geen skeleton.
    expect(await screen.findByText('LUSSO Interieurbouw')).toBeInTheDocument()
    expect(screen.queryByText('Wachtrij laden…')).not.toBeInTheDocument()
    expect(screen.getByTestId('acc-versheid')).toHaveTextContent(/^stand van \d\d:\d\d · verversen…$/)

    // Lezen mag; het geldbesluit niet — tot de verse stand er is.
    await userEvent.click(screen.getByText('LUSSO Interieurbouw'))
    const opSlot = await screen.findAllByRole('button', { name: 'verversen…' })
    expect(opSlot).toHaveLength(2)
    opSlot.forEach((knop) => expect(knop).toBeDisabled())
    expect(aantalCalls(mock, '/administraties/kempen/accordering/documenten/k1/akkoord')).toBe(0)

    // Verse stand mét hetzelfde item: knoppen los, "laatst ververst", cache vernieuwd.
    uitgesteld.geef([KEMPEN_1])
    const akkoordKnop = await screen.findByRole('button', { name: 'Akkoord ✓' })
    expect(akkoordKnop).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Afwijzen' })).toBeEnabled()
    await new Promise((r) => setTimeout(r, 350)) // dubbeltik-guard voorbij
    await userEvent.click(akkoordKnop)
    await waitFor(() => expect(aantalCalls(mock, '/administraties/kempen/accordering/documenten/k1/akkoord')).toBe(1))
    expect(screen.getByTestId('acc-versheid')).toHaveTextContent(/^laatst ververst \d\d:\d\d$/)
    expect(leesStand('u-1')?.items.map((i) => i.document_id)).toEqual(['k1'])
  })

  it('een cache-item dat in de verse stand ontbreekt gaat mét melding terug naar de wachtrij — nooit een besluit op een verdwenen document', async () => {
    bewaarStand('u-1', [KEMPEN_1], [])
    const uitgesteld: Uitgesteld = { geef: () => {} }
    stubFetch(routes('u-1', uitgesteld))
    renderFlow()
    await userEvent.click(await screen.findByText('LUSSO Interieurbouw'))
    expect(screen.getAllByRole('button', { name: 'verversen…' })).toHaveLength(2)

    uitgesteld.geef([KEMPEN_2])
    expect(await screen.findByText('Deze factuur is intussen afgehandeld of ingetrokken')).toBeInTheDocument()
    expect(await screen.findByText('Boels Verhuur B.V.')).toBeInTheDocument()
    expect(screen.queryByText('LUSSO Interieurbouw')).not.toBeInTheDocument()
    expect(leesStand('u-1')?.items.map((i) => i.document_id)).toEqual(['k2'])
  })

  it('zonder cache: gewone laadstate, daarna wordt de verse stand bewaard voor de volgende start', async () => {
    const uitgesteld: Uitgesteld = { geef: () => {} }
    stubFetch(routes('u-1', uitgesteld))
    renderFlow()
    expect(await screen.findByText('Wachtrij laden…')).toBeInTheDocument()
    expect(screen.queryByTestId('acc-versheid')).not.toBeInTheDocument()
    uitgesteld.geef([KEMPEN_1])
    expect(await screen.findByText('LUSSO Interieurbouw')).toBeInTheDocument()
    expect(screen.getByTestId('acc-versheid')).toHaveTextContent(/^laatst ververst/)
    expect(leesStand('u-1')?.items).toHaveLength(1)
  })

  it('de cache van een ándere gebruiker wordt nooit getoond', async () => {
    bewaarStand('u-9', [KEMPEN_1], [])
    const uitgesteld: Uitgesteld = { geef: () => {} }
    stubFetch(routes('u-1', uitgesteld))
    renderFlow()
    expect(await screen.findByText('Wachtrij laden…')).toBeInTheDocument()
    expect(screen.queryByText('LUSSO Interieurbouw')).not.toBeInTheDocument()
    uitgesteld.geef([])
    expect(await screen.findByText('Alles is bij')).toBeInTheDocument()
  })

  it('D3: de vragen-fetch start terwijl de wachtrij nog onderweg is (parallel, niet erna)', async () => {
    const uitgesteld: Uitgesteld = { geef: () => {} }
    const mock = stubFetch(routes('u-1', uitgesteld))
    renderFlow()
    await waitFor(() => expect(aantalCalls(mock, '/accordering/wachtrij')).toBe(1))
    await waitFor(() => expect(aantalCalls(mock, '/accordering/vragen')).toBe(1))
    uitgesteld.geef([KEMPEN_1])
    expect(await screen.findByText('LUSSO Interieurbouw')).toBeInTheDocument()
  })

  it('D3: een voorgeladen stand (gestart vóór het monteren) wordt overgenomen — precies één wachtrij-call', async () => {
    const mock = stubFetch(routes('u-1', null, [KEMPEN_1]))
    setAccessToken(nepJwt('u-1'))
    voorlaadStand()
    renderFlow()
    expect(await screen.findByText('LUSSO Interieurbouw')).toBeInTheDocument()
    expect(aantalCalls(mock, '/accordering/wachtrij')).toBe(1)
    expect(aantalCalls(mock, '/accordering/vragen')).toBe(1)
  })
})
