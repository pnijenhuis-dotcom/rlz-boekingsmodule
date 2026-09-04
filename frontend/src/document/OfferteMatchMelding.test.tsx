import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OfferteMatchMelding } from './OfferteMatchMelding'
import type { VerplichtingMatchDto } from '../verplichting/verplichtingApi'

// Factuur ↔ offerte-match op het controlescherm (blok B 04-09, mockup offerte-matching blok 2):
// groen "binnen de goedgekeurde offerte" mét verbruiksbalk, oranje "buiten de offerte" / "geen
// goedgekeurde offerte" mét het meerwerk-handelingsperspectief en "Koppel offerte…".
// Nooit een blokkade — en `geen_verplichting`/`niet_toetsbaar` renderen helemaal niets.

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOC = 'bbbbbbbb-0000-0000-0000-000000000002'
const VERPLICHTING = 'cccccccc-0000-0000-0000-000000000003'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function match(overrides: Partial<VerplichtingMatchDto> = {}): VerplichtingMatchDto {
  return {
    document_id: DOC,
    uitkomst: 'binnen',
    verplichting: {
      document_id: VERPLICHTING,
      offertenummer: '26140-OFF-01',
      soort_label: 'offerte',
      leverancier_naam: 'Confide Bouw B.V.',
      project_naam: 'Koningstraat',
      totaal_excl: '48500.00',
      goedgekeurd_op: '2026-09-04T10:00:00Z',
      goedgekeurd_door_naam: 'J. de Groot',
    },
    bedrag_excl: '12400.00',
    verbruik_voor: '14750.00',
    verbruik_na: '27150.00',
    percentage_na: 56,
    overschrijding_excl: null,
    handmatig_gekoppeld: false,
    kandidaten: [],
    berekend_op: '2026-09-04T11:00:00Z',
    melding: 'Gematcht op leverancier + project; offertenummer stond op de factuur.',
    ...overrides,
  }
}

function installFetch(body: VerplichtingMatchDto, koppelAanroepen?: { url: string; body: unknown }[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/verplichting-match/koppel') && init?.method === 'POST') {
        koppelAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(
          json(match({ uitkomst: 'binnen', handmatig_gekoppeld: true, melding: 'Handmatig gekoppeld.' })),
        )
      }
      if (url.endsWith('/verplichting-match')) return Promise.resolve(json(body))
      return Promise.resolve(json({ detail: `onverwacht pad ${url}` }, 500))
    }),
  )
}

