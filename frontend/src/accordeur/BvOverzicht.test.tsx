// BV-openingsscherm + verversen (besluiten Peter 27-08, mockup accordeur-vragen.html scherm 0):
// twee administraties met werk → keuzescherm; één → direct de wachtrij; alles bij → "✓ Alles is
// bij" mét verversknop; na akkoord de volgende factuur van dezelfde BV, stapel leeg → overzicht;
// pull-to-refresh en voorgrond-terugkeer halen een zojuist klaargezette factuur op; deep-link
// landt in de juiste BV-wachtrij.

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { GoedkeurenFlow } from './GoedkeurenFlow'
import { PULL_DREMPEL_PX } from './PullToRefresh'
import type { WachtrijItemDto } from './accordeurApi'
import { besluitVerzender } from './besluitQueue'
import { factuurCache } from './pdfCache'

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
const KEMPEN_2: WachtrijItemDto = { ...KEMPEN_1, document_id: 'k2', leverancier_naam: 'Boels Verhuur B.V.', totaalbedrag: '486.10', aangeboden_op: '2026-08-26T09:00:00Z' }
const UNIVERSAL_1: WachtrijItemDto = {
  ...KEMPEN_1,
  document_id: 'u1',
  administratie_id: 'universal',
  administratie_naam: 'Universal Steigerbouw B.V.',
  leverancier_naam: 'Van Diemen Transport',
  totaalbedrag: '2310.00',
  aangeboden_op: '2026-08-27T07:00:00Z',
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

/** Wachtrij-stub met een muteerbare lijst — zo simuleren we "zojuist klaargezet". */
function routesMetLijst(lijst: { items: WachtrijItemDto[] }, vragen: unknown[] = []): FetchAntwoorden {
  const pdf = () => new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 })
  return {
    '/auth/token/vernieuwen': () => new Response(null, { status: 401 }),
    '/accordering/wachtrij': () => jsonResponse({ items: lijst.items }),
    '/accordering/vragen': () => jsonResponse({ items: vragen }),
    '/auth/administraties': () => jsonResponse({ administraties: [] }),
    '/administraties/kempen/documenten/k1/bestand': pdf,
    '/administraties/kempen/documenten/k2/bestand': pdf,
    '/administraties/universal/documenten/u1/bestand': pdf,
    '/administraties/kempen/accordering/documenten/k1/akkoord': besluitOk,
    '/administraties/kempen/accordering/documenten/k2/akkoord': besluitOk,
    '/administraties/universal/accordering/documenten/u1/akkoord': besluitOk,
  }
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

const aantalWachtrijCalls = (mock: ReturnType<typeof vi.fn>) =>
  mock.mock.calls.filter((c) => String(c[0]).split('?')[0] === '/accordering/wachtrij').length

