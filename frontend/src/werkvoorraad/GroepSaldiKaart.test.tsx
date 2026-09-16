import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GroepSaldiKaart } from './GroepSaldiKaart'
import { euro } from './groepSaldiApi'

/** Kaart "Groepssaldi" (Peter 16-09): stand van vannacht, drie kolommen (bruto = zonder IC + IC), "N van M administraties in je
 * scope", uitklap per administratie mét rekeningen/status, groep onbekend = leesbare regel. */

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const STAND = {
  groep: { id: 'g-kg', naam: 'Kempen groep', code: 'KEMPENGROEP', actief: true, aantal_administraties: 3 },
  datum: '2026-09-16',
  bron: 'stand',
  aantal_leden: 3,
  aantal_in_scope: 2,
  zonder_stand: 0,
  rijen: [
    {
      administratie_id: 'a1',
      naam: 'Kempen Facilities B.V.',
      status: 'ok',
      detail: null,
      debiteuren: '1150.25',
      debiteuren_ic: '350.10',
      debiteuren_zonder_ic: '800.15',
      crediteuren: '2500.30',
      crediteuren_ic: '1200.00',
      crediteuren_zonder_ic: '1300.30',
      debiteuren_rekening: '1300 Debiteuren',
      crediteuren_rekening: '1600 Crediteuren',
    },
    {
      administratie_id: 'a2',
      naam: 'Kempen B.V.',
      status: 'ongeldig',
      detail: 'RLZ-blokkering — meting ongeldig: 403',
      debiteuren: null,
      debiteuren_ic: null,
      debiteuren_zonder_ic: null,
      crediteuren: null,
      crediteuren_ic: null,
      crediteuren_zonder_ic: null,
      debiteuren_rekening: null,
      crediteuren_rekening: null,
    },
  ],
  totalen: {
    debiteuren: '1150.25',
    debiteuren_ic: '350.10',
    debiteuren_zonder_ic: '800.15',
    crediteuren: '2500.30',
    crediteuren_ic: '1200.00',
    crediteuren_zonder_ic: '1300.30',
    aantal_geldig: 1,
  },
}

afterEach(() => vi.unstubAllGlobals())

describe('GroepSaldiKaart', () => {
  it('toont stand van vannacht, drie kolommen, scope-tekst en de uitklap per administratie', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => Promise.resolve(url === '/groepen/g-kg/saldi' ? json(STAND) : new Response(null, { status: 404 }))))
    const gebruiker = userEvent.setup()
    render(<GroepSaldiKaart groepId="g-kg" />)
    const kaart = await screen.findByTestId('groep-saldi-kaart')
    expect(kaart).toHaveTextContent('Groepssaldi · Kempen groep')
    expect(kaart).toHaveTextContent('stand van vannacht (16-09)')
    expect(kaart).toHaveTextContent('2 van 3 administraties in je scope')
    expect(kaart).toHaveTextContent('1 niet in het totaal')
    const totalen = screen.getByTestId('groep-saldi-totalen')
    expect(totalen).toHaveTextContent('Debiteuren€ 1.150,25€ 350,10€ 800,15')
    expect(totalen).toHaveTextContent('Crediteuren€ 2.500,30€ 1.200,00€ 1.300,30')
    expect(screen.queryByTestId('groep-saldi-per-administratie')).not.toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: /per administratie/ }))
    const detail = screen.getByTestId('groep-saldi-per-administratie')
    expect(detail).toHaveTextContent('1300 Debiteuren · 1600 Crediteuren')
    expect(detail).toHaveTextContent('RLZ-blokkering — meting ongeldig')
    // Geen "verversen"-knop (regel 08-09) en geen debiteur-/crediteurnamen.
    expect(screen.queryByRole('button', { name: /verversen/i })).not.toBeInTheDocument()
  })

  it('groep onbekend = leesbare regel (404-detail), nooit stil leeg; nog geen stand = eigen tekst', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(json({ detail: "groep 'x' niet gevonden — maak hem aan op Instellingen › Administraties (blok Groepen)" }, 404))),
    )
    render(<GroepSaldiKaart groepId="x" />)
    expect(await screen.findByTestId('groep-saldi-kaart')).toHaveTextContent('maak hem aan op Instellingen › Administraties')

    vi.unstubAllGlobals()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({ ...STAND, rijen: [], zonder_stand: 2, totalen: { ...STAND.totalen, aantal_geldig: 0 } }))))
    render(<GroepSaldiKaart groepId="g-kg" />)
    await waitFor(() => expect(screen.getAllByTestId('groep-saldi-kaart').at(-1)).toHaveTextContent('nog geen stand — volgt na de nachtelijke run'))
  })

  it('euro formatteert cent-exact', () => {
    expect(euro('1150.25')).toBe('€ 1.150,25')
    expect(euro('0.00')).toBe('€ 0,00')
    expect(euro(null)).toBe('—')
  })
})
