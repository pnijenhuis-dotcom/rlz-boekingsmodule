/** Blok 1 07-09 (besluit Peter "moet er toch een geboekt worden, dan zoek ik hem in het archief"): statusfilter
 * "Afgevoerd als duplicaat" binnen het bestaande archiefscherm — chip mét referentie, link naar het origineel en de
 * actie "Terug naar werkvoorraad" (bestaand heropenen-pad). */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ArchiefScreen } from './ArchiefScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const ORIGINEEL_ID = 'cccccccc-0000-0000-0000-000000000003'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function afgevoerdDocument() {
  return {
    document_id: DOCUMENT_ID,
    administratie_id: ADMINISTRATIE_ID,
    administratie_naam: 'Kempen Facilities B.V.',
    soort: 'inkoopfactuur',
    bestandsnaam: '2026-0322 (2).pdf',
    leverancier: 'Meer Leisure B.V.',
    referentie: '2026-0322',
    rlz_boekstuknummer: null,
    totaalbedrag: '7927.80',
    factuurdatum: '2026-08-29',
    geboekt_op: null,
    automatisch_geboekt: false,
    tegengeboekt: false,
    status: 'afgewezen',
    afgevoerd_als_duplicaat_van: {
      document_id: ORIGINEEL_ID,
      referentie: '2026-0322',
      bestandsnaam: '2026-0322.pdf',
      afgevoerd_op: '2026-09-07T14:00:00Z',
      automatisch: true,
    },
  }
}

function installFetchMock(aanroepen: string[], heropenAanroepen: string[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const pad = String(url)
      if (pad.endsWith('/auth/administraties')) {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Kempen Facilities B.V.' }] }))
      }
      if (pad.includes('/archief?')) {
        aanroepen.push(pad)
        const params = new URL(pad, 'http://test').searchParams
        const afgevoerd = params.get('status') === 'afgevoerd'
        // Ná heropenen is de rij weg uit het afgevoerd-filter.
        const documenten = afgevoerd && heropenAanroepen.length === 0 ? [afgevoerdDocument()] : []
        return Promise.resolve(
          jsonResponse({
            documenten,
            totaal: documenten.length,
            pagina: 1,
            per_pagina: 25,
            van: '2025-09-07',
            tot: '2026-09-07',
            administraties_met_documenten: documenten.length ? 1 : 0,
            facet: documenten.length ? [{ administratie_id: ADMINISTRATIE_ID, naam: 'Kempen Facilities B.V.', aantal: 1 }] : [],
          }),
        )
      }
      if (pad.endsWith('/heropenen') && init?.method === 'POST') {
        heropenAanroepen.push(pad)
        return Promise.resolve(jsonResponse({ id: 'x', document_id: DOCUMENT_ID, document_status: 'te_controleren' }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm(pad = '/archief') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
      <Routes>
        <Route path="/archief" element={<ArchiefScreen />} />
        <Route path="/documenten/:administratieId/:documentId" element={<div>documentpagina-probe</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('ArchiefScreen — statusfilter "Afgevoerd als duplicaat" (blok 1 07-09)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('default = geboekt (geen status-parameter); de kiezer "Tonen" stuurt status=afgevoerd mee en toont chip + origineel-link', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: string[] = []
    installFetchMock(aanroepen, [])
    renderScherm()

    await waitFor(() => expect(aanroepen.length).toBeGreaterThan(0))
    expect(aanroepen[0]).not.toContain('status=')
    expect(screen.getByLabelText('Geboekt van')).toBeInTheDocument()

    await gebruiker.selectOptions(screen.getByLabelText('Tonen'), 'afgevoerd')
    await waitFor(() => expect(aanroepen[aanroepen.length - 1]).toContain('status=afgevoerd'))
    await waitFor(() => expect(screen.getByText('Meer Leisure B.V.')).toBeInTheDocument())
    expect(screen.getByLabelText('Afgevoerd van')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: /Afgevoerd op/ })).toBeInTheDocument()
    const chip = screen.getByText(/afgevoerd als duplicaat van/)
    expect(chip).toHaveClass('chip')
    expect(chip).toHaveTextContent('afgevoerd als duplicaat van 2026-0322')
    expect(screen.getByRole('link', { name: 'open origineel' })).toHaveAttribute('href', `/documenten/${ADMINISTRATIE_ID}/${ORIGINEEL_ID}`)
  })

  it('/archief?status=afgevoerd opent direct in het afgevoerd-filter; ⋯ → "Terug naar werkvoorraad" heropent en herlaadt', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: string[] = []
    const heropen: string[] = []
    installFetchMock(aanroepen, heropen)
    renderScherm('/archief?status=afgevoerd')

    await waitFor(() => expect(screen.getByText('Meer Leisure B.V.')).toBeInTheDocument())
    expect(aanroepen[0]).toContain('status=afgevoerd')

    await gebruiker.click(screen.getByRole('button', { name: 'Acties voor 2026-0322 (2).pdf' }))
    // Geen "Tegenboeken…" op een afgevoerd duplicaat (niets geboekt); wél terughalen.
    expect(screen.queryByRole('menuitem', { name: 'Tegenboeken…' })).not.toBeInTheDocument()
    await gebruiker.click(screen.getByRole('menuitem', { name: 'Terug naar werkvoorraad' }))

    await waitFor(() => expect(heropen).toHaveLength(1))
    expect(heropen[0]).toContain(`/administraties/${ADMINISTRATIE_ID}/documenten/${DOCUMENT_ID}/heropenen`)
    // Herladen: rij verdwijnt uit het afgevoerd-filter, lege stand benoemt het filter.
    await waitFor(() => expect(screen.queryByText('Meer Leisure B.V.')).not.toBeInTheDocument())
    expect(screen.getByText(/Geen als duplicaat afgevoerde documenten/)).toBeInTheDocument()
  })
})
