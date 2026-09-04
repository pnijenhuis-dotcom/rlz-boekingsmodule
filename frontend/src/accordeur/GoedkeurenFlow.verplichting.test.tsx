// Accordeur-app: verplichtingen + offerte-match (blok B 04-09, mockup offerte-matching blok 1/2).
// Kaart voor soort 'verplichting' (neutrale soort-chip, werk/project/geldigheid, bedrag excl.) en
// review-kop "Verplichting:" i.p.v. "Boeking:"; bij een inkoopfactuur mét offerte_match de
// groene/oranje melding mét balk én het VOORINGEVULDE vinkje "Conform offerte ‹nr›" — besluit
// Peter 04-09 optie A: het vinkje is presentatie, de mens tikt zélf Akkoord.

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { GoedkeurenFlow } from './GoedkeurenFlow'
import { besluitVerzender } from './besluitQueue'
import { factuurCache } from './pdfCache'
import type { WachtrijItemDto } from './accordeurApi'

const FACTUUR: WachtrijItemDto = {
  document_id: 'd1',
  administratie_id: 'a1',
  administratie_naam: 'Kempen Facilities B.V.',
  leverancier_naam: 'Confide Bouw B.V.',
  referentie: 'F-2026-118',
  factuurdatum: '2026-09-02',
  totaalbedrag: '15004.00',
  aangeboden_op: '2026-09-03T09:00:00Z',
  laag_volgnummer: 1,
  boeking_omschrijving: 'Verbouwing · btw 21%',
  staande_regel_kandidaat: false,
}

