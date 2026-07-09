import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DocumentDetailScreen } from './DocumentDetailScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const ORIGINEEL_ID = 'cccccccc-0000-0000-0000-000000000003'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function installFetchMock(detail: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.endsWith(`/documenten/${DOCUMENT_ID}`)) return Promise.resolve(jsonResponse(detail))
      if (url.endsWith('/bestand')) return Promise.resolve(new Response(new Blob(['%PDF-1.4']), { status: 200, headers: { 'Content-Type': 'application/pdf' } }))
      if (url.endsWith('/boekvoorstel')) {
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            vendor_id: null,
            referentie: null,
            factuurdatum: null,
            totaalbedrag: null,
            rlz_boekstuknummer: null,
            opgeslagen: false,
            regels: [],
          }),
        )
      }
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [] }))
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={[`/documenten/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`]}>
      <Routes>
        <Route path="/documenten/:administratieId/:documentId" element={<DocumentDetailScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('DocumentDetailScreen — tijdlijn en duplicaat', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont "Document binnengekomen" i.p.v. de kale "Ontvangen (status )"-placeholder', async () => {
    installFetchMock({
      id: DOCUMENT_ID,
      administratie_id: ADMINISTRATIE_ID,
      bestandsnaam: 'factuur.pdf',
      status: 'te_controleren',
      bron: 'upload',
      mogelijk_duplicaat_van: null,
      toegewezen_aan: null,
      aangemaakt_op: '2026-07-09T10:00:00Z',
      laatst_gewijzigd_op: '2026-07-09T10:00:00Z',
      veldvoorstel: null,
      tijdlijn: [{ van_status: null, naar_status: 'ontvangen', actor_id: 'x', detail: null, tijdstip: '2026-07-09T10:00:00Z' }],
    })

    renderScherm()

    await waitFor(() => expect(screen.getByText(/Document binnengekomen/)).toBeInTheDocument())
    expect(screen.queryByText(/status \)/)).not.toBeInTheDocument()
  })

  it('toont een klikbare duplicaat-link met bestandsnaam en datum, geen kale UUID', async () => {
    installFetchMock({
      id: DOCUMENT_ID,
      administratie_id: ADMINISTRATIE_ID,
      bestandsnaam: 'kopie.pdf',
      status: 'te_controleren',
      bron: 'upload',
      mogelijk_duplicaat_van: {
        document_id: ORIGINEEL_ID,
        bestandsnaam: 'origineel.pdf',
        aangemaakt_op: '2026-07-08T09:00:00Z',
      },
      toegewezen_aan: null,
      aangemaakt_op: '2026-07-09T10:00:00Z',
      laatst_gewijzigd_op: '2026-07-09T10:00:00Z',
      veldvoorstel: null,
      tijdlijn: [{ van_status: null, naar_status: 'ontvangen', actor_id: 'x', detail: null, tijdstip: '2026-07-09T10:00:00Z' }],
    })

    renderScherm()

    const link = await screen.findByRole('link', { name: /origineel\.pdf/ })
    expect(link).toHaveAttribute('href', `/documenten/${ADMINISTRATIE_ID}/${ORIGINEEL_ID}`)
    expect(screen.queryByText(ORIGINEEL_ID)).not.toBeInTheDocument()
  })
})
