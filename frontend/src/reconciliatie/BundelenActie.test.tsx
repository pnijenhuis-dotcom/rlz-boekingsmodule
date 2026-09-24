import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BundelenActie, isUblPdfOngebundeld } from './BundelenActie'
import type { BevindingDto } from './reconciliatieApi'

// Blok 1 bundelrun 24-09 (Vastly-batch 23-09): losse PDF hoort bij een UBL-verkoopfactuur → één klik "Bundelen".

function bevinding(overrides: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-1',
    run_id: 'run-1',
    blok: 'documenten',
    soort: 'afwijking',
    administratie_id: 'adm-1',
    administratie_naam: 'Rubicon Investments B.V.',
    vingerafdruk: 'vaf',
    tekst: 'AFWIJKING …',
    titel: 'Losse PDF hoort bij een verkoopfactuur · factuur-RUB-2026-0031.pdf',
    wat: 'factuur-RUB-2026-0031.pdf staat als inkoopfactuur in de werkvoorraad, maar hoort op dezelfde bestandsnaam bij de UBL-verkoopfactuur factuur-RUB-2026-0031-ubl.xml …',
    doe: "Klik 'Bundelen' …",
    details: [],
    sinds: '2026-09-24T04:30:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: { afwijking_soort: 'ubl_pdf_ongebundeld', document_id: 'pdf-1', ubl_document_id: 'ubl-1', match_basis: 'naamstam' },
    doel_pad: '/?administratie=adm-1&document=pdf-1',
    ...overrides,
  } as BevindingDto
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('BundelenActie (blok 1 bundelrun 24-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('herkent alleen de documenten-afwijking ubl_pdf_ongebundeld mét document_id', () => {
    expect(isUblPdfOngebundeld(bevinding())).toBe(true)
    expect(isUblPdfOngebundeld(bevinding({ detail: { afwijking_soort: 'intussen_extern_geboekt', document_id: 'x' } }))).toBe(false)
    expect(isUblPdfOngebundeld(bevinding({ blok: 'omzet' }))).toBe(false)
    expect(isUblPdfOngebundeld(bevinding({ administratie_id: null }))).toBe(false)
  })

  it('één klik → POST zonder reden, melding mét Reeleezee-bijlage, daarna een link naar de verkoopfactuur', async () => {
    const aanroepen: { pad: string; body: Record<string, unknown> }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push({ pad: url, body: JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown> })
        return Promise.resolve(
          jsonResponse({ document_id: 'pdf-1', ubl_document_id: 'ubl-1', status: 'gebundeld', match_basis: 'naamstam', rlz_bijlage: 'geüpload op SalesInvoices/abc', doel_pad: '/verkoop/adm-1/ubl-1' }),
        )
      }),
    )
    const gelukt = vi.fn()
    render(
      <MemoryRouter>
        <BundelenActie bevinding={bevinding()} onGelukt={gelukt} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /^Bundelen:/ }))
    await waitFor(() => expect(gelukt).toHaveBeenCalled())
    expect(aanroepen).toEqual([{ pad: '/reconciliatie/documenten/pdf-1/bundelen', body: { administratie_id: 'adm-1' } }])
    expect(gelukt.mock.calls[0][0]).toContain('Reeleezee-bijlage: geüpload op SalesInvoices/abc')
    expect(screen.getByRole('link', { name: 'Naar de verkoopfactuur' })).toHaveAttribute('href', '/verkoop/adm-1/ubl-1')
  })

  it('toont 409 (twijfel) zichtbaar naast de knop — niets verdwijnt stil', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse({ detail: 'meerdere UBL-kandidaten (a.xml, b.xml) — niet gebundeld' }, 409))))
    render(
      <MemoryRouter>
        <BundelenActie bevinding={bevinding()} onGelukt={vi.fn()} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /^Bundelen:/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('meerdere UBL-kandidaten')
  })
})
