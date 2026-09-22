// 22-09 (Peter, casus Bouwadvies F/2026/01235): een factuur die intussen buiten de module al in Reeleezee staat
// verdwijnt uit "te accorderen", staat zichtbaar onder "Wachten op kantoor" mét de banner, en heeft in de review geen
// Akkoord/Afwijzen — het kantoor beoordeelt. Nooit stil weg.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { GoedkeurenFlow } from './GoedkeurenFlow'
import type { WachtrijItemDto } from './accordeurApi'
import { besluitVerzender } from './besluitQueue'
import { factuurCache } from './pdfCache'

const BANNER = 'Al geboekt in Reeleezee (RLZ-04-00000518) — kantoor beoordeelt; akkoord niet nodig'
const GEWOON: WachtrijItemDto = {
  document_id: 'd1',
  administratie_id: 'a1',
  administratie_naam: 'Bouwadvies Oost Nederland B.V.',
  leverancier_naam: 'Segers Installatie',
  referentie: '33122',
  factuurdatum: '2026-09-15',
  totaalbedrag: '80000.00',
  aangeboden_op: '2026-09-15T09:00:00Z',
  laag_volgnummer: 1,
  boeking_omschrijving: 'Installatiewerk · btw verlegd',
  staande_regel_kandidaat: false,
}
const EXTERN: WachtrijItemDto = {
  ...GEWOON,
  document_id: 'd2',
  leverancier_naam: 'Beter Assemblage B.V.',
  referentie: 'F/2026/01235',
  totaalbedrag: '173.84',
  aangeboden_op: '2026-09-16T09:13:00Z',
  laag_volgnummer: 3,
  extern_geboekt: { boekstuk: 'RLZ-04-00000518', systeem: 'Reeleezee', stand: 'geboekt', tekst: BANNER },
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stubFetch(items: WachtrijItemDto[]) {
  const routes: Record<string, () => Response> = {
    '/auth/token/vernieuwen': () => new Response(null, { status: 401 }),
    '/accordering/wachtrij': () => jsonResponse({ items }),
    '/auth/administraties': () => jsonResponse({ administraties: [{ id: 'a1', naam: 'Bouwadvies Oost Nederland B.V.' }] }),
    '/administraties/a1/documenten/d1/bestand': () => new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 }),
    '/administraties/a1/documenten/d2/bestand': () => new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 }),
    '/accordering/vragen': () => jsonResponse({ items: [] }),
  }
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL) => {
      const pad = String(invoer).split('?')[0]
      const handler = routes[pad]
      return Promise.resolve(handler ? handler() : new Response(null, { status: 404 }))
    }),
  )
}

function renderFlow() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <GoedkeurenFlow wisselThema={() => {}} uitloggen={() => Promise.resolve()} />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('GoedkeurenFlow — intussen buiten de module geboekt (22-09)', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} }))
    besluitVerzender.resetVoorTests()
    factuurCache.resetVoorTests()
  })
  afterEach(() => vi.unstubAllGlobals())

  it('telt de factuur niet als te accorderen, toont haar onder "Wachten op kantoor" mét banner, en de review heeft geen Akkoord/Afwijzen', async () => {
    stubFetch([GEWOON, EXTERN])
    renderFlow()
    // Teller telt alleen echt werk (1, niet 2).
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
    expect(screen.getByTestId('acc-wacht-op-kantoor')).toHaveTextContent('Wachten op kantoor · 1')
    expect(screen.getByTestId('acc-extern-geboekt-banner')).toHaveTextContent(BANNER)
    expect(screen.getByText('Beter Assemblage B.V.')).toBeInTheDocument()
    // Review van het wacht-op-kantoor-item: banner bovenaan, geen actiebalk.
    await userEvent.click(screen.getByText('Beter Assemblage B.V.'))
    expect(await screen.findByRole('status')).toHaveTextContent(BANNER)
    expect(screen.queryByRole('button', { name: 'Akkoord ✓' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Afwijzen' })).toBeNull()
  })

  it('een administratie met alléén een wacht-op-kantoor-factuur is niet "alles bij" — de sectie staat er, zonder knoppen', async () => {
    stubFetch([EXTERN])
    renderFlow()
    expect(await screen.findByTestId('acc-wacht-op-kantoor')).toHaveTextContent('Wachten op kantoor · 1')
    expect(screen.queryByText('Alles is bij')).toBeNull()
    expect(screen.getByText(/geen facturen te accorderen/)).toBeInTheDocument()
  })

  it('zonder extern_geboekt verandert er niets aan de gewone kaart', async () => {
    stubFetch([GEWOON])
    renderFlow()
    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
    expect(screen.queryByTestId('acc-wacht-op-kantoor')).toBeNull()
    await userEvent.click(screen.getByText('Segers Installatie'))
    expect(await screen.findByRole('button', { name: 'Akkoord ✓' })).toBeInTheDocument()
  })
})