function toon(soort = 'inkoopfactuur', status = 'te_controleren') {
  return render(
    <MemoryRouter>
      <OfferteMatchMelding administratieId={ADMIN} documentId={DOC} status={status} soort={soort} />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('OfferteMatchMelding', () => {
  it('binnen de offerte: groene chip, verbruiksbalk en geen meerwerk-waarschuwing', async () => {
    installFetch(match())
    toon()

    expect(await screen.findByTestId('offerte-chip-binnen')).toHaveTextContent('binnen offerte')
    expect(screen.getByText(/Binnen de goedgekeurde offerte/i)).toBeInTheDocument()
    expect(screen.getByText(/J. de Groot/)).toBeInTheDocument()
    const balk = screen.getByTestId('offerte-balk')
    expect(balk).toHaveTextContent('56%')
    expect(balk).toHaveTextContent('€ 27.150,00 / € 48.500,00')
    expect(screen.queryByTestId('meerwerk-perspectief')).not.toBeInTheDocument()
    // Open-link naar de verplichting zelf.
    expect(screen.getByRole('link', { name: /Open de verplichting/ })).toHaveAttribute(
      'href',
      `/verplichting/${ADMIN}/${VERPLICHTING}`,
    )
  })

  it('buiten de offerte: oranje chip, het bedrag erover en het meerwerk-handelingsperspectief', async () => {
    installFetch(
      match({
        uitkomst: 'buiten',
        bedrag_excl: '15000.00',
        verbruik_na: '51900.00',
        percentage_na: 107,
        overschrijding_excl: '3400.00',
        melding: 'Cumulatief boven het goedgekeurde bedrag.',
      }),
    )
    toon()

    expect(await screen.findByTestId('offerte-chip-buiten')).toHaveTextContent('buiten offerte')
    expect(screen.getByText(/Buiten de offerte/i)).toBeInTheDocument()
    expect(screen.getByTestId('offerte-balk')).toHaveTextContent('− € 3.400,00 over')
    expect(screen.getByTestId('meerwerk-perspectief')).toHaveTextContent(
      /Meerwerk rekt een offerte niet op — laat aanvullend werk als aparte verplichting accorderen/i,
    )
    // Nooit een blokkade — dat staat er expliciet bij.
    expect(screen.getByTestId('meerwerk-perspectief')).toHaveTextContent(/signaal, geen blokkade/i)
  })

  it('geen goedgekeurde offerte gevonden: oranje melding mét de reden en "Koppel offerte…"', async () => {
    installFetch(
      match({
        uitkomst: 'geen_match',
        verplichting: null,
        verbruik_voor: null,
        verbruik_na: null,
        percentage_na: null,
        melding: 'Wel een lopende offerte van deze leverancier, maar niet voor dit project.',
      }),
    )
    toon()

    expect(await screen.findByTestId('offerte-chip-buiten')).toBeInTheDocument()
    expect(screen.getByText(/Geen goedgekeurde offerte gevonden/i)).toBeInTheDocument()
    expect(screen.queryByTestId('offerte-balk')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Koppel offerte…' })).toBeInTheDocument()
  })

  it('rendert niets bij geen_verplichting (stil) en niets op een ander documentsoort', async () => {
    installFetch(match({ uitkomst: 'geen_verplichting', verplichting: null, melding: '' }))
    const { container } = toon()
    await waitFor(() => expect(container.querySelector('[data-testid="offerte-match-melding"]')).toBeNull())

    vi.unstubAllGlobals()
    const opgeroepen = vi.fn(() => Promise.resolve(json({})))
    vi.stubGlobal('fetch', opgeroepen)
    const { container: tweede } = toon('kassarapport')
    expect(tweede.querySelector('[data-testid="offerte-match-melding"]')).toBeNull()
    expect(opgeroepen).not.toHaveBeenCalled()
  })

  it('koppel-dialoog: kandidaten kiezen POST naar de koppel-route; ontkoppelen stuurt null', async () => {
    const koppelAanroepen: { url: string; body: unknown }[] = []
    installFetch(
      match({
        uitkomst: 'meerdere_kandidaten',
        verplichting: null,
        melding: 'Twee lopende offertes voor dit project.',
        kandidaten: [
          {
            document_id: VERPLICHTING,
            offertenummer: '26140-OFF-01',
            soort_label: 'offerte',
            totaal_excl: '48500.00',
            verbruikt_excl: '14750.00',
            project_naam: 'Koningstraat',
            geldig_tot: '2026-12-31',
          },
          {
            document_id: 'dddd0000-0000-0000-0000-000000000004',
            offertenummer: '26140-OFF-09',
            soort_label: 'prijsopgave',
            totaal_excl: '9500.00',
            verbruikt_excl: '0.00',
            project_naam: 'Koningstraat',
            geldig_tot: null,
          },
        ],
      }),
      koppelAanroepen,
    )
    toon()

    expect(await screen.findByText(/Meerdere goedgekeurde offertes mogelijk/i)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Koppel offerte…' }))

    const dialoog = await screen.findByTestId('koppel-offerte-dialoog')
    expect(within(dialoog).getAllByRole('radio')).toHaveLength(2)
    await userEvent.click(within(dialoog).getByLabelText('Kies 26140-OFF-09'))
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Koppelen' }))

    await waitFor(() => expect(koppelAanroepen).toHaveLength(1))
    expect(koppelAanroepen[0].url).toContain(`/administraties/${ADMIN}/documenten/${DOC}/verplichting-match/koppel`)
    expect(koppelAanroepen[0].body).toEqual({ verplichting_document_id: 'dddd0000-0000-0000-0000-000000000004' })
    // Na het koppelen toont de melding de nieuwe, handmatig gekoppelde stand.
    expect(await screen.findByText('handmatig gekoppeld')).toBeInTheDocument()

    // Ontkoppelen is nu beschikbaar en stuurt expliciet null.
    await userEvent.click(screen.getByRole('button', { name: 'Koppel offerte…' }))
    const tweede = await screen.findByTestId('koppel-offerte-dialoog')
    await userEvent.click(within(tweede).getByRole('button', { name: 'Ontkoppelen' }))
    await waitFor(() => expect(koppelAanroepen).toHaveLength(2))
    expect(koppelAanroepen[1].body).toEqual({ verplichting_document_id: null })
  })
})
