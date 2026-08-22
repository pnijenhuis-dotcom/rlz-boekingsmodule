/** Tegenboek-sectie (mockup tegenboek-mockup.html, akkoord Peter 22-08): de knop
 * "Tegenboeken…" verschijnt alléén bij een geblokkeerde storno; de flow is één scherm
 * (keuze, voorbeeld met negatieve regels, betaalstatus-waarschuwing alleen indien betaald,
 * verplichte reden, boeken); een bestaande tegenboeking toont de chip TEGENGEBOEKT. */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { TegenboekToetsDto } from '../api/types'
import { TegenboekSectie } from './TegenboekSectie'

const ADMINISTRATIE_ID = 'dddddddd-0000-0000-0000-00000000000d'
const DOCUMENT_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function toets(overrides: Partial<TegenboekToetsDto> = {}): TegenboekToetsDto {
  return {
    document_id: DOCUMENT_ID,
    storno_geblokkeerd: true,
    blokkade_melding: 'BTW-aangifte over deze periode is definitief ingediend — wijzigingen handmatig verwerken (tegenboeking)',
    tegenboeking: null,
    betaalstatus: { betaald_bedrag: '0', open_bedrag: '121.00', volledig_afgeletterd: false },
    voorbeeld: [
      {
        grootboek_code: '4302',
        grootboek_naam: 'Onderhoud',
        omschrijving: 'TEGENBOEKING 2026-0841 · Bouwmaat Eindhoven',
        netto_bedrag: '-5000.00',
        btw_bedrag: '-1050.00',
      },
    ],
    referentie: '2026-0841',
    tegenboek_referentie: 'TB 2026-0841',
    leverancier_naam: 'Bouwmaat Eindhoven',
    totaal_netto: '-5000.00',
    totaal_btw: '-1050.00',
    ...overrides,
  }
}

function installMock(toetsBody: TegenboekToetsDto, post?: () => Response) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/tegenboek-toets')) return Promise.resolve(jsonResponse(toetsBody))
    if (url.includes('/tegenboeken') && init?.method === 'POST')
      return Promise.resolve(
        (post ?? (() => jsonResponse({ document_id: DOCUMENT_ID, soort: 'volledig', status: 'geboekt', rlz_tegenboeking_id: DOCUMENT_ID, rlz_boekstuknummer: 'RLZ-04-9' })))(),
      )
    return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderSectie(props: Partial<Parameters<typeof TegenboekSectie>[0]> = {}) {
  return render(
    <MemoryRouter>
      <TegenboekSectie
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="geboekt"
        soort="inkoopfactuur"
        onGewijzigd={() => undefined}
        {...props}
      />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('TegenboekSectie', () => {
  it('toont de geblokkeerde storno + Tegenboeken-knop en de flow met voorbeeld en verplichte reden', async () => {
    installMock(toets())
    renderSectie()
    await waitFor(() => expect(screen.getByText(/Storno niet mogelijk/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Storneren (geblokkeerd)' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Tegenboeken…' }))
    // Eén scherm: keuze, voorbeeld (negatieve bedragen), reden verplicht.
    expect(screen.getByText('Volledig tegenboeken')).toBeInTheDocument()
    expect(screen.getByText('Tegenboeken én opnieuw boeken')).toBeInTheDocument()
    expect(screen.getByText('TEGENBOEKING 2026-0841 · Bouwmaat Eindhoven')).toBeInTheDocument()
    expect(screen.getAllByText(/€\s*-5\.000,00/).length).toBeGreaterThan(0)
    // Geen betaling → géén open-creditpost-waarschuwing.
    expect(screen.queryByText(/open creditpost/)).not.toBeInTheDocument()
    const boekKnop = screen.getByRole('button', { name: 'Tegenboeking boeken' })
    expect(boekKnop).toBeDisabled() // reden verplicht
    fireEvent.change(screen.getByLabelText(/Reden/), { target: { value: 'dubbel geboekt in april' } })
    expect(boekKnop).toBeEnabled()
  })

  it('boekt de tegenboeking en meldt de kruisverwijzing', async () => {
    const fetchMock = installMock(toets())
    const onGewijzigd = vi.fn()
    renderSectie({ onGewijzigd })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Tegenboeken…' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Tegenboeken…' }))
    fireEvent.change(screen.getByLabelText(/Reden/), { target: { value: 'dubbel geboekt in april' } })
    fireEvent.click(screen.getByRole('button', { name: 'Tegenboeking boeken' }))
    await waitFor(() => expect(onGewijzigd).toHaveBeenCalled())
    const postCall = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'POST')
    expect(JSON.parse(String((postCall![1] as RequestInit).body))).toEqual({
      soort: 'volledig',
      reden: 'dubbel geboekt in april',
    })
    expect(screen.getByText(/origineel gemarkeerd TEGENGEBOEKT/)).toBeInTheDocument()
  })

  it('waarschuwt voor de open creditpost bij een deels betaald origineel', async () => {
    installMock(toets({ betaalstatus: { betaald_bedrag: '3000.00', open_bedrag: '3050.00', volledig_afgeletterd: false } }))
    renderSectie()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Tegenboeken…' })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Tegenboeken…' }))
    expect(screen.getByText(/deels betaald/)).toBeInTheDocument()
    expect(screen.getByText(/open creditpost/)).toBeInTheDocument()
  })

  it('toont de chip TEGENGEBOEKT met kruisverwijzing bij een bestaande tegenboeking', async () => {
    installMock(
      toets({
        tegenboeking: {
          soort: 'volledig',
          reden: 'dubbel geboekt',
          boek_cyclus: 0,
          rlz_tegenboeking_id: 'eeeeeeee-0000-0000-0000-00000000000e',
          rlz_boekstuknummer: 'RLZ-04-0004201',
          origineel_betaald_bedrag: null,
          aangemaakt_op: '2026-08-22T10:00:00Z',
        },
      }),
    )
    renderSectie()
    await waitFor(() => expect(screen.getByText('TEGENGEBOEKT')).toBeInTheDocument())
    expect(screen.getByText('RLZ-04-0004201')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tegenboeken…' })).not.toBeInTheDocument()
  })

  it('toont niets als storno niet geblokkeerd is (bestaand gedrag blijft)', async () => {
    installMock(toets({ storno_geblokkeerd: false, blokkade_melding: null }))
    const { container } = renderSectie()
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    await waitFor(() => expect(container.querySelector('.panel')).toBeNull())
  })
})
