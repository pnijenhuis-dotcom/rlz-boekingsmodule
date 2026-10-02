import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BevindingDto } from './reconciliatieApi'
import {
  isVastlyEntiteitNietGekoppeld,
  isVastlyOmzetrekeningOntbreekt,
  isVastlyVerkoopNietGeboekt,
  MeldBijVastlyHint,
  meldBijVastlyTekst,
  OpnieuwAanbiedenActie,
} from './VastlyActies'

// 29-09 (Peter 28-09): Vastly-verkoop volledig automatisch; 01-10 (Peter): geen mens-keuze meer in de module — de enige
// handeling is "Opnieuw aanbieden", een ontbrekend administratie-id of grootboekcode is "melden bij Vastly".

function bevinding(overrides: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-1',
    run_id: 'run-1',
    blok: 'vastly_verkoop',
    soort: 'afwijking',
    administratie_id: null,
    administratie_naam: null,
    vingerafdruk: 'vaf',
    tekst: 'AFWIJKING …',
    titel: 'Vastly-verhuurder niet gekoppeld: B. van Rooijen · 9 facturen',
    wat: '…',
    doe: '…',
    details: [],
    sinds: '2026-09-29T04:30:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: { afwijking_soort: 'vastly_entiteit_niet_gekoppeld', sleutel_soort: 'naam', sleutel: 'b van rooijen', weergave: 'B. van Rooijen', aantal: 9 },
    doel_pad: '/reconciliatie',
    ...overrides,
  } as BevindingDto
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => vi.unstubAllGlobals())

describe('VastlyActies (29-09, herzien 01-10)', () => {
  it('herkent de drie soorten precies op blok + afwijking_soort + sleutelvelden (omzetrekening_ontbreekt is per document)', () => {
    expect(isVastlyEntiteitNietGekoppeld(bevinding())).toBe(true)
    expect(isVastlyEntiteitNietGekoppeld(bevinding({ blok: 'documenten' }))).toBe(false)
    expect(isVastlyOmzetrekeningOntbreekt(bevinding({ administratie_id: 'adm-1', detail: { afwijking_soort: 'vastly_omzetrekening_ontbreekt', document_id: 'doc-1', regelsoort: 'huur' } }))).toBe(true)
    expect(isVastlyOmzetrekeningOntbreekt(bevinding({ administratie_id: 'adm-1', detail: { afwijking_soort: 'vastly_omzetrekening_ontbreekt', regelsoort: 'huur' } }))).toBe(false)
    expect(isVastlyOmzetrekeningOntbreekt(bevinding({ detail: { afwijking_soort: 'vastly_omzetrekening_ontbreekt', document_id: 'doc-1' } }))).toBe(false)
    expect(isVastlyVerkoopNietGeboekt(bevinding({ administratie_id: 'adm-1', detail: { afwijking_soort: 'vastly_verkoop_niet_geboekt', document_id: 'doc-1' } }))).toBe(true)
    expect(isVastlyVerkoopNietGeboekt(bevinding({ administratie_id: 'adm-1', detail: { afwijking_soort: 'vastly_verkoop_niet_geboekt' } }))).toBe(false)
  })

  it('entiteit niet gekoppeld: melden bij Vastly — zonder id, of mét een onbekend id; nooit een koppelknop', () => {
    expect(meldBijVastlyTekst(bevinding())).toContain('geen administratie-id (RLZ-ADMINISTRATIE) en geen bekende KvK')
    expect(meldBijVastlyTekst(bevinding({ detail: { afwijking_soort: 'vastly_entiteit_niet_gekoppeld', sleutel_soort: 'naam', sleutel: 'x', administratie_id_ubl: '00000000-0000-0000-0000-000000000009' } }))).toContain(
      'administratie-id 00000000-0000-0000-0000-000000000009, dat de module niet kent',
    )
    render(<MeldBijVastlyHint bevinding={bevinding()} />)
    expect(screen.getByText(/melden bij Vastly/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.queryByRole('combobox')).toBeNull()
  })

  it('Opnieuw aanbieden: één klik → POST mét administratie; geweigerd = reden zichtbaar; 409 zichtbaar', async () => {
    let antwoord: unknown = { document_id: 'doc-1', administratie_id: 'adm-1', uitkomst: 'geweigerd', reden: 'omzetrekening_ontbreekt: regel 1 (huur): geen grootboekcode (cbc:AccountingCost) in de UBL — melden bij Vastly', doel_pad: '/verkoop/adm-1/doc-1' }
    let status = 200
    const posts: { url: string; body: Record<string, unknown> }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        posts.push({ url, body: JSON.parse(String(init?.body ?? '{}')) as Record<string, unknown> })
        if (status !== 200) return Promise.resolve(jsonResponse({ detail: 'Dit document is geen autoboek-kandidaat' }, status))
        return Promise.resolve(jsonResponse(antwoord))
      }),
    )
    const gebruiker = userEvent.setup()
    const gelukt = vi.fn()
    const b = bevinding({ administratie_id: 'adm-1', detail: { afwijking_soort: 'vastly_omzetrekening_ontbreekt', document_id: 'doc-1', bestandsnaam: 'factuur-RUB-2026-0034-ubl.xml', reden: 'x' } })
    const { unmount } = render(<OpnieuwAanbiedenActie bevinding={b} onGelukt={gelukt} />)
    await gebruiker.click(screen.getByRole('button', { name: 'factuur-RUB-2026-0034-ubl.xml opnieuw aanbieden' }))
    await waitFor(() => expect(gelukt).toHaveBeenCalledTimes(1))
    expect(posts[0].url).toContain('/reconciliatie/vastly/documenten/doc-1/opnieuw-aanbieden')
    expect(posts[0].body).toEqual({ administratie_id: 'adm-1' })
    expect(String(gelukt.mock.calls[0][0])).toContain('nog niet geboekt: omzetrekening_ontbreekt')
    expect(screen.getByText(/niet geboekt — omzetrekening_ontbreekt/)).toBeInTheDocument()
    unmount()
    antwoord = { document_id: 'doc-1', administratie_id: 'adm-1', uitkomst: 'geboekt', reden: null, doel_pad: '/verkoop/adm-1/doc-1' }
    render(<OpnieuwAanbiedenActie bevinding={b} onGelukt={gelukt} />)
    await gebruiker.click(screen.getByRole('button', { name: 'factuur-RUB-2026-0034-ubl.xml opnieuw aanbieden' }))
    expect(await screen.findByText('geboekt')).toBeInTheDocument()
    status = 409
    render(<OpnieuwAanbiedenActie bevinding={b} onGelukt={gelukt} />)
    await gebruiker.click(screen.getAllByRole('button', { name: 'factuur-RUB-2026-0034-ubl.xml opnieuw aanbieden' })[0])
    expect(await screen.findByText(/geen autoboek-kandidaat/)).toBeInTheDocument()
  })
})
