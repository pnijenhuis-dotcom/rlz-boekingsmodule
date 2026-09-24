import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FactuurPdfHerstellenActie, isDoorbelastingFactuurPdfOntbreekt } from './FactuurPdfHerstellenActie'
import type { BevindingDto } from './reconciliatieApi'

// Stap 4 RLZ-vorm-opdracht 24-09: geboekte doorbelasting zonder factuur-PDF → één klik "Factuur-PDF herstellen".

function bevinding(overrides: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-1',
    run_id: 'run-1',
    blok: 'doorbelasting',
    soort: 'afwijking',
    administratie_id: 'adm-kf',
    administratie_naam: 'Kempen Facilities B.V.',
    vingerafdruk: 'vaf',
    tekst: 'AFWIJKING …',
    titel: 'Doorbelasting zonder factuur-PDF · Molenhof Verhuur B.V. ref 24713312',
    wat: 'De doorbelasting aan Molenhof Verhuur B.V. staat geboekt, maar de factuur op naam ontbreekt als bijlage.',
    doe: "Klik 'Factuur-PDF herstellen' …",
    details: [],
    sinds: '2026-09-25T04:30:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: { afwijking_soort: 'doorbelasting_factuur_pdf_ontbreekt', boeking_id: 'boek-1', document_id: 'doc-1' },
    doel_pad: '/doorbelasting/adm-kf/doc-1',
    ...overrides,
  } as BevindingDto
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('FactuurPdfHerstellenActie (RLZ-vorm 24-09, stap 4)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('herkent alleen de doorbelasting-afwijking doorbelasting_factuur_pdf_ontbreekt mét boeking_id', () => {
    expect(isDoorbelastingFactuurPdfOntbreekt(bevinding())).toBe(true)
    expect(isDoorbelastingFactuurPdfOntbreekt(bevinding({ detail: { afwijking_soort: 'doorbelasting_bedrag_afwijking', boeking_id: 'x' } }))).toBe(false)
    expect(isDoorbelastingFactuurPdfOntbreekt(bevinding({ blok: 'documenten' }))).toBe(false)
    expect(isDoorbelastingFactuurPdfOntbreekt(bevinding({ detail: { afwijking_soort: 'doorbelasting_factuur_pdf_ontbreekt' } }))).toBe(false)
    expect(isDoorbelastingFactuurPdfOntbreekt(bevinding({ administratie_id: null }))).toBe(false)
  })

  it('één klik → POST mét administratie_id, melding, daarna een link naar de doorbelasting', async () => {
    const aanroepen: { pad: string; body: Record<string, unknown> }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push({ pad: url, body: JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown> })
        return Promise.resolve(
          jsonResponse({
            boeking_id: 'boek-1',
            document_id: 'doc-1',
            doelentiteit_naam: 'Molenhof Verhuur B.V.',
            verkoop_referentie: '24713312',
            factuur_pdf_status: 'aanwezig',
            doel_pad: '/doorbelasting/adm-kf/doc-1',
          }),
        )
      }),
    )
    const gelukt = vi.fn()
    render(
      <MemoryRouter>
        <FactuurPdfHerstellenActie bevinding={bevinding()} onGelukt={gelukt} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /Factuur-PDF herstellen/ }))
    await waitFor(() => expect(gelukt).toHaveBeenCalled())
    expect(aanroepen).toHaveLength(1)
    expect(aanroepen[0].pad).toContain('/reconciliatie/doorbelasting/boek-1/factuur-herstellen')
    expect(aanroepen[0].body).toEqual({ administratie_id: 'adm-kf' })
    expect(gelukt.mock.calls[0][0]).toContain('Molenhof Verhuur B.V. (24713312)')
    expect(screen.getByRole('link', { name: 'Naar de doorbelasting' })).toHaveAttribute('href', '/doorbelasting/adm-kf/doc-1')
  })

  it('422 = de reden zichtbaar naast de knop, knop blijft', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          jsonResponse(
            { detail: 'factuur-PDF onvolledig: btw-som € 1.045,52 — de RLZ-factuur toont andere centen dan de module registreerde …' },
            422,
          ),
        ),
      ),
    )
    render(
      <MemoryRouter>
        <FactuurPdfHerstellenActie bevinding={bevinding()} onGelukt={vi.fn()} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /Factuur-PDF herstellen/ }))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('alert').textContent).toContain('andere centen')
    expect(screen.getByRole('button', { name: /Factuur-PDF herstellen/ })).toBeInTheDocument()
  })
})
