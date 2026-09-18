import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BtwAftrekUitgeslotenBlok } from './BtwAftrekUitgeslotenBlok'

/** BUA-blok (Peter 18-09, migratie 0163): voorstel als vinkjes, Beheerder bevestigt — nooit stil aangezet; PUT = exacte set. */
const AID = 'aaaaaaaa-0000-0000-0000-000000000001'
const stand = (uitgesloten: string[]) => ({
  rekeningen: [
    { ledger_id: 'gb-4510', code: '4510', naam: 'Representatiekosten (beperkt aftrekbaar)', uitgesloten: uitgesloten.includes('gb-4510'), voorstel: true, standaard_percentage: null, standaard_naam: null, gezet_op: null },
    { ledger_id: 'gb-4508', code: '4508', naam: 'Relatiegeschenken (beperkt aftrekbaar)', uitgesloten: uitgesloten.includes('gb-4508'), voorstel: true, standaard_percentage: null, standaard_naam: null, gezet_op: null },
    { ledger_id: 'gb-4404', code: '4404', naam: 'Kosten mobiele telefonie', uitgesloten: false, voorstel: false, standaard_percentage: '0.21', standaard_naam: 'NL, Hoog Tarief', gezet_op: null },
  ],
  aantal_uitgesloten: uitgesloten.length,
  aantal_voorstel: 2 - uitgesloten.length,
})

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('BtwAftrekUitgeslotenBlok', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont het voorstel als vinkjes (uit) mét chip "voorstel" en zet niets automatisch aan', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json(stand([])))))
    render(<BtwAftrekUitgeslotenBlok administratieId={AID} naam="BLOW B.V." />)
    await waitFor(() => expect(screen.getByTestId('btw-aftrek-teller')).toHaveTextContent('0 niet aftrekbaar'))
    expect(screen.getAllByText('voorstel')).toHaveLength(2)
    expect(screen.getByRole('checkbox', { name: /4510/ })).not.toBeChecked()
    expect(screen.queryByText('4404')).toBeNull() // niet-voorstel, niet aangevinkt = verborgen tot "Alle kostenrekeningen"
    expect(screen.getByRole('button', { name: 'Opslaan' })).toBeDisabled()
  })

  it('"Voorstel overnemen (2)" vinkt aan; Opslaan stuurt de exacte set (PUT) en toont de nieuwe stand', async () => {
    const gebruiker = userEvent.setup()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') return Promise.resolve(json(stand(['gb-4510', 'gb-4508'])))
      return Promise.resolve(json(stand([])))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<BtwAftrekUitgeslotenBlok administratieId={AID} naam="BLOW B.V." />)
    await gebruiker.click(await screen.findByRole('button', { name: 'Voorstel overnemen (2)' }))
    expect(screen.getByTestId('btw-aftrek-teller')).toHaveTextContent('2 niet aftrekbaar')
    await gebruiker.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(screen.getByText('opgeslagen')).toBeInTheDocument())
    const put = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'PUT')
    expect(put?.[0]).toBe(`/administraties/${AID}/btw-aftrek-uitgesloten`)
    expect(JSON.parse(String((put?.[1] as RequestInit).body))).toEqual({ ledger_ids: expect.arrayContaining(['gb-4510', 'gb-4508']) })
  })

  it('"Alle kostenrekeningen" toont ook de niet-voorstel-rekeningen mét hun standaard', async () => {
    const gebruiker = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json(stand([])))))
    render(<BtwAftrekUitgeslotenBlok administratieId={AID} naam="BLOW B.V." />)
    await gebruiker.click(await screen.findByRole('button', { name: /Alle kostenrekeningen \(3\)/ }))
    expect(screen.getByText('4404')).toBeInTheDocument()
    expect(screen.getByText(/standaard: NL, Hoog Tarief/)).toBeInTheDocument()
  })
})
