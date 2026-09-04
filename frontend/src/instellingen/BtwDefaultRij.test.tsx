import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BtwDefaultRij, optieTekst } from './BtwDefaultRij'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const VERLEGD_ID = 'bbbbbbbb-0000-0000-0000-000000000001'
const HOOG_ID = 'bbbbbbbb-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const OPTIES = [
  { id: VERLEGD_ID, naam: 'NL, BTW verlegd (hoog)', percentage: '0' },
  { id: HOOG_ID, naam: 'NL, Hoog Tarief', percentage: '0.2100' },
]

function installFetchMock(opties: { huidig?: string | null; putAanroepen?: unknown[]; putStatus?: number }) {
  let huidig: string | null = opties.huidig ?? null
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (!url.endsWith('/btw-default')) return Promise.resolve(new Response(null, { status: 404 }))
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { taxrate_id: string | null }
        opties.putAanroepen?.push(body)
        if (opties.putStatus && opties.putStatus >= 400) {
          return Promise.resolve(jsonResponse({ detail: 'Onbekende btw-code voor deze administratie — kies een tarief uit de gesyncte lijst.' }, opties.putStatus))
        }
        huidig = body.taxrate_id
      }
      const naam = OPTIES.find((o) => o.id === huidig)?.naam ?? null
      return Promise.resolve(jsonResponse({ taxrate_id: huidig, taxrate_naam: naam, opties: OPTIES }))
    }),
  )
}

describe('BtwDefaultRij — standaard btw-voorstel per administratie (blok E 04-09, Beheerder)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont de rij mét uitlegzin en de gesyncte tarieven; default uit', async () => {
    installFetchMock({})
    render(<BtwDefaultRij administratieId={ADMINISTRATIE_ID} naam="Universal Steigerbouw" />)
    const select = await screen.findByLabelText('Standaard btw-voorstel voor Universal Steigerbouw')
    await waitFor(() => expect(select).not.toBeDisabled())
    expect(select).toHaveValue('')
    expect(screen.getByText('Standaard btw-voorstel')).toBeInTheDocument()
    expect(screen.getByText(/vult alleen regels waar factuur en leverancier-geheugen niets opleveren/i)).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '0% · NL, BTW verlegd (hoog)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '21% · NL, Hoog Tarief' })).toBeInTheDocument()
  })

  it('kiezen doet een PUT met het tarief; leeg kiezen zet de default uit (null)', async () => {
    const putAanroepen: unknown[] = []
    installFetchMock({ putAanroepen })
    const gebruiker = userEvent.setup()
    render(<BtwDefaultRij administratieId={ADMINISTRATIE_ID} naam="Universal Steigerbouw" />)
    const select = await screen.findByLabelText('Standaard btw-voorstel voor Universal Steigerbouw')
    await waitFor(() => expect(select).not.toBeDisabled())

    await gebruiker.selectOptions(select, VERLEGD_ID)
    await waitFor(() => expect(putAanroepen).toEqual([{ taxrate_id: VERLEGD_ID }]))
    await waitFor(() => expect(select).toHaveValue(VERLEGD_ID))
    expect(await screen.findByText('opgeslagen')).toBeInTheDocument()

    await gebruiker.selectOptions(select, '')
    await waitFor(() => expect(putAanroepen).toEqual([{ taxrate_id: VERLEGD_ID }, { taxrate_id: null }]))
    await waitFor(() => expect(select).toHaveValue(''))
  })

  it('een geweigerde PUT (422) toont de reden en laat de oude stand staan', async () => {
    installFetchMock({ putStatus: 422 })
    const gebruiker = userEvent.setup()
    render(<BtwDefaultRij administratieId={ADMINISTRATIE_ID} naam="Universal Steigerbouw" />)
    const select = await screen.findByLabelText('Standaard btw-voorstel voor Universal Steigerbouw')
    await waitFor(() => expect(select).not.toBeDisabled())
    await gebruiker.selectOptions(select, HOOG_ID)
    expect(await screen.findByRole('alert')).toHaveTextContent(/gesyncte lijst/)
    expect(select).toHaveValue('')
  })

  it('optietekst volgt de btw-combobox van het controlescherm', () => {
    expect(optieTekst({ id: 'x', naam: 'NL, Hoog Tarief', percentage: '0.21' })).toBe('21% · NL, Hoog Tarief')
    expect(optieTekst({ id: 'x', naam: 'Onbekend', percentage: null })).toBe('Onbekend')
  })
})
