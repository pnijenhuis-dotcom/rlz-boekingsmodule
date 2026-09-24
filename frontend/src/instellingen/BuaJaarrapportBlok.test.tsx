import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BuaJaarrapportBlok, type BuaJaarrapportDto } from './BuaJaarrapportBlok'

/** BUA-jaarrapport (Peter 24-09 "standaard 21 % btw aanhouden"): lees-only blok — rekeningen mét afgetrokken btw, categorie,
 * voorstel-chip, kantine/sponsoring apart, LET-OP-tekst letterlijk, jaar-keuze = nieuwe GET. */
const AID = 'aaaaaaaa-0000-0000-0000-000000000001'
const LET_OP =
  'LET OP: de € 227-drempel per begunstigde per jaar is niet uit de boekhouding te halen — voorstel = volledige btw-som; de accountant toetst de drempel, de module past niets toe'

function rekening(over: Partial<BuaJaarrapportDto['rekeningen'][number]>): BuaJaarrapportDto['rekeningen'][number] {
  return {
    ledger_id: 'gb', code: '4510', naam: 'Representatiekosten', categorie: 'BUA', kenmerk: false,
    mod_n: 0, mod_netto: '0.00', mod_btw: '0.00', bank_n: 0, bank_netto: '0.00', bank_btw: '0.00',
    rlz_n: null, rlz_netto: null, rlz_btw: null, btw_totaal: '0.00', documenten: 0,
    ...over,
  }
}

function stand(jaar: number): BuaJaarrapportDto {
  return {
    jaar,
    administratie_id: AID,
    administratie: 'BLOW B.V.',
    rlz_kant: 'niet gemeten',
    bua_btw: jaar === 2026 ? '31.50' : '0.00',
    correctie_voorstel: jaar === 2026 ? '31.50' : '0.00',
    kantine_btw: '9.00',
    sponsoring_btw: '0.00',
    rekeningen:
      jaar === 2026
        ? [
            rekening({ ledger_id: 'gb-4510', code: '4510', naam: 'Representatiekosten', mod_n: 2, mod_netto: '100.00', mod_btw: '21.00', btw_totaal: '21.00', documenten: 2 }),
            rekening({ ledger_id: 'gb-4508', code: '4508', naam: 'Relatiegeschenken', kenmerk: true, bank_n: 1, bank_netto: '50.00', bank_btw: '10.50', btw_totaal: '10.50', documenten: 1 }),
            rekening({ ledger_id: 'gb-4014', code: '4014', naam: 'Kantinekosten', categorie: 'kantine', mod_n: 1, mod_netto: '100.00', mod_btw: '9.00', btw_totaal: '9.00', documenten: 1 }),
            rekening({ ledger_id: 'gb-4503', code: '4503', naam: 'Kosten promotie/sponsoring', categorie: 'sponsoring — reclame' }),
          ]
        : [rekening({ ledger_id: 'gb-4510' })],
    let_op: LET_OP,
  }
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

describe('BuaJaarrapportBlok', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont per rekening mét afgetrokken btw code/categorie/btw, het voorstel als chip, kantine apart en de LET-OP-tekst letterlijk', async () => {
    const fetchMock = vi.fn((url: string) => {
      const jaar = Number(new URL(url, 'http://x').searchParams.get('jaar'))
      return Promise.resolve(json(stand(jaar)))
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-12-05T10:00:00Z'))
    render(<BuaJaarrapportBlok administratieId={AID} naam="BLOW B.V." />)
    await waitFor(() => expect(screen.getByTestId('bua-jaarrapport-voorstel')).toHaveTextContent('correctie laatste aangifte (voorstel): € 31,50'))
    expect(String(fetchMock.mock.calls[0][0])).toContain(`/administraties/${AID}/bua-jaarrapport?jaar=2026`)
    expect(screen.getByText('4510')).toBeInTheDocument()
    expect(screen.getByText('Relatiegeschenken')).toBeInTheDocument()
    expect(screen.getByText(/kenmerk “btw niet aftrekbaar” staat aan/)).toBeInTheDocument()
    expect(screen.getAllByText('BUA')).toHaveLength(2)
    expect(screen.getByText('kantine')).toBeInTheDocument()
    expect(screen.queryByText('4503')).toBeNull() // 0,00 btw = niet getoond
    expect(screen.getByTestId('bua-jaarrapport-sommen')).toHaveTextContent('BUA-btw € 31,50 · kantine € 9,00 (apart) · sponsoring € 0,00 (apart)')
    expect(screen.getByRole('note')).toHaveTextContent(LET_OP)
    vi.useRealTimers()
  })

  it('jaar wisselen doet een nieuwe GET en toont de lege stand als er niets is afgetrokken; fout = zichtbare melding', async () => {
    const gebruiker = userEvent.setup()
    const fetchMock = vi.fn((url: string) => {
      const jaar = Number(new URL(url, 'http://x').searchParams.get('jaar'))
      return Promise.resolve(json(stand(jaar)))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<BuaJaarrapportBlok administratieId={AID} naam="BLOW B.V." />)
    await waitFor(() => expect(screen.getByTestId('bua-jaarrapport-voorstel')).toBeInTheDocument())
    const huidig = new Date().getFullYear()
    await gebruiker.selectOptions(screen.getByRole('combobox', { name: /Boekjaar BUA-jaarrapport/ }), String(huidig - 2))
    await waitFor(() => expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain(`jaar=${huidig - 2}`))
    await waitFor(() => expect(screen.getByText(/geen btw afgetrokken/)).toBeInTheDocument())
    vi.unstubAllGlobals()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify({ detail: 'Onbekende administratie' }), { status: 404 }))))
    render(<BuaJaarrapportBlok administratieId="onbekend" naam="X" />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})
