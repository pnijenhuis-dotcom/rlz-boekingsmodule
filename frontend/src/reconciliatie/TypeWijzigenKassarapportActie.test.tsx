import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BevindingDto } from './reconciliatieApi'
import { isKassarapportInWerkvoorraad, TypeWijzigenKassarapportActie } from './TypeWijzigenKassarapportActie'

function bevinding(overrides: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-1',
    run_id: 'run-1',
    blok: 'omzet',
    soort: 'afwijking',
    administratie_id: 'adm-1',
    administratie_naam: 'Van Boxtel Horeca Exploitatie B.V.',
    vingerafdruk: 'vaf',
    tekst: 'AFWIJKING …',
    titel: 'Kassarapport in de werkvoorraad · Journaal 31-8.pdf',
    wat: 'Journaal 31-8.pdf is als inkoopfactuur binnengekomen, maar de inhoud is een herkend kassarapport (profx journaal).',
    doe: 'Klik "Type wijzigen → kassarapport".',
    details: [],
    sinds: '2026-09-16T05:30:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: { afwijking_soort: 'kassarapport_in_werkvoorraad', document_id: 'doc-1' },
    doel_pad: '/?administratie=adm-1&document=doc-1',
    ...overrides,
  } as BevindingDto
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('TypeWijzigenKassarapportActie (blok C, 16-09 avond)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('herkent alleen de omzet-afwijking kassarapport_in_werkvoorraad', () => {
    expect(isKassarapportInWerkvoorraad(bevinding())).toBe(true)
    expect(isKassarapportInWerkvoorraad(bevinding({ detail: { afwijking_soort: 'omzet_in_inkoopstroom' } }))).toBe(false)
    expect(isKassarapportInWerkvoorraad(bevinding({ blok: 'documenten' }))).toBe(false)
  })

  it('één klik → POST zonder reden, daarna een link naar het kassarapport', async () => {
    const aanroepen: { pad: string; body: Record<string, unknown> }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push({ pad: url, body: JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown> })
        return Promise.resolve(
          jsonResponse({ document_id: 'doc-1', status: 'ontvangen', van_soort: 'inkoopfactuur', naar_soort: 'kassarapport', doel_pad: '/?administratie=adm-1&document=doc-1' }),
        )
      }),
    )
    const gelukt = vi.fn()
    render(
      <MemoryRouter>
        <TypeWijzigenKassarapportActie bevinding={bevinding()} onGelukt={gelukt} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /Type wijzigen naar kassarapport/ }))
    await waitFor(() => expect(gelukt).toHaveBeenCalled())
    expect(aanroepen).toEqual([{ pad: '/reconciliatie/bevindingen/bev-1/type-wijzigen-kassarapport', body: { administratie_id: 'adm-1' } }])
    expect(screen.getByRole('link', { name: 'Naar het kassarapport' })).toHaveAttribute('href', '/?administratie=adm-1&document=doc-1')
  })

  it('toont de serverfout (409: geboekt) zichtbaar naast de knop', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse({ detail: 'Een geboekt document wissel je niet van type' }, 409))))
    render(
      <MemoryRouter>
        <TypeWijzigenKassarapportActie bevinding={bevinding()} onGelukt={vi.fn()} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /Type wijzigen naar kassarapport/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('geboekt')
  })
})
