// Blok "Intercompany-relaties" + sectie "Rekening-courant" op Instellingen › Boeken (blok A opdracht 16-09): lijst mét
// status-chips, ⋯ → Uitsluiten vraagt een reden en stuurt PUT {status, reden}, ⋯ → Bevestigen stuurt PUT zonder reden,
// afkortingen-veld → PUT op de identiteit.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IntercompanyRelaties } from './IntercompanyRelaties'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const RELATIES = [
  {
    id: 'r1',
    administratie_a_id: 'a',
    administratie_a_naam: 'Kempen B.V.',
    entity_in_a: 'e1',
    entity_naam: 'Kempen Facilities B.V.',
    administratie_b_id: 'b',
    administratie_b_naam: 'Kempen Facilities B.V.',
    richting: 'crediteur',
    basis: 'kvk',
    status: 'afgeleid',
    bron: 'afgeleid',
    reden: null,
    gewijzigd_op: null,
    actief: true,
  },
  {
    id: 'r2',
    administratie_a_id: 'b',
    administratie_a_naam: 'Kempen Facilities B.V.',
    entity_in_a: 'e2',
    entity_naam: 'Kempen Beheer',
    administratie_b_id: 'c',
    administratie_b_naam: 'Kempen Beheer B.V.',
    richting: 'debiteur',
    basis: 'naam',
    status: 'afgeleid',
    bron: 'afgeleid',
    reden: null,
    gewijzigd_op: null,
    actief: false,
  },
]

const KOPPELINGEN = [
  {
    id: 'k1',
    administratie_a_id: 'a',
    administratie_a_naam: 'Kempen B.V.',
    rekening_a: 'l1',
    rekening_a_code: '1400',
    rekening_a_naam: 'RC Kempen Facilities',
    administratie_b_id: 'b',
    administratie_b_naam: 'Kempen Facilities B.V.',
    rekening_b: null,
    rekening_b_code: null,
    rekening_b_naam: null,
    basis: 'naam',
    status: 'afgeleid',
    bron: 'afgeleid',
    reden: null,
    gewijzigd_op: null,
    actief: true,
  },
]

const IDENTITEITEN = [
  { administratie_id: 'a', administratie_naam: 'Kempen B.V.', naam: 'Kempen B.V.', kvk: '12345678', btw: null, bron: 'rlz', afkortingen: [], gelezen_op: null },
  { administratie_id: 'b', administratie_naam: 'Kempen Facilities B.V.', naam: 'Kempen Facilities B.V.', kvk: '90425405', btw: null, bron: 'rlz', afkortingen: ['KF'], gelezen_op: null },
]

function installFetch(puts: { url: string; body: unknown }[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const methode = init?.method ?? 'GET'
      if (url === '/intercompany/relaties' && methode === 'GET') return Promise.resolve(json({ relaties: RELATIES }))
      if (url === '/intercompany/rc-koppelingen' && methode === 'GET') return Promise.resolve(json({ koppelingen: KOPPELINGEN, identiteiten: IDENTITEITEN }))
      if (methode === 'PUT') {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        puts.push({ url, body })
        if (url.startsWith('/intercompany/relaties/')) {
          const rel = RELATIES.find((r) => url.endsWith(r.id))!
          return Promise.resolve(json({ ...rel, status: body.status, reden: body.reden ?? null, bron: body.status === 'afgeleid' ? 'afgeleid' : 'mens', actief: body.status === 'bevestigd' }))
        }
        if (url.startsWith('/intercompany/rc-koppelingen/')) return Promise.resolve(json({ ...KOPPELINGEN[0], status: body.status, bron: 'mens' }))
        if (url.startsWith('/intercompany/identiteit/')) return Promise.resolve(json({ ...IDENTITEITEN[0], afkortingen: body.afkortingen }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('IntercompanyRelaties (Instellingen › Boeken, blok A 16-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('rendert relaties en RC-koppelingen mét status-chips; naam-only = "vermoedelijk — bevestigen", geen tegenrekening = chip', async () => {
    installFetch([])
    render(<IntercompanyRelaties />)
    const rijen = await screen.findAllByTestId('ic-relatie-rij')
    expect(rijen).toHaveLength(2)
    expect(within(rijen[0]).getByText('afgeleid')).toHaveClass('chip')
    expect(within(rijen[0]).getByText('KvK-nummer')).toBeInTheDocument()
    expect(within(rijen[0]).getByText('crediteur — B levert aan A')).toBeInTheDocument()
    expect(within(rijen[1]).getByText('vermoedelijk — bevestigen')).toHaveClass('afwijking')
    const rc = screen.getByTestId('rc-koppeling-rij')
    expect(within(rc).getByText('1400 RC Kempen Facilities')).toBeInTheDocument()
    expect(within(rc).getByText('zonder tegenrekening')).toHaveClass('chip')
    expect(screen.getByRole('button', { name: 'Nu afleiden' })).toBeInTheDocument()
  })

  it('⋯ → Uitsluiten vraagt een reden en stuurt PUT {status: uitgesloten, reden}; Bevestigen stuurt PUT zonder reden', async () => {
    const puts: { url: string; body: unknown }[] = []
    installFetch(puts)
    const gebruiker = userEvent.setup()
    render(<IntercompanyRelaties />)
    const rijen = await screen.findAllByTestId('ic-relatie-rij')
    await gebruiker.click(within(rijen[0]).getByRole('button', { name: /Meer acties voor/ }))
    await gebruiker.click(screen.getByRole('menuitem', { name: 'Uitsluiten…' }))
    const dialoog = screen.getByTestId('ic-reden-dialoog')
    expect(puts).toHaveLength(0)
    expect(within(dialoog).getByRole('button', { name: 'Uitsluiten' })).toBeDisabled()
    await gebruiker.type(within(dialoog).getByLabelText('Reden'), 'Toch een externe klant')
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Uitsluiten' }))
    await waitFor(() => expect(puts).toEqual([{ url: '/intercompany/relaties/r1', body: { status: 'uitgesloten', reden: 'Toch een externe klant' } }]))
    await waitFor(() => expect(within(screen.getAllByTestId('ic-relatie-rij')[0]).getByText('uitgesloten')).toBeInTheDocument())
    expect(screen.getByText('Toch een externe klant')).toBeInTheDocument()

    await gebruiker.click(within(screen.getAllByTestId('ic-relatie-rij')[1]).getByRole('button', { name: /Meer acties voor/ }))
    await gebruiker.click(screen.getByRole('menuitem', { name: 'Bevestigen' }))
    await waitFor(() => expect(puts[1]).toEqual({ url: '/intercompany/relaties/r2', body: { status: 'bevestigd', reden: null } }))
    await waitFor(() => expect(within(screen.getAllByTestId('ic-relatie-rij')[1]).getByText('bevestigd')).toHaveClass('ok'))
  })

  it('afkortingen per administratie: veld opent onder de knop, Opslaan stuurt PUT met de gesplitste lijst', async () => {
    const puts: { url: string; body: unknown }[] = []
    installFetch(puts)
    const gebruiker = userEvent.setup()
    render(<IntercompanyRelaties />)
    await screen.findAllByTestId('ic-relatie-rij')
    await gebruiker.click(screen.getByRole('button', { name: 'Afkortingen per administratie (1)' }))
    const veld = screen.getByLabelText('Afkortingen voor Kempen B.V.')
    await gebruiker.type(veld, 'KB, kempen')
    await gebruiker.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(puts).toEqual([{ url: '/intercompany/identiteit/a/afkortingen', body: { afkortingen: ['KB', 'kempen'] } }]))
  })
})
