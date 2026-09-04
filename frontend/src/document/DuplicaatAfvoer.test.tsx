/** Duplicaat-afvoer (besluit Peter 04-09): rijmenu-regel "Afvoeren als duplicaat" alleen bij een harde-
 * match-signaal én afvoerbare status; de bevestigingsdialoog toont het origineel als voorstel-regel en POST
 * zonder vrije reden; de controlescherm-sectie toont kandidaat-knop, afgevoerd-kant en origineel-kant. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DocumentListItemDto, DuplicaatAfvoerStandDto, DuplicaatOrigineelDto } from '../api/types'
import { DuplicaatAfvoerDialog, DuplicaatAfvoerSectie, toonAfvoerenAlsDuplicaat } from './DuplicaatAfvoer'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const ORIGINEEL_ID = 'cccccccc-0000-0000-0000-000000000003'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function origineel(overrides: Partial<DuplicaatOrigineelDto> = {}): DuplicaatOrigineelDto {
  return {
    bron: 'werkvoorraad',
    referentie: 'F-2026-0042',
    document_id: ORIGINEEL_ID,
    rlz_document_id: null,
    boekstuknummer: null,
    bestandsnaam: 'origineel.pdf',
    aangemaakt_op: '2026-09-01T09:00:00Z',
    status: 'te_controleren',
    ...overrides,
  }
}

function rij(overrides: Partial<DocumentListItemDto> = {}): DocumentListItemDto {
  return {
    id: DOCUMENT_ID,
    bestandsnaam: 'kopie.pdf',
    status: 'te_controleren',
    bron: 'upload',
    soort: 'inkoopfactuur',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-09-02T09:00:00Z',
    laatst_gewijzigd_op: '2026-09-02T09:00:00Z',
    afwijzing: null,
    leverancier: 'Bouwmaat',
    totaalbedrag: '121.00',
    factuurdatum: '2026-08-20',
    automatisch_geboekt: false,
    ...overrides,
  }
}

describe('toonAfvoerenAlsDuplicaat (rijmenu-regel)', () => {
  it('toont het item bij een werkvoorraad-origineel of een gecachete RLZ-treffer, alleen in afvoerbare statussen', () => {
    expect(toonAfvoerenAlsDuplicaat(rij())).toBe(false)
    expect(toonAfvoerenAlsDuplicaat(rij({ duplicaat_werkvoorraad_van: origineel() }))).toBe(true)
    expect(
      toonAfvoerenAlsDuplicaat(rij({ duplicaatsignaal: { uitkomst: 'mogelijk_duplicaat', aantal_treffers: 1, berekend_op: '2026-09-02T09:00:00Z' } })),
    ).toBe(true)
    expect(toonAfvoerenAlsDuplicaat(rij({ duplicaatsignaal: { uitkomst: 'geen', aantal_treffers: 0, berekend_op: '2026-09-02T09:00:00Z' } }))).toBe(false)
    // Zacht/andere signalen tellen niet: het sha256-bestandsduplicaat is geen harde kop-match.
    expect(toonAfvoerenAlsDuplicaat(rij({ mogelijk_duplicaat_van: { document_id: ORIGINEEL_ID, bestandsnaam: 'x.pdf', aangemaakt_op: '2026-09-01T09:00:00Z' } }))).toBe(false)
    for (const status of ['ter_accordering', 'geboekt', 'vraag_open', 'afgewezen']) {
      expect(toonAfvoerenAlsDuplicaat(rij({ status, duplicaat_werkvoorraad_van: origineel() }))).toBe(false)
    }
    expect(toonAfvoerenAlsDuplicaat(rij({ soort: 'kassarapport', duplicaat_werkvoorraad_van: origineel() }))).toBe(false)
  })
})

describe('DuplicaatAfvoerDialog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont het origineel als voorstel-regel en POST zonder vrije reden; resultaat naar onAfgevoerd', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: { url: string; body: string | null }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/afvoeren-als-duplicaat') && init?.method === 'POST') {
          aanroepen.push({ url, body: init.body ? String(init.body) : null })
          return Promise.resolve(
            jsonResponse({
              afwijzing_id: 'f1',
              document_id: DOCUMENT_ID,
              document_status: 'afgewezen',
              reden: 'Duplicaat van F-2026-0042 (document origineel.pdf van 2026-09-01 in de werkvoorraad)',
              automatisch: false,
              al_afgevoerd: false,
              origineel: origineel(),
            }),
          )
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const onAfgevoerd = vi.fn()
    render(
      <MemoryRouter>
        <DuplicaatAfvoerDialog
          administratieId={ADMINISTRATIE_ID}
          documentId={DOCUMENT_ID}
          bestandsnaam="kopie.pdf"
          kandidaat={origineel()}
          onAfgevoerd={onAfgevoerd}
          onAnnuleren={() => {}}
        />
      </MemoryRouter>,
    )
    const regel = screen.getByTestId('duplicaat-origineel')
    expect(regel).toHaveTextContent('F-2026-0042')
    expect(regel).toHaveTextContent('origineel.pdf')
    expect(regel).toHaveTextContent('in de werkvoorraad')
    expect(screen.getByRole('link', { name: 'open origineel' })).toHaveAttribute('href', `/documenten/${ADMINISTRATIE_ID}/${ORIGINEEL_ID}`)
    // Geen redenveld: de reden is deterministisch.
    expect(screen.queryByRole('textbox')).toBeNull()

    await gebruiker.click(screen.getByRole('button', { name: 'Afvoeren als duplicaat' }))
    await waitFor(() => expect(onAfgevoerd).toHaveBeenCalledTimes(1))
    expect(aanroepen).toHaveLength(1)
    expect(aanroepen[0].url).toContain(`/administraties/${ADMINISTRATIE_ID}/documenten/${DOCUMENT_ID}/afvoeren-als-duplicaat`)
    expect(onAfgevoerd.mock.calls[0][0].reden).toMatch(/^Duplicaat van F-2026-0042/)
  })

  it('haalt zonder meegegeven kandidaat de stand zelf op en toont een 409 leesbaar', async () => {
    const gebruiker = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/afvoeren-als-duplicaat') && init?.method === 'POST') {
          return Promise.resolve(jsonResponse({ detail: 'Geen harde duplicaat-match (meer): crediteur, referentie en totaalbedrag komen niet alle drie overeen' }, 409))
        }
        if (url.endsWith(`/documenten/${DOCUMENT_ID}`)) {
          return Promise.resolve(
            jsonResponse({
              id: DOCUMENT_ID,
              status: 'te_controleren',
              tijdlijn: [],
              duplicaat_afvoer: { kandidaat: origineel({ bron: 'geboekt', document_id: null, bestandsnaam: null, aangemaakt_op: null, boekstuknummer: 'INK-77' }), afgevoerd_als_duplicaat_van: null, afgevoerde_duplicaten: [] },
            }),
          )
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    render(
      <MemoryRouter>
        <DuplicaatAfvoerDialog administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} bestandsnaam="kopie.pdf" onAfgevoerd={() => {}} onAnnuleren={() => {}} />
      </MemoryRouter>,
    )
    const regel = await screen.findByTestId('duplicaat-origineel')
    expect(regel).toHaveTextContent('boekstuk INK-77')
    expect(regel).toHaveTextContent('al geboekt')
    expect(screen.queryByRole('link', { name: 'open origineel' })).toBeNull() // RLZ-origineel zonder app-document
    await gebruiker.click(screen.getByRole('button', { name: 'Afvoeren als duplicaat' }))
    expect(await screen.findByText(/Geen harde duplicaat-match/)).toBeInTheDocument()
  })
})

describe('DuplicaatAfvoerSectie (controlescherm)', () => {
  const naamVoor = (id: string) => (id === 'u1' ? 'J. Willems' : id)

  function renderSectie(status: string, stand: DuplicaatAfvoerStandDto) {
    return render(
      <MemoryRouter>
        <DuplicaatAfvoerSectie
          administratieId={ADMINISTRATIE_ID}
          documentId={DOCUMENT_ID}
          bestandsnaam="kopie.pdf"
          status={status}
          stand={stand}
          naamVoor={naamVoor}
          onGewijzigd={() => {}}
        />
      </MemoryRouter>,
    )
  }

  it('kandidaat → paneel mét één secundaire knop; niets zonder kandidaat', () => {
    renderSectie('te_controleren', { kandidaat: origineel(), afgevoerd_als_duplicaat_van: null, afgevoerde_duplicaten: [] })
    expect(screen.getByTestId('duplicaat-kandidaat')).toBeInTheDocument()
    const knop = screen.getByRole('button', { name: 'Afvoeren als duplicaat…' })
    expect(knop.className).toContain('btn secondary')
  })

  it('afgevoerd-kant toont "Afgevoerd als duplicaat" mét link naar het origineel', () => {
    renderSectie('afgewezen', { kandidaat: null, afgevoerd_als_duplicaat_van: origineel(), afgevoerde_duplicaten: [] })
    expect(screen.getByTestId('duplicaat-afgevoerd')).toHaveTextContent('Afgevoerd als duplicaat')
    expect(screen.getByRole('link', { name: 'open origineel' })).toHaveAttribute('href', `/documenten/${ADMINISTRATIE_ID}/${ORIGINEEL_ID}`)
    expect(screen.queryByRole('button', { name: 'Afvoeren als duplicaat…' })).toBeNull()
  })

  it('origineel-kant telt de afgevoerde duplicaten en benoemt ⚙ systeem vs medewerker', () => {
    renderSectie('te_controleren', {
      kandidaat: null,
      afgevoerd_als_duplicaat_van: null,
      afgevoerde_duplicaten: [
        { afwijzing_id: 'f1', document_id: 'd1', bestandsnaam: 'kopie-1.pdf', aangemaakt_op: '2026-09-02T09:00:00Z', referentie: 'F-2026-0042', automatisch: true, afgewezen_op: '2026-09-02T09:05:00Z', afgewezen_door: 'sys' },
        { afwijzing_id: 'f2', document_id: 'd2', bestandsnaam: 'kopie-2.pdf', aangemaakt_op: '2026-09-03T09:00:00Z', referentie: 'F-2026-0042', automatisch: false, afgewezen_op: '2026-09-03T09:05:00Z', afgewezen_door: 'u1' },
      ],
    })
    const lijst = screen.getByTestId('duplicaat-afgevoerde-lijst')
    expect(lijst).toHaveTextContent('2 duplicaten afgevoerd')
    expect(lijst).toHaveTextContent('⚙ systeem')
    expect(lijst).toHaveTextContent('J. Willems')
    expect(screen.getByRole('link', { name: 'kopie-1.pdf' })).toHaveAttribute('href', `/documenten/${ADMINISTRATIE_ID}/d1`)
  })

  it('rendert niets als er niets te melden is', () => {
    const { container } = renderSectie('te_controleren', { kandidaat: null, afgevoerd_als_duplicaat_van: null, afgevoerde_duplicaten: [] })
    expect(container).toBeEmptyDOMElement()
  })
})
