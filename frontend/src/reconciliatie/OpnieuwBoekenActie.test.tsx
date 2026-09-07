import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isVerdwenenDocument, OpnieuwBoekenActie } from './OpnieuwBoekenActie'
import type { BevindingDto } from './reconciliatieApi'

// A11 (07-09): "Opnieuw boeken…" op een documenten-afwijking `ontbreekt_in_rlz`/`ontbreekt_in_odoo` — teal knop,
// bevestigingsdialoog mét leverancier/factuurnummer en VERPLICHTE reden (≥ 5 tekens), POST naar het endpoint,
// daarna de melding + de link "Nu boeken →" naar het controlescherm; een serverfout blijft zichtbaar.

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'

function bevinding(extra: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-1',
    run_id: 'run-1',
    blok: 'documenten',
    soort: 'afwijking',
    administratie_id: ADMIN,
    administratie_naam: 'Kempen Facilities B.V.',
    vingerafdruk: 'vaf1',
    tekst: 'document=doc-1 rlz_document=guid soort=ontbreekt_in_rlz [vaf:vaf1]: 404',
    titel: 'Factuur 202632704 van BOOT ontbreekt in Reeleezee',
    wat: '',
    doe: '',
    details: [],
    sinds: '2026-09-07T05:00:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: {
      bron: 'documenten',
      afwijking_soort: 'ontbreekt_in_rlz',
      document_id: 'doc-1',
      leverancier_naam: 'BOOT organiserend ingenieursburo B.V.',
      factuurnummer: '202632704',
      rlz_boekstuk: 'RLZ-04-00004038',
      backend: 'rlz',
    },
    doel_pad: `/?administratie=${ADMIN}&document=doc-1`,
    ...extra,
  }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('OpnieuwBoekenActie', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('isVerdwenenDocument: alleen documenten-blok met ontbreekt_in_rlz/odoo', () => {
    expect(isVerdwenenDocument(bevinding())).toBe(true)
    expect(isVerdwenenDocument(bevinding({ detail: { afwijking_soort: 'ontbreekt_in_odoo' } }))).toBe(true)
    expect(isVerdwenenDocument(bevinding({ detail: { afwijking_soort: 'bedrag_wijkt_af' } }))).toBe(false)
    expect(isVerdwenenDocument(bevinding({ blok: 'bank' }))).toBe(false)
    expect(isVerdwenenDocument(bevinding({ detail: null }))).toBe(false)
  })

  it('toont leverancier/factuurnummer, eist een reden, post naar het endpoint en toont daarna "Nu boeken →"', async () => {
    const aangeroepen: { pad: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aangeroepen.push({ pad: url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
        return Promise.resolve(
          jsonResponse({ document_id: 'doc-1', status: 'klaar_om_te_boeken', boek_cyclus: 1, doel_pad: `/?administratie=${ADMIN}&document=doc-1` }),
        )
      }),
    )
    const onGelukt = vi.fn()
    const onAccepteren = vi.fn()
    render(
      <MemoryRouter>
        <OpnieuwBoekenActie bevinding={bevinding()} onGelukt={onGelukt} onAccepteren={onAccepteren} />
      </MemoryRouter>,
    )
    // Primaire (teal) knop + de secundaire accepteer-knop ernaast.
    await userEvent.click(screen.getByRole('button', { name: /^Opnieuw boeken/ }))
    const dialoog = await screen.findByTestId('opnieuw-boeken-dialoog')
    expect(dialoog).toHaveTextContent('BOOT organiserend ingenieursburo B.V.')
    expect(dialoog).toHaveTextContent('202632704')
    expect(dialoog).toHaveTextContent('RLZ-04-00004038')
    expect(dialoog).toHaveTextContent('Reeleezee')
    const bevestig = screen.getByRole('button', { name: 'Terug naar klaar om te boeken' })
    expect(bevestig).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Reden'), 'ok')
    expect(bevestig).toBeDisabled()
    expect(screen.getByText(/minimaal 5 tekens/)).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Reden'), ' — per abuis verwijderd in RLZ (kliktest 16-08)')
    expect(bevestig).toBeEnabled()
    await userEvent.click(bevestig)
    await waitFor(() => expect(onGelukt).toHaveBeenCalled())
    expect(aangeroepen.some((a) => a.pad === '/reconciliatie/bevindingen/bev-1/opnieuw-boeken')).toBe(true)
    const post = aangeroepen.find((a) => a.pad === '/reconciliatie/bevindingen/bev-1/opnieuw-boeken')!
    expect(post.body).toMatchObject({ administratie_id: ADMIN })
    expect((post.body as { reden: string }).reden).toMatch(/per abuis verwijderd/)
    expect(onGelukt.mock.calls[0][0]).toMatch(/klaar om te boeken/)
    expect(onGelukt.mock.calls[0][1]).toBe(`/?administratie=${ADMIN}&document=doc-1`)
    // Ná succes: geen dialoog meer, wél de directe link naar het controlescherm.
    expect(screen.queryByTestId('opnieuw-boeken-dialoog')).toBeNull()
    expect(screen.getByRole('link', { name: /Naar het document om opnieuw te boeken/ })).toHaveAttribute(
      'href',
      `/?administratie=${ADMIN}&document=doc-1`,
    )
  })

  it('toont de serverfout in de dialoog (409: document bestaat nog) en roept onGelukt niet aan', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse({ detail: 'Het externe document bestaat nog (RLZ-04-00004038, status 2) — corrigeer via storno of tegenboeken' }, 409))),
    )
    const onGelukt = vi.fn()
    render(
      <MemoryRouter>
        <OpnieuwBoekenActie bevinding={bevinding()} onGelukt={onGelukt} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /^Opnieuw boeken/ }))
    await userEvent.type(await screen.findByLabelText('Reden'), 'document verdwenen na kliktest')
    await userEvent.click(screen.getByRole('button', { name: 'Terug naar klaar om te boeken' }))
    expect(await screen.findByText(/bestaat nog/)).toBeInTheDocument()
    expect(onGelukt).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /Accepteren/ })).toBeNull()
  })
})