const VERPLICHTING: WachtrijItemDto = {
  ...FACTUUR,
  document_id: 'd2',
  referentie: null,
  factuurdatum: null,
  totaalbedrag: '48500.00',
  boeking_omschrijving: null,
  soort: 'verplichting',
  verplichting: {
    soort_label: 'offerte',
    project_naam: '26140',
    totaal_excl: '48500.00',
    geldig_tot: '2026-12-31',
    omschrijving: 'Verbouwing Koningstraat',
  },
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stubFetch(items: WachtrijItemDto[]) {
  const mock = vi.fn((invoer: RequestInfo | URL) => {
    const pad = String(invoer).split('?')[0]
    if (pad === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
    if (pad === '/accordering/wachtrij') return Promise.resolve(jsonResponse({ items }))
    if (pad === '/accordering/vragen') return Promise.resolve(jsonResponse({ items: [] }))
    if (pad === '/auth/administraties') {
      return Promise.resolve(jsonResponse({ administraties: [{ id: 'a1', naam: 'Kempen Facilities B.V.' }] }))
    }
    if (pad.endsWith('/bestand')) {
      return Promise.resolve(new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 }))
    }
    return Promise.resolve(new Response(null, { status: 404 }))
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

function renderFlow() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <GoedkeurenFlow wisselThema={() => {}} uitloggen={() => Promise.resolve()} />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('GoedkeurenFlow — verplichtingen + offerte-match', () => {
  beforeEach(() => {
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} }))
    besluitVerzender.resetVoorTests()
    factuurCache.resetVoorTests()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('kaart voor een verplichting: soort-chip, werk/project/geldigheid en het bedrag excl.', async () => {
    stubFetch([VERPLICHTING])
    renderFlow()

    expect(await screen.findByTestId('acc-verplichting-chip')).toHaveTextContent('Offerte')
    expect(screen.getByText('Confide Bouw B.V.')).toBeInTheDocument()
    expect(screen.getByText(/Verbouwing Koningstraat · project 26140 · geldig t\/m 31-12-2026/)).toBeInTheDocument()
    expect(screen.getByText('€ 48.500,00')).toBeInTheDocument()
  })

  it('review-pane van een verplichting heet "Verplichting:" en zegt expliciet dat er niets geboekt wordt', async () => {
    stubFetch([VERPLICHTING])
    renderFlow()

    await userEvent.click(await screen.findByText('Confide Bouw B.V.'))
    expect(await screen.findByText(/Verplichting:/)).toBeInTheDocument()
    expect(screen.getByTestId('acc-verplichting-toelicht')).toHaveTextContent(/er wordt niets geboekt/i)
    expect(screen.queryByText(/^Boeking:/)).not.toBeInTheDocument()
    // De accordeur beslist met dezelfde twee knoppen.
    expect(screen.getByRole('button', { name: 'Akkoord ✓' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Afwijzen' })).toBeInTheDocument()
  })

  it('factuur binnen de offerte: groene melding mét balk en het VOORINGEVULDE conform-vinkje (optie A)', async () => {
    stubFetch([
      {
        ...FACTUUR,
        offerte_match: {
          uitkomst: 'binnen',
          offertenummer: '26140-OFF-01',
          leverancier_naam: 'Confide Bouw B.V.',
          goedgekeurd_door_naam: 'J. de Groot',
          goedgekeurd_op: '2026-09-04T10:00:00Z',
          bedrag_excl: '12400.00',
          verbruik_na: '27150.00',
          totaal_excl: '48500.00',
          percentage_na: 56,
          overschrijding_excl: null,
        },
      },
    ])
    renderFlow()

    // Kaartchip in de wachtrij.
    expect(await screen.findByTestId('acc-offerte-chip')).toHaveTextContent('Conform offerte')
    await userEvent.click(screen.getByText('Confide Bouw B.V.'))

    const melding = await screen.findByTestId('acc-offerte-melding')
    expect(melding.className).toContain('binnen')
    expect(melding).toHaveTextContent('✓ Binnen de goedgekeurde offerte 26140-OFF-01')
    expect(melding).toHaveTextContent('€ 27.150,00 van € 48.500,00')
    expect(melding).toHaveTextContent('akkoord J. de Groot')

    const conform = screen.getByTestId('acc-conform')
    const vinkje = within(conform).getByRole('checkbox')
    expect(vinkje).toBeChecked()
    expect(conform).toHaveTextContent('Conform offerte 26140-OFF-01')
    // Het vinkje is presentatie: het akkoord komt van de knop, die staat er los van.
    expect(conform).toHaveTextContent(/Je akkoord geef je zelf met de knop/i)
    expect(screen.getByRole('button', { name: 'Akkoord ✓' })).toBeEnabled()
    await userEvent.click(vinkje)
    expect(vinkje).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Akkoord ✓' })).toBeEnabled()
  })

  it('factuur buiten de offerte: oranje melding mét het bedrag erover — geen blokkade', async () => {
    stubFetch([
      {
        ...FACTUUR,
        offerte_match: {
          uitkomst: 'buiten',
          offertenummer: '26133-OFF-02',
          leverancier_naam: 'GNM B.V.',
          goedgekeurd_door_naam: 'P. Nijenhuis',
          goedgekeurd_op: '2026-08-28T10:00:00Z',
          bedrag_excl: '5000.00',
          verbruik_na: '19870.00',
          totaal_excl: '18500.00',
          percentage_na: 107,
          overschrijding_excl: '1370.00',
        },
      },
    ])
    renderFlow()

    expect(await screen.findByTestId('acc-offerte-chip')).toHaveTextContent('Buiten offerte')
    await userEvent.click(screen.getByText('Confide Bouw B.V.'))

    const melding = await screen.findByTestId('acc-offerte-melding')
    expect(melding.className).toContain('buiten')
    expect(melding).toHaveTextContent('⚠ Buiten de offerte 26133-OFF-02')
    expect(melding).toHaveTextContent('€ 1.370,00 erover')
    expect(screen.getByRole('button', { name: 'Akkoord ✓' })).toBeEnabled()
  })

  it('een factuur zónder offerte-match toont geen melding en geen vinkje', async () => {
    stubFetch([FACTUUR])
    renderFlow()

    await userEvent.click(await screen.findByText('Confide Bouw B.V.'))
    await waitFor(() => expect(screen.getByText('Verbouwing · btw 21%')).toBeInTheDocument())
    expect(screen.queryByTestId('acc-offerte-melding')).not.toBeInTheDocument()
    expect(screen.queryByTestId('acc-conform')).not.toBeInTheDocument()
  })
})
