import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IntakeRegels } from './IntakeRegels'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const REGEL_ID = 'bbbbbbbb-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetchMock(opties: { deleteAanroepen?: string[]; deleteStatus?: number }) {
  let verwijderd = false
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/intake/splitsing-uitsluitingen') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            regels: verwijderd
              ? []
              : [
                  {
                    id: REGEL_ID,
                    administratie_id: ADMINISTRATIE_ID,
                    afzender_adres: 'facturen@universal-nederland.nl',
                    leverancier_naam: 'Universal Nederland',
                    reden: null,
                    aangemaakt_op: '2026-09-04T09:00:00Z',
                    aangemaakt_door: 'cccccccc-0000-0000-0000-000000000003',
                    aangemaakt_door_naam: 'Barbara',
                  },
                ],
          }),
        )
      }
      if (init?.method === 'DELETE') {
        opties.deleteAanroepen?.push(url)
        if (opties.deleteStatus && opties.deleteStatus >= 400) {
          return Promise.resolve(jsonResponse({ detail: 'Geen toegang tot deze administratie' }, opties.deleteStatus))
        }
        verwijderd = true
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('IntakeRegels — nooit splitsen per afzender (detailpagina, tab Algemeen)', () => {
  it('toont afzender · leverancier · sinds · door', async () => {
    installFetchMock({})
    render(<IntakeRegels administratieId={ADMINISTRATIE_ID} />)
    expect(await screen.findByText('facturen@universal-nederland.nl')).toBeInTheDocument()
    expect(screen.getByTestId('intake-regels-kop')).toHaveTextContent('Intake-regels')
    expect(screen.getByTestId('intake-regels-lijst')).toHaveTextContent('Universal Nederland')
    expect(screen.getByTestId('intake-regels-lijst')).toHaveTextContent('door Barbara')
  })

  it('verwijderen = bevestigingsdialoog → DELETE op het juiste pad → lege stand met uitleg', async () => {
    const deleteAanroepen: string[] = []
    installFetchMock({ deleteAanroepen })
    const gebruiker = userEvent.setup()
    render(<IntakeRegels administratieId={ADMINISTRATIE_ID} />)
    await gebruiker.click(await screen.findByRole('button', { name: 'Verwijder regel voor facturen@universal-nederland.nl' }))
    expect(screen.getByTestId('bevestig-dialoog')).toHaveTextContent('weer door de splitsings-AI')
    expect(deleteAanroepen).toHaveLength(0) // niets zonder bevestiging
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(deleteAanroepen).toHaveLength(1))
    expect(deleteAanroepen[0]).toContain(`/administraties/${ADMINISTRATIE_ID}/intake/splitsing-uitsluitingen/${REGEL_ID}`)
    expect(await screen.findByText(/geen regels — kies in de verzamelbak/)).toBeInTheDocument()
  })

  it('een geweigerde verwijdering blijft zichtbaar in de dialoog', async () => {
    installFetchMock({ deleteStatus: 403 })
    const gebruiker = userEvent.setup()
    render(<IntakeRegels administratieId={ADMINISTRATIE_ID} />)
    await gebruiker.click(await screen.findByRole('button', { name: /Verwijder regel voor/ }))
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))
    expect(await screen.findByText(/Geen toegang tot deze administratie/)).toBeInTheDocument()
    expect(screen.getByText('facturen@universal-nederland.nl')).toBeInTheDocument() // regel staat er nog
  })
})
