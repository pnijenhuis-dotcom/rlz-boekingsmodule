import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { VastlyInstellingenDto } from '../reconciliatie/VastlyActies'
import { bronTekst, VastlyOmzetrekeningenRij } from './VastlyOmzetrekeningenRij'

// 29-09: Instellingen › Administratie › Vastgoed-koppeling — de vaste Vastly-omzetrekeningen per regelsoort (zichtbaar + wijzigbaar).

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stand(): VastlyInstellingenDto {
  return {
    administratie_id: ADM,
    omzetrekeningen: [
      { regelsoort: 'huur', ledger_id: 'l-8000', code: '8000', naam: 'Huuropbrengsten', bron: 'historie' },
      { regelsoort: 'servicekosten', ledger_id: null, code: null, naam: null, bron: null },
      { regelsoort: 'waarborg', ledger_id: 'l-8000', code: '8000', naam: 'Huuropbrengsten', bron: 'mens' },
      { regelsoort: 'overig', ledger_id: null, code: null, naam: null, bron: null },
    ],
    keuzelijst: [
      { ledger_id: 'l-8000', code: '8000', naam: 'Huuropbrengsten' },
      { ledger_id: 'l-8100', code: '8100', naam: 'Servicekosten doorbelast' },
    ],
    entiteiten: [{ sleutel_soort: 'kvk', sleutel: '87654321', weergave: 'Rubicon Investments B.V.', bron: 'identiteit' }],
  }
}

afterEach(() => vi.unstubAllGlobals())

describe('VastlyOmzetrekeningenRij (29-09)', () => {
  it('bronTekst', () => {
    expect(bronTekst(stand().omzetrekeningen[0])).toContain('afgeleid')
    expect(bronTekst(stand().omzetrekeningen[2])).toBe('door u gekozen')
    expect(bronTekst(stand().omzetrekeningen[1])).toContain('nog niet afleidbaar')
  })

  it('toont de vier regelsoorten mét bron en de entiteiten; kiezen doet een PUT en toont "door u gekozen"', async () => {
    const puts: Record<string, unknown>[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/vastly-instellingen')) return Promise.resolve(jsonResponse(stand()))
        if (url.endsWith('/vastly-omzetrekeningen') && init?.method === 'PUT') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>
          puts.push(body)
          return Promise.resolve(jsonResponse({ regelsoort: body.regelsoort, ledger_id: body.ledger_id, code: '8100', naam: 'Servicekosten doorbelast', bron: 'mens' }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const gebruiker = userEvent.setup()
    render(<VastlyOmzetrekeningenRij administratieId={ADM} naam="Rubicon Investments B.V." />)
    expect(await screen.findByText('Vastly-omzetrekeningen')).toBeInTheDocument()
    expect(screen.getByTestId('vastly-omzetrekening-huur')).toHaveTextContent('afgeleid')
    expect(screen.getByTestId('vastly-omzetrekening-waarborg')).toHaveTextContent('door u gekozen')
    expect(screen.getByTestId('vastly-omzetrekening-servicekosten')).toHaveTextContent('nog niet afleidbaar')
    expect(screen.getByText(/Rubicon Investments B\.V\. \(kvk 87654321, via identiteit\)/)).toBeInTheDocument()
    const combobox = screen.getByLabelText('Omzetrekening Servicekosten')
    await gebruiker.click(combobox)
    await gebruiker.type(combobox, 'Service')
    await gebruiker.click(await screen.findByRole('option', { name: /Servicekosten doorbelast/ }))
    await waitFor(() => expect(puts).toEqual([{ regelsoort: 'servicekosten', ledger_id: 'l-8100' }]))
    await waitFor(() => expect(screen.getByTestId('vastly-omzetrekening-servicekosten')).toHaveTextContent('door u gekozen'))
  })
})