describe('BV-openingsscherm (27-08)', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} }))
    besluitVerzender.resetVoorTests()
    factuurCache.resetVoorTests()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('twee administraties met werk → keuzescherm met tellers, vraag-chip en oudste-wacht-regel; klik = gefilterde wachtrij mét terugknop', async () => {
    const vraag = {
      id: 'v1',
      administratie_id: 'kempen',
      administratie_naam: 'Kempen Facilities B.V.',
      document_id: 'oud-doc',
      document_status: 'geboekt',
      leverancier_naam: 'Van Diemen Transport',
      totaalbedrag: '780.45',
      vraag_tekst: 'Klopt het werkadres?',
      gesteld_op: '2026-08-25T11:20:00Z',
      ik_ben_aan_de_beurt: true,
      berichten: [],
    }
    stubFetch(routesMetLijst({ items: [KEMPEN_1, KEMPEN_2, UNIVERSAL_1] }, [vraag]))
    renderFlow()

    expect(await screen.findByText('Uw administraties')).toBeInTheDocument()
    const kempen = screen.getByRole('button', { name: 'Administratie Kempen Facilities B.V.' })
    expect(kempen).toHaveTextContent('2 te accorderen')
    expect(kempen).toHaveTextContent('💬 1 vraag aan u')
    expect(kempen).toHaveTextContent(/Oudste wacht/)
    expect(screen.getByRole('button', { name: 'Administratie Universal Steigerbouw B.V.' })).toHaveTextContent('1 te accorderen')
    // Op het overzicht geen facturen of losse vragen-sectie — die horen bij een BV.
    expect(screen.queryByText('LUSSO Interieurbouw')).not.toBeInTheDocument()
    expect(screen.queryByText(/Vragen aan u ·/)).not.toBeInTheDocument()

    await userEvent.click(kempen)
    expect(await screen.findByText('Kempen Facilities B.V. — te accorderen · 2')).toBeInTheDocument()
    expect(screen.getByText('LUSSO Interieurbouw')).toBeInTheDocument()
    expect(screen.queryByText('Van Diemen Transport · laag')).not.toBeInTheDocument()
    expect(screen.queryByText('€ 2.310,00')).not.toBeInTheDocument()
    // "Vragen aan u" van déze BV wél zichtbaar
    expect(screen.getByText('Vragen aan u · 1')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '‹ Administraties' }))
    expect(await screen.findByText('Uw administraties')).toBeInTheDocument()
  })

  it('precies één administratie met werk → keuzescherm overslaan, direct de wachtrij zonder terugknop', async () => {
    stubFetch(routesMetLijst({ items: [UNIVERSAL_1] }))
    renderFlow()
    expect(await screen.findByText('Universal Steigerbouw B.V. — te accorderen · 1')).toBeInTheDocument()
    expect(screen.queryByText('Uw administraties')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '‹ Administraties' })).not.toBeInTheDocument()
  })

  it('ná akkoord volgt de volgende factuur van DEZELFDE BV; stapel leeg → terug naar het overzicht met de resterende BV', async () => {
    stubFetch(routesMetLijst({ items: [KEMPEN_1, KEMPEN_2, UNIVERSAL_1] }))
    renderFlow()
    await userEvent.click(await screen.findByRole('button', { name: 'Administratie Kempen Facilities B.V.' }))
    await userEvent.click(await screen.findByText('LUSSO Interieurbouw'))
    expect(await screen.findByText('1 van 2')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Akkoord ✓' }))
    // Volgende = Boels (Kempen), níét Van Diemen (Universal)
    expect(await screen.findByText('2 van 2')).toBeInTheDocument()
    expect(screen.getByText(/€ 486,10/)).toBeInTheDocument()
    expect(screen.queryByText(/€ 2\.310,00/)).not.toBeInTheDocument()

    // Guard-venster (300 ms) voorbij laten gaan vóór de tweede akkoord-klik
    await new Promise((r) => setTimeout(r, 350))
    await userEvent.click(screen.getByRole('button', { name: 'Akkoord ✓' }))
    // Kempen-stapel leeg → nog precies één BV met werk → direct díe wachtrij (regel "één = overslaan")
    expect(await screen.findByText('Universal Steigerbouw B.V. — te accorderen · 1')).toBeInTheDocument()
  })

  it('alles bij → "✓ Alles is bij" mét verversknop die een zojuist klaargezette factuur ophaalt', async () => {
    const lijst = { items: [] as WachtrijItemDto[] }
    const mock = stubFetch(routesMetLijst(lijst))
    renderFlow()
    expect(await screen.findByText('Alles is bij')).toBeInTheDocument()

    lijst.items = [KEMPEN_1]
    await userEvent.click(screen.getByRole('button', { name: '↻ Verversen' }))
    expect(await screen.findByText('LUSSO Interieurbouw')).toBeInTheDocument()
    expect(aantalWachtrijCalls(mock)).toBe(2)
  })

  it('pull-to-refresh op de wachtrij: trek voorbij de drempel en laat los → verse wachtrij (stil, lijst blijft staan)', async () => {
    const lijst = { items: [KEMPEN_1] }
    const mock = stubFetch(routesMetLijst(lijst))
    renderFlow()
    await screen.findByText('LUSSO Interieurbouw')

    lijst.items = [KEMPEN_1, KEMPEN_2]
    const zone = screen.getByTestId('pull-to-refresh').parentElement!
    fireEvent.touchStart(zone, { touches: [{ clientY: 100 }] })
    fireEvent.touchMove(zone, { touches: [{ clientY: 100 + (PULL_DREMPEL_PX + 20) / 0.55 }] })
    expect(screen.getByTestId('pull-to-refresh')).toHaveTextContent('Laat los om te verversen')
    fireEvent.touchEnd(zone)

    expect(await screen.findByText('Boels Verhuur B.V.')).toBeInTheDocument()
    // De bestaande kaart bleef staan (geen "Wachtrij laden…"-flits)
    expect(screen.getByText('LUSSO Interieurbouw')).toBeInTheDocument()
    expect(aantalWachtrijCalls(mock)).toBe(2)
  })

  it('een te korte trek ververst niet', async () => {
    const mock = stubFetch(routesMetLijst({ items: [KEMPEN_1] }))
    renderFlow()
    await screen.findByText('LUSSO Interieurbouw')
    const zone = screen.getByTestId('pull-to-refresh').parentElement!
    fireEvent.touchStart(zone, { touches: [{ clientY: 100 }] })
    fireEvent.touchMove(zone, { touches: [{ clientY: 130 }] })
    fireEvent.touchEnd(zone)
    await new Promise((r) => setTimeout(r, 50))
    expect(aantalWachtrijCalls(mock)).toBe(1)
  })

  it('terug naar de voorgrond (visibilitychange → visible) ververst automatisch', async () => {
    const lijst = { items: [KEMPEN_1] }
    const mock = stubFetch(routesMetLijst(lijst))
    renderFlow()
    await screen.findByText('LUSSO Interieurbouw')

    lijst.items = [KEMPEN_1, UNIVERSAL_1]
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    // Twee BV's met werk → het overzicht verschijnt vanzelf
    expect(await screen.findByText('Uw administraties')).toBeInTheDocument()
    await waitFor(() => expect(aantalWachtrijCalls(mock)).toBe(2))
  })

  it('deep-link ?document= landt direct in de review van de juiste BV; terug = díe BV-wachtrij', async () => {
    stubFetch(routesMetLijst({ items: [KEMPEN_1, UNIVERSAL_1] }))
    renderFlow('/accordeur?document=u1')
    expect(await screen.findByText(/€ 2\.310,00/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Akkoord ✓' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '‹ Wachtrij' }))
    expect(await screen.findByText('Universal Steigerbouw B.V. — te accorderen · 1')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '‹ Administraties' })).toBeInTheDocument()
  })
})
