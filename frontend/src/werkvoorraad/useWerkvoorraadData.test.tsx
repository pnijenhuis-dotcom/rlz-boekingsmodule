/** Blok 6 run 11-09 — beginscherm traag bij 71 administraties: (1) de klantenlijst doet géén call per administratie
 * meer (`/doorbelasting/{id}/spiegel-taken` × N is weg; `spiegel_taken` komt server-side mee), (2) de lijst staat er
 * zodra het overzicht binnen is en de Bank-kolom toont een skeleton tot `/bank/overzicht` er is — geen leeg wit. */
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdministratieDto } from '../api/types'
import { Klantenlijst } from './Klantenlijst'
import { useWerkvoorraadData } from './useWerkvoorraadData'

const A = 'aaaaaaaa-0000-0000-0000-000000000001'
const B = 'aaaaaaaa-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function klantDto(id: string, naam: string, spiegel = 0) {
  return {
    administratie_id: id,
    naam,
    te_controleren: 1,
    klaar_om_te_boeken: 0,
    vragen: 0,
    afgewezen: 0,
    bij_klant: 0,
    iban_wachtend: 0,
    spiegel_taken: spiegel,
  }
}

function Harnas({ administraties }: { administraties: AdministratieDto[] }) {
  const { klanten, fout, herlaad } = useWerkvoorraadData(administraties)
  return <Klantenlijst klanten={klanten} fout={fout} onHerlaad={herlaad} totaalAdministraties={administraties.length} />
}

describe('useWerkvoorraadData (blok 6)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('doet geen spiegel-taken-call per administratie en toont de lijst vóór het bank-overzicht binnen is', async () => {
    let bankKlaar: (r: Response) => void = () => undefined
    const bank = new Promise<Response>((resolve) => {
      bankKlaar = resolve
    })
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/werkvoorraad/overzicht')) {
        return Promise.resolve(jsonResponse({ klanten: [klantDto(A, 'Alfa B.V.', 2), klantDto(B, 'Beta B.V.')] }))
      }
      if (url.endsWith('/bank/overzicht')) return bank
      if (url.endsWith('/vragen/stand')) return Promise.resolve(jsonResponse({ open: 0 }))
      return Promise.resolve(jsonResponse({ detail: `onverwacht: ${url}` }, 404))
    })
    vi.stubGlobal('fetch', fetchMock)
    const administraties = [
      { id: A, naam: 'Alfa B.V.' },
      { id: B, naam: 'Beta B.V.' },
    ] as AdministratieDto[]

    render(
      <MemoryRouter>
        <Harnas administraties={administraties} />
      </MemoryRouter>,
    )

    // Lijst staat er terwijl /bank/overzicht nog open is: rijen + skeleton in de Bank-kolom.
    await screen.findByText('Alfa B.V.')
    expect(screen.getByText('Beta B.V.')).toBeTruthy()
    const skeletons = screen.getAllByLabelText('Laden')
    expect(skeletons.length).toBe(2)
    // Spiegel-taken uit het overzicht zelf: kolom zichtbaar met de server-side teller, zonder extra calls.
    expect(screen.getByText('Spiegel-taken')).toBeTruthy()
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('spiegel-taken'))).toBe(false)

    bankKlaar(jsonResponse({ klanten: [{ administratie_id: A, open_mutaties: 4 }] }))
    await waitFor(() => expect(screen.queryAllByLabelText('Laden')).toHaveLength(0))
    expect(screen.getByText('4')).toBeTruthy()
    // Precies drie calls: overzicht, bank, vragen-stand — onafhankelijk van het aantal administraties.
    expect(fetchMock.mock.calls.length).toBe(3)
  })
})
