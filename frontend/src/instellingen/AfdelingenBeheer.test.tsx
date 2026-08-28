import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AfdelingenBeheer } from './AfdelingenBeheer'

// Mockup afdelingen.html §1 (blok A 28-08): tabel Afdeling / Accorderingsroute / Staande
// goedkeuringen, terugval "Algemeen" volgt de administratie-route, route wijzigen per afdeling,
// archiveren (nooit verwijderen) en "+ Afdeling toevoegen".

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const LIJST = {
  ingeschakeld: true,
  afdelingen: [
    { id: 'alg', naam: 'Algemeen', is_terugval: true, actief: true, route: [], staande_goedkeuringen: 0, gearchiveerd_op: null },
    {
      id: 'buiten',
      naam: 'Buitendienst',
      is_terugval: false,
      actief: true,
      route: [
        { volgnummer: 1, accordeur_gebruiker_id: 'u1', accordeur_naam: 'R. de Groot', bedrag_drempel: null },
        { volgnummer: 2, accordeur_gebruiker_id: 'u2', accordeur_naam: 'P. Kempen', bedrag_drempel: '5000.00' },
      ],
      staande_goedkeuringen: 2,
      gearchiveerd_op: null,
    },
    { id: 'rec', naam: 'Receptie', is_terugval: false, actief: true, route: [], staande_goedkeuringen: 0, gearchiveerd_op: null },
  ],
}

function stubFetch() {
  const aangeroepen: { pad: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      aangeroepen.push({ pad: url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
      if (url === '/administraties/a1/afdelingen' && method === 'GET') return Promise.resolve(jsonResponse(LIJST))
      if (url === '/administraties/a1/afdelingen' && method === 'POST') {
        return Promise.resolve(
          jsonResponse({ id: 'nieuw', naam: 'Magazijn', is_terugval: false, actief: true, route: [], staande_goedkeuringen: 0, gearchiveerd_op: null }, 201),
        )
      }
      if (url === '/administraties/a1/accordering/kandidaten') {
        return Promise.resolve(jsonResponse({ kandidaten: [{ id: 'u1', naam: 'R. de Groot' }, { id: 'u2', naam: 'P. Kempen' }] }))
      }
      if (url.endsWith('/accordering/route') && method === 'PUT') {
        return Promise.resolve(jsonResponse({ afdeling_id: 'rec', lagen: [], rondes_vervallen: 1 }))
      }
      if (url.endsWith('/archiveren')) return Promise.resolve(new Response(null, { status: 204 }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

describe('AfdelingenBeheer', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de tabel conform de mockup: terugval, routesamenvatting, staande goedkeuringen, ontbrekende route', async () => {
    stubFetch()
    render(<AfdelingenBeheer administratieId="a1" naam="Kempen Facilities B.V." />)
    expect(await screen.findByText('Buitendienst')).toBeInTheDocument()
    expect(screen.getByText('terugval')).toBeInTheDocument()
    expect(screen.getByText('Route van de administratie (bestaande config)')).toBeInTheDocument()
    expect(screen.getByText('Laag 1 · R. de Groot → Laag 2 · P. Kempen > € 5.000')).toBeInTheDocument()
    expect(screen.getByText('2 actief')).toBeInTheDocument()
    expect(screen.getByText(/nog geen route/)).toBeInTheDocument()
    // De terugval heeft geen archiveer-/route-knop.
    const rijen = screen.getAllByRole('row')
    const algemeen = rijen.find((r) => within(r).queryByText('Algemeen'))!
    expect(within(algemeen).queryByRole('button', { name: 'Archiveren' })).toBeNull()
  })

  it('+ Afdeling toevoegen → POST en lijst opnieuw', async () => {
    const aangeroepen = stubFetch()
    render(<AfdelingenBeheer administratieId="a1" naam="Kempen" />)
    await screen.findByText('Buitendienst')
    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getByRole('button', { name: '+ Afdeling toevoegen' }))
    await gebruiker.type(screen.getByLabelText('Naam nieuwe afdeling (Kempen)'), 'Magazijn')
    await gebruiker.click(screen.getByRole('button', { name: 'Toevoegen' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.method === 'POST' && a.pad === '/administraties/a1/afdelingen')).toBe(true))
    expect(aangeroepen.find((a) => a.method === 'POST' && a.pad === '/administraties/a1/afdelingen')?.body).toEqual({ naam: 'Magazijn' })
    expect(await screen.findByText(/Afdeling "Magazijn" toegevoegd/)).toBeInTheDocument()
  })

  it('Route wijzigen → editor met lagen, opslaan = PUT en de vervallen-melding', async () => {
    const aangeroepen = stubFetch()
    render(<AfdelingenBeheer administratieId="a1" naam="Kempen" />)
    await screen.findByText('Receptie')
    const gebruiker = userEvent.setup()
    const receptieRij = screen.getAllByRole('row').find((r) => within(r).queryByText('Receptie'))!
    await gebruiker.click(within(receptieRij).getByRole('button', { name: 'Route wijzigen' }))
    const editor = await screen.findByTestId('afdeling-route-editor')
    await gebruiker.selectOptions(within(editor).getByLabelText('Accordeur laag 1 (Receptie)'), 'u2')
    await gebruiker.click(within(editor).getByRole('button', { name: 'Route opslaan' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.method === 'PUT' && a.pad.endsWith('/afdelingen/rec/accordering/route'))).toBe(true))
    const put = aangeroepen.find((a) => a.method === 'PUT')!
    expect(put.body).toEqual({ lagen: [{ volgnummer: 1, accordeur_gebruiker_id: 'u2', bedrag_drempel: null }] })
    expect(await screen.findByText(/1 lopende accordering is vervallen/)).toBeInTheDocument()
  })

  it('Archiveren vraagt bevestiging en POST daarna naar /archiveren', async () => {
    const aangeroepen = stubFetch()
    render(<AfdelingenBeheer administratieId="a1" naam="Kempen" />)
    await screen.findByText('Receptie')
    const gebruiker = userEvent.setup()
    const receptieRij = screen.getAllByRole('row').find((r) => within(r).queryByText('Receptie'))!
    await gebruiker.click(within(receptieRij).getByRole('button', { name: 'Archiveren' }))
    expect(await screen.findByText('Afdeling "Receptie" archiveren?')).toBeInTheDocument()
    expect(aangeroepen.some((a) => a.pad.endsWith('/archiveren'))).toBe(false)
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(aangeroepen.some((a) => a.pad === '/administraties/a1/afdelingen/rec/archiveren')).toBe(true))
  })
})
