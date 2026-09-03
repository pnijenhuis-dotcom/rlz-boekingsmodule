import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ArchiefScreen } from './ArchiefScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const TWEEDE_ADMINISTRATIE_ID = 'ffffffff-0000-0000-0000-000000000005'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const TWEEDE_DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000003'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function archiefDocument(overrides: Record<string, unknown> = {}) {
  return {
    document_id: DOCUMENT_ID,
    administratie_id: ADMINISTRATIE_ID,
    administratie_naam: 'Kempen Groep B.V.',
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

function tweedeDocument() {
  return archiefDocument({
    document_id: TWEEDE_DOCUMENT_ID,
    administratie_id: TWEEDE_ADMINISTRATIE_ID,
    administratie_naam: 'BLOW B.V.',
    bestandsnaam: 'riwal-lift.pdf',
    leverancier: 'Riwal',
    referentie: 'R-77',
    rlz_boekstuknummer: 'IF-2026-0300',
    totaalbedrag: '2140.00',
    automatisch_geboekt: false,
  })
}

interface MockOpties {
  documenten?: unknown[]
  totaal?: number
  bestandAanroepen?: string[]
  archiefAanroepen?: string[]
}

function installFetchMock(opties: MockOpties = {}) {
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
      if (pad.includes('/archief?')) {
        opties.archiefAanroepen?.push(pad)
        const params = new URL(pad, 'http://test').searchParams
        const facet = params.get('administratie_id')
        const alle = (opties.documenten ?? []) as Array<{ administratie_id: string }>
        const documenten = facet ? alle.filter((d) => d.administratie_id === facet) : alle
        const administraties = new Set(documenten.map((d) => d.administratie_id))
        return Promise.resolve(
          jsonResponse({
            documenten,
            totaal: facet ? documenten.length : (opties.totaal ?? documenten.length),
            pagina: Number(params.get('pagina') ?? 1),
            per_pagina: 25,
            van: params.get('van') ?? '2025-09-03',
            tot: params.get('tot') ?? '2026-09-03',
            administraties_met_documenten: administraties.size,
            facet: [
              { administratie_id: ADMINISTRATIE_ID, naam: 'Kempen Groep B.V.', aantal: 1 },
              { administratie_id: TWEEDE_ADMINISTRATIE_ID, naam: 'BLOW B.V.', aantal: 1 },
            ].filter((f) => alle.some((d) => d.administratie_id === f.administratie_id)),
          }),
        )
      }
      if (pad.endsWith('/bestand')) {
        opties.bestandAanroepen?.push(pad)
        return Promise.resolve(new Response(new Blob(['%PDF-fake']), { status: 200 }))
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
        <Route path="/documenten/:administratieId/:documentId" element={<div>controlescherm-probe</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

/** De administratie-kiezer is een doorzoekbare combobox (punt 13, opruimrun 28-08). */
async function kiesAdministratie(gebruiker: ReturnType<typeof userEvent.setup>, naam: RegExp) {
  await gebruiker.click(await screen.findByLabelText('Administratie'))
  await gebruiker.click(await screen.findByRole('option', { name: naam }))
}

const laatste = (aanroepen: string[]) => aanroepen[aanroepen.length - 1]

describe('ArchiefScreen — kantoorbreed bladeren (B4 03-09, bewaarplicht 7 jaar)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('opent kantoorbreed zónder administratie-keuze: rijen uit twee administraties, kolom Administratie, teller over M administraties', async () => {
    const archiefAanroepen: string[] = []
    installFetchMock({ documenten: [archiefDocument(), tweedeDocument()], archiefAanroepen })
    renderScherm()

    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    expect(screen.getByText('Riwal')).toBeInTheDocument()
    // Kantoorbreed endpoint, gepagineerd, zónder facet en zónder van/tot (server vult de default).
    expect(archiefAanroepen[0]).toContain('/archief?pagina=1&per_pagina=25')
    expect(archiefAanroepen[0]).not.toContain('administratie_id=')
    expect(archiefAanroepen[0]).not.toContain('van=')
    // Kolom Administratie per rij + teller "N documenten over M administraties".
    expect(screen.getByRole('columnheader', { name: /Administratie/ })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'BLOW B.V.' })).toBeInTheDocument()
    expect(screen.getByText('2 documenten over 2 administraties')).toBeInTheDocument()
    // Default-datumvenster zichtbaar ingevuld uit het antwoord.
    expect(screen.getByLabelText('Geboekt van')).toHaveValue('2025-09-03')
    expect(screen.getByLabelText('tot en met')).toHaveValue('2026-09-03')
    expect(screen.getByText('IF-2026-0219')).toBeInTheDocument()
    expect(screen.getByText(/922,04/)).toBeInTheDocument()
    expect(screen.getByText('automatisch')).toHaveClass('chip')
  })

  it('facet: administratie kiezen stuurt administratie_id mee (met aantal in de kiezer), "Alle administraties" wist het weer', async () => {
    const gebruiker = userEvent.setup()
    const archiefAanroepen: string[] = []
    installFetchMock({ documenten: [archiefDocument(), tweedeDocument()], archiefAanroepen })
    renderScherm()
    await waitFor(() => expect(screen.getByText('Riwal')).toBeInTheDocument())

    await kiesAdministratie(gebruiker, /BLOW B\.V\. \(1\)/)
    await waitFor(() => expect(laatste(archiefAanroepen)).toContain(`administratie_id=${TWEEDE_ADMINISTRATIE_ID}`))
    await waitFor(() => expect(screen.queryByText('Bouwmaat Nederland B.V.')).not.toBeInTheDocument())
    expect(screen.getByText('Riwal')).toBeInTheDocument()
    // Eén administratie gekozen: teller zonder "over M administraties".
    expect(screen.getByText('1 document')).toBeInTheDocument()

    await gebruiker.click(screen.getByRole('button', { name: 'Alle administraties' }))
    await waitFor(() => expect(laatste(archiefAanroepen)).not.toContain('administratie_id='))
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
  })

  it('/archief?administratie=X opent met voorgevulde facet (klantpagina-deeplink)', async () => {
    const archiefAanroepen: string[] = []
    installFetchMock({ documenten: [archiefDocument(), tweedeDocument()], archiefAanroepen })
    renderScherm(`/archief?administratie=${ADMINISTRATIE_ID}`)

    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    expect(archiefAanroepen[0]).toContain(`administratie_id=${ADMINISTRATIE_ID}`)
    expect(screen.queryByText('Riwal')).not.toBeInTheDocument()
  })

  it('sorteerbare koppen: klik = oplopend → aflopend → uit, mét aria-sort en sort= in de request', async () => {
    const gebruiker = userEvent.setup()
    const archiefAanroepen: string[] = []
    installFetchMock({ documenten: [archiefDocument(), tweedeDocument()], archiefAanroepen })
    renderScherm()
    await waitFor(() => expect(screen.getByText('Riwal')).toBeInTheDocument())

    const kop = () => screen.getByRole('columnheader', { name: /Bedrag/ })
    const knop = () => screen.getByRole('button', { name: 'Bedrag' })
    expect(kop()).toHaveAttribute('aria-sort', 'none')
    expect(knop()).toHaveAttribute('title', 'Sorteer oplopend op bedrag')
    await gebruiker.click(knop())
    await waitFor(() => expect(laatste(archiefAanroepen)).toContain('sort=bedrag%3Aasc'))
    await waitFor(() => expect(kop()).toHaveAttribute('aria-sort', 'ascending'))
    expect(knop()).toHaveAttribute('title', expect.stringContaining('klik voor aflopend'))

    await gebruiker.click(knop())
    await waitFor(() => expect(laatste(archiefAanroepen)).toContain('sort=bedrag%3Adesc'))
    await waitFor(() => expect(kop()).toHaveAttribute('aria-sort', 'descending'))
    expect(knop()).toHaveAttribute('title', expect.stringContaining('op te heffen'))

    await gebruiker.click(knop())
    await waitFor(() => expect(laatste(archiefAanroepen)).not.toContain('sort='))
    await waitFor(() => expect(kop()).toHaveAttribute('aria-sort', 'none'))
  })

  it('paginering uit totaal: "1–25 van 30", Volgende stuurt pagina=2; datumfilter wijzigen springt terug naar pagina 1', async () => {
    const gebruiker = userEvent.setup()
    const archiefAanroepen: string[] = []
    installFetchMock({ documenten: [archiefDocument()], totaal: 30, archiefAanroepen })
    renderScherm()
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    expect(screen.getByText('1–25 van 30 documenten')).toBeInTheDocument()

    await gebruiker.click(screen.getByRole('button', { name: 'Volgende pagina' }))
    await waitFor(() => expect(laatste(archiefAanroepen)).toContain('pagina=2&per_pagina=25'))

    fireEvent.change(screen.getByLabelText('Geboekt van'), { target: { value: '2024-01-01' } })
    await waitFor(() => expect(laatste(archiefAanroepen)).toContain('pagina=1&per_pagina=25&van=2024-01-01'))
  })

  it('zoekveld stuurt q= mee (gedebounced)', async () => {
    const gebruiker = userEvent.setup()
    const archiefAanroepen: string[] = []
    installFetchMock({ documenten: [archiefDocument()], archiefAanroepen })
    renderScherm()
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())

    await gebruiker.type(screen.getByLabelText('Zoeken'), 'riwal')
    await waitFor(() => expect(laatste(archiefAanroepen)).toContain('q=riwal'))
  })

  it('lege staat: melding mét de 7-jaarsbewaarplicht-hint', async () => {
    installFetchMock({ documenten: [] })
    renderScherm()

    await waitFor(() => expect(screen.getByText(/Geen geboekte documenten in dit datumvenster/)).toBeInTheDocument())
    expect(screen.getByText(/7 jaar/)).toBeInTheDocument()
  })

  it('het ⋯-menu opent de PDF via de administratie van de RIJ (niet een schermbrede keuze)', async () => {
    const gebruiker = userEvent.setup()
    const bestandAanroepen: string[] = []
    installFetchMock({ documenten: [archiefDocument(), tweedeDocument()], bestandAanroepen })
    const createObjectURL = vi.fn(() => 'blob:test-url')
    const revokeObjectURL = vi.fn()
    Object.assign(URL, { createObjectURL, revokeObjectURL })
    const openSpy = vi.spyOn(window, 'open').mockReturnValue(null)
    renderScherm()
    await waitFor(() => expect(screen.getByText('Riwal')).toBeInTheDocument())

    await gebruiker.click(screen.getByRole('button', { name: /Acties voor riwal-lift\.pdf/ }))
    await gebruiker.click(screen.getByRole('menuitem', { name: 'PDF openen' }))

    await waitFor(() => expect(openSpy).toHaveBeenCalledWith('blob:test-url', '_blank', 'noopener'))
    expect(bestandAanroepen).toHaveLength(1)
    expect(bestandAanroepen[0]).toContain(`/administraties/${TWEEDE_ADMINISTRATIE_ID}/documenten/${TWEEDE_DOCUMENT_ID}/bestand`)

    openSpy.mockRestore()
    delete (URL as unknown as Record<string, unknown>).createObjectURL
    delete (URL as unknown as Record<string, unknown>).revokeObjectURL
  })

  it('rij-klik opent het reviewscherm van de juiste soort én administratie', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [archiefDocument(), tweedeDocument()] })
    renderScherm()
    await waitFor(() => expect(screen.getByText('Riwal')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('Riwal'))

    await waitFor(() => expect(screen.getByText('controlescherm-probe')).toBeInTheDocument())
  })
})
