import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ArchiefScreen } from './ArchiefScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const TWEEDE_ADMINISTRATIE_ID = 'ffffffff-0000-0000-0000-000000000005'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function archiefDocument(overrides: Record<string, unknown> = {}) {
  return {
    document_id: DOCUMENT_ID,
    soort: 'inkoopfactuur',
    bestandsnaam: 'bouwmaat-factuur.pdf',
    leverancier: 'Bouwmaat Nederland B.V.',
    referentie: '2026-0601',
    rlz_boekstuknummer: 'IF-2026-0219',
    totaalbedrag: '922.04',
    factuurdatum: '2026-06-20',
    geboekt_op: '2026-06-24T09:30:00Z',
    automatisch_geboekt: true,
    tegengeboekt: false,
    ...overrides,
  }
}

function installFetchMock(opties: { documenten?: unknown[]; bestandAanroepen?: string[] } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const pad = String(url)
      if (pad.endsWith('/auth/administraties')) {
        return Promise.resolve(
          jsonResponse({
            administraties: [
              { id: ADMINISTRATIE_ID, naam: 'Kempen Groep B.V.' },
              { id: TWEEDE_ADMINISTRATIE_ID, naam: 'BLOW B.V.' },
            ],
          }),
        )
      }
      if (pad.endsWith('/archief')) {
        return Promise.resolve(jsonResponse({ documenten: opties.documenten ?? [] }))
      }
      if (pad.endsWith('/bestand')) {
        opties.bestandAanroepen?.push(pad)
        return Promise.resolve(new Response(new Blob(['%PDF-fake']), { status: 200 }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/archief']}>
      <Routes>
        <Route path="/archief" element={<ArchiefScreen />} />
        <Route path="/documenten/:administratieId/:documentId" element={<div>controlescherm-probe</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

/** Punt 13 (opruimrun 28-08): de administratie-kiezer is een doorzoekbare combobox — kiezen =
 * veld openen en de optie aanklikken (i.p.v. userEvent.selectOptions op een <select>). */
async function kiesAdministratie(gebruiker: ReturnType<typeof userEvent.setup>, label: string, naam: string) {
  await gebruiker.click(await screen.findByLabelText(label))
  await gebruiker.click(await screen.findByRole('option', { name: naam }))
}

describe('ArchiefScreen — geboekt archief per administratie (bewaarplicht 7 jaar)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('administratie kiezen → rijen met boekstuk, bedrag en de chip "automatisch"', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [archiefDocument()] })
    renderScherm()

    // Twee administraties in scope: het scherm start met een expliciete keuze.
    expect(await screen.findByText(/Kies een administratie/)).toBeInTheDocument()

    await kiesAdministratie(gebruiker, 'Administratie', 'Kempen Groep B.V.')

    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    expect(screen.getByText('2026-0601')).toBeInTheDocument()
    expect(screen.getByText('IF-2026-0219')).toBeInTheDocument()
    expect(screen.getByText(/922,04/)).toBeInTheDocument()
    const chip = screen.getByText('automatisch')
    expect(chip).toHaveClass('chip')
  })

  it('lege staat: melding mét de 7-jaarsbewaarplicht-hint', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [] })
    renderScherm()

    await kiesAdministratie(gebruiker, 'Administratie', 'Kempen Groep B.V.')

    await waitFor(() => expect(screen.getByText(/Nog geen geboekte documenten/)).toBeInTheDocument())
    expect(screen.getByText(/7 jaar/)).toBeInTheDocument()
  })

  it('de PDF-knop haalt het bestand op via het bestand-endpoint en opent het in een nieuw tabblad', async () => {
    const gebruiker = userEvent.setup()
    const bestandAanroepen: string[] = []
    installFetchMock({ documenten: [archiefDocument()], bestandAanroepen })
    // jsdom kent geen createObjectURL/open — stubs, alleen om de aanroep te toetsen.
    const createObjectURL = vi.fn(() => 'blob:test-url')
    const revokeObjectURL = vi.fn()
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    renderScherm()

    await kiesAdministratie(gebruiker, 'Administratie', 'Kempen Groep B.V.')
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    // Sinds het tegenboek-pad (22-08) zit de PDF-actie in het ⋯-menu per rij.
    await gebruiker.click(screen.getByRole('button', { name: /Acties voor bouwmaat-factuur\.pdf/ }))
    await gebruiker.click(screen.getByRole('menuitem', { name: 'PDF openen' }))

    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('blob:test-url', '_blank', 'noopener'))
    expect(bestandAanroepen).toHaveLength(1)
    expect(bestandAanroepen[0]).toContain(`/administraties/${ADMINISTRATIE_ID}/documenten/${DOCUMENT_ID}/bestand`)

    openSpy.mockRestore()
    delete (URL as unknown as Record<string, unknown>).createObjectURL
    delete (URL as unknown as Record<string, unknown>).revokeObjectURL
  })

  it('rij-klik opent het reviewscherm van de juiste soort', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [archiefDocument()] })
    renderScherm()

    await kiesAdministratie(gebruiker, 'Administratie', 'Kempen Groep B.V.')
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('Bouwmaat Nederland B.V.'))

    await waitFor(() => expect(screen.getByText('controlescherm-probe')).toBeInTheDocument())
  })
})
