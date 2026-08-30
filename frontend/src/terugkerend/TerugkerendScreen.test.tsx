import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { TerugkerendSignaal } from '../document/TerugkerendSignaal'
import { TerugkerendScreen } from './TerugkerendScreen'
import type { TerugkerendOverzichtDto } from './terugkerendApi'

// Terugkerende facturen (blok B 30-08): overzicht per administratie, snooze/afmelden per leverancier,
// drempel (Beheerder), prijsstijging-chip op het controlescherm. De client formatteert alleen.

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function fakeAccessToken(rol: string): string {
  const payload = btoa(JSON.stringify({ sub: 'gebruiker-id', rol })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'
const OVERZICHT: TerugkerendOverzichtDto = {
  administratie_id: ADMIN,
  prijsstijging_drempel_pct: '10.00',
  signalen: [
    {
      id: 's1',
      vendor_id: 'v-ziggo',
      leverancier: 'Ziggo Zakelijk',
      patroon: 'maand',
      interval_dagen: 30,
      aantal_facturen: 4,
      laatste_datum: '2026-04-02',
      laatste_bedrag: '120.00',
      laatste_document_id: 'doc-1',
      vorige_datum: '2026-03-02',
      vorige_bedrag: '100.00',
      verwacht_op: '2026-05-02',
      uiterlijk_op: '2026-05-13',
      ontbreekt_sinds: '2026-05-13',
      dagen_te_laat: 109,
      prijsstijging_pct: '20.00',
      snooze_tot: null,
      afgemeld_op: null,
      status: 'ontbreekt',
      berekend_op: '2026-08-30T05:00:00Z',
    },
    {
      id: 's2',
      vendor_id: 'v-eneco',
      leverancier: 'Eneco',
      patroon: 'kwartaal',
      interval_dagen: 91,
      aantal_facturen: 3,
      laatste_datum: '2026-07-01',
      laatste_bedrag: '300.00',
      laatste_document_id: null,
      vorige_datum: null,
      vorige_bedrag: null,
      verwacht_op: '2026-09-30',
      uiterlijk_op: '2026-11-01',
      ontbreekt_sinds: null,
      dagen_te_laat: null,
      prijsstijging_pct: null,
      snooze_tot: null,
      afgemeld_op: null,
      status: 'op_schema',
      berekend_op: '2026-08-30T05:00:00Z',
    },
  ],
}

function stubFetch(rol = 'boekhouding') {
  const aangeroepen: { pad: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      aangeroepen.push({ pad: url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken(rol) }))
      if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADMIN, naam: 'Kempen Facilities B.V.' }] }))
      if (url === `/administraties/${ADMIN}/terugkerend`) return Promise.resolve(jsonResponse(OVERZICHT))
      if (url.endsWith('/snooze') || url.endsWith('/afmelden')) return Promise.resolve(new Response(null, { status: 204 }))
      if (url.endsWith('/terugkerend-instelling')) return Promise.resolve(jsonResponse({ prijsstijging_pct: '5' }))
      if (url.endsWith('/terugkerend-signaal')) {
        return Promise.resolve(jsonResponse({ prijsstijging_pct: '20.00', vorige_bedrag: '100.00', vorige_datum: '2026-03-02', laatste_bedrag: '120.00', patroon: 'maand', leverancier: 'Ziggo Zakelijk' }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

describe('TerugkerendScreen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont per leverancier ritme, laatste factuur, verwachting, signaal en prijsstijging; snooze en afmelden POSTen per leverancier', async () => {
    const aangeroepen = stubFetch()
    render(
      <MemoryRouter initialEntries={[`/terugkerend?administratie=${ADMIN}`]}>
        <AuthProvider>
          <TerugkerendScreen />
        </AuthProvider>
      </MemoryRouter>,
    )
    const tabel = await screen.findByTestId('terugkerend-tabel')
    expect(within(tabel).getByText('Ziggo Zakelijk')).toBeInTheDocument()
    expect(within(tabel).getByText('maandelijks (≈ 30 d)')).toBeInTheDocument()
    expect(within(tabel).getByText(/verwachte factuur ontbreekt · 109 d te laat/)).toBeInTheDocument()
    expect(within(tabel).getByText('▲ +20%')).toBeInTheDocument()
    // Op schema zonder prijsstijging staat achter "op schema tonen".
    expect(within(tabel).queryByText('Eneco')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: '1 op schema tonen' }))
    expect(within(tabel).getByText('Eneco')).toBeInTheDocument()
    expect(within(tabel).getByText(/✓ op schema/)).toBeInTheDocument()
    // Niet-Beheerder: geen drempel-invoer.
    expect(screen.queryByLabelText('Drempel prijsstijging')).toBeNull()
    await userEvent.click(within(tabel).getByRole('button', { name: 'Snooze Ziggo Zakelijk' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === `/administraties/${ADMIN}/terugkerend/v-ziggo/snooze`)).toBe(true))
    const snooze = aangeroepen.find((a) => a.pad.endsWith('/v-ziggo/snooze'))!
    expect(snooze.method).toBe('POST')
    expect((snooze.body as { tot: string }).tot).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    await userEvent.click(within(tabel).getByRole('button', { name: 'Afmelden Ziggo Zakelijk' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad.endsWith('/v-ziggo/afmelden'))).toBe(true))
    expect(aangeroepen.find((a) => a.pad.endsWith('/v-ziggo/afmelden'))?.body).toEqual({ afgemeld: true })
  })

  it('Beheerder kan de drempel zetten (PUT terugkerend-instelling)', async () => {
    const aangeroepen = stubFetch('beheerder')
    render(
      <MemoryRouter initialEntries={[`/terugkerend?administratie=${ADMIN}`]}>
        <AuthProvider>
          <TerugkerendScreen />
        </AuthProvider>
      </MemoryRouter>,
    )
    const invoer = await screen.findByLabelText('Drempel prijsstijging')
    expect(invoer).toHaveValue('10.00')
    await userEvent.clear(invoer)
    await userEvent.type(invoer, '5')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad.endsWith('/terugkerend-instelling') && a.method === 'PUT')).toBe(true))
    expect(aangeroepen.find((a) => a.pad.endsWith('/terugkerend-instelling'))?.body).toEqual({ prijsstijging_pct: '5' })
  })
})

describe('TerugkerendSignaal (controlescherm-chip)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de prijsstijging-chip mét vorige factuur en link naar het overzicht; niet-inkoop = niets', async () => {
    stubFetch()
    const { rerender } = render(
      <MemoryRouter>
        <TerugkerendSignaal administratieId={ADMIN} documentId="doc-1" status="te_controleren" soort="inkoopfactuur" boekvoorstelVersie={0} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('Prijsstijging +20%')).toBeInTheDocument()
    expect(screen.getByText(/t\.o\.v\./)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Alle terugkerende facturen/ })).toHaveAttribute('href', `/terugkerend?administratie=${ADMIN}`)
    rerender(
      <MemoryRouter>
        <TerugkerendSignaal administratieId={ADMIN} documentId="doc-1" status="te_controleren" soort="verkoopfactuur" boekvoorstelVersie={0} />
      </MemoryRouter>,
    )
    expect(screen.queryByText(/Prijsstijging/)).toBeNull()
  })
})
