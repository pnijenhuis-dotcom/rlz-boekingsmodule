import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BevindingDto } from './reconciliatieApi'
import {
  isVastlyEntiteitNietGekoppeld,
  isVastlyOmzetrekeningOntbreekt,
  isVastlyVerkoopNietGeboekt,
  KoppelEntiteitActie,
  koppelMelding,
  OpnieuwAanbiedenActie,
  RekeningKiezenActie,
} from './VastlyActies'

// 29-09 (Peter 28-09): Vastly-verkoop volledig automatisch — de drie bevindingen mét handeling in blok `vastly_verkoop`.

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

describe('VastlyActies (29-09)', () => {
  it('herkent de drie soorten precies op blok + afwijking_soort + sleutelvelden', () => {
    expect(isVastlyEntiteitNietGekoppeld(bevinding())).toBe(true)
    expect(isVastlyEntiteitNietGekoppeld(bevinding({ blok: 'documenten' }))).toBe(false)
    expect(isVastlyOmzetrekeningOntbreekt(bevinding({ administratie_id: 'adm-1', detail: { afwijking_soort: 'vastly_omzetrekening_ontbreekt', regelsoort: 'huur' } }))).toBe(true)
    expect(isVastlyOmzetrekeningOntbreekt(bevinding({ detail: { afwijking_soort: 'vastly_omzetrekening_ontbreekt', regelsoort: 'huur' } }))).toBe(false)
    expect(isVastlyVerkoopNietGeboekt(bevinding({ administratie_id: 'adm-1', detail: { afwijking_soort: 'vastly_verkoop_niet_geboekt', document_id: 'doc-1' } }))).toBe(true)
    expect(isVastlyVerkoopNietGeboekt(bevinding({ administratie_id: 'adm-1', detail: { afwijking_soort: 'vastly_verkoop_niet_geboekt' } }))).toBe(false)
  })

  it('koppelMelding: alles geboekt / deels / niets wachtend', () => {
    const basis = { sleutel_soort: 'naam', sleutel: 'x', administratie_id: 'a', administratie_naam: 'B. van Rooijen / G. Schaalje', doel_pad: '/' }
    expect(koppelMelding({ ...basis, documenten: 9, per_uitkomst: { geboekt: 9 } })).toContain('9 facturen zijn direct automatisch als omzet geboekt')
    expect(koppelMelding({ ...basis, documenten: 9, per_uitkomst: { geboekt: 7, geweigerd: 2 } })).toContain('7 van 9 facturen direct geboekt; 2 wacht(en) nog')
    expect(koppelMelding({ ...basis, documenten: 0, per_uitkomst: {} })).toContain('geen facturen meer')
  })

  it('Koppel aan administratie…: kiezen + één klik → POST mét sleutel en administratie, melding mét telling', async () => {
    const posts: Record<string, unknown>[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/auth/administraties')) {
          return Promise.resolve(jsonResponse({ administraties: [{ id: 'adm-1', naam: 'B. van Rooijen / G. Schaalje' }, { id: 'adm-2', naam: 'Rubicon Investments B.V.' }] }))
        }
        if (url.endsWith('/reconciliatie/vastly/entiteit-koppelen')) {
          posts.push(JSON.parse(String(init?.body)) as Record<string, unknown>)
          return Promise.resolve(jsonResponse({ sleutel_soort: 'naam', sleutel: 'b van rooijen', administratie_id: 'adm-1', administratie_naam: 'B. van Rooijen / G. Schaalje', documenten: 9, per_uitkomst: { geboekt: 9 }, doel_pad: '/administraties/adm-1' }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const gebruiker = userEvent.setup()
    const gelukt = vi.fn()
    render(
      <MemoryRouter>
        <KoppelEntiteitActie bevinding={bevinding()} onGelukt={gelukt} />
      </MemoryRouter>,
    )
    const knop = await screen.findByRole('button', { name: /Koppel B\. van Rooijen aan de gekozen administratie/ })
    expect(knop).toBeDisabled()
    const combobox = await screen.findByLabelText('Administratie voor B. van Rooijen')
    await gebruiker.click(combobox)
    await gebruiker.type(combobox, 'Rooijen')
    await gebruiker.click(await screen.findByRole('option', { name: 'B. van Rooijen / G. Schaalje' }))
    await waitFor(() => expect(knop).toBeEnabled())
    await gebruiker.click(knop)
    await waitFor(() => expect(gelukt).toHaveBeenCalledTimes(1))
    expect(posts).toEqual([{ sleutel_soort: 'naam', sleutel: 'b van rooijen', administratie_id: 'adm-1', weergave: 'B. van Rooijen' }])
    expect(String(gelukt.mock.calls[0][0])).toContain('9 facturen zijn direct automatisch als omzet geboekt')
    expect(screen.getByText(/gekoppeld aan B\. van Rooijen \/ G\. Schaalje — 9 geboekt/)).toBeInTheDocument()
  })

  it('Rekening kiezen: laadt de keuzelijst van de administratie en doet een PUT (Beheerder; 422 zichtbaar)', async () => {
    const puts: Record<string, unknown>[] = []
    let status = 200
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/administraties/adm-1/vastly-instellingen')) {
          return Promise.resolve(jsonResponse({ administratie_id: 'adm-1', omzetrekeningen: [], entiteiten: [], keuzelijst: [{ ledger_id: 'l-8000', code: '8000', naam: 'Huuropbrengsten' }, { ledger_id: 'l-8100', code: '8100', naam: 'Servicekosten' }] }))
        }
        if (url.endsWith('/administraties/adm-1/vastly-omzetrekeningen') && init?.method === 'PUT') {
          puts.push(JSON.parse(String(init.body)) as Record<string, unknown>)
          if (status !== 200) return Promise.resolve(jsonResponse({ detail: 'de gekozen rekening is geen actieve omzetrekening' }, status))
          return Promise.resolve(jsonResponse({ regelsoort: 'huur', ledger_id: 'l-8000', code: '8000', naam: 'Huuropbrengsten', bron: 'mens' }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const gebruiker = userEvent.setup()
    const gelukt = vi.fn()
    const b = bevinding({ administratie_id: 'adm-1', administratie_naam: 'Rubicon', detail: { afwijking_soort: 'vastly_omzetrekening_ontbreekt', regelsoort: 'huur', aantal: 3 } })
    const { unmount } = render(<RekeningKiezenActie bevinding={b} onGelukt={gelukt} />)
    const combobox = await screen.findByLabelText('Omzetrekening voor huur')
    await gebruiker.click(combobox)
    await gebruiker.type(combobox, 'Huur')
    await gebruiker.click(await screen.findByRole('option', { name: /Huuropbrengsten/ }))
    const knop = screen.getByRole('button', { name: 'Omzetrekening voor huur kiezen' })
    await waitFor(() => expect(knop).toBeEnabled())
    await gebruiker.click(knop)
    await waitFor(() => expect(gelukt).toHaveBeenCalledTimes(1))
    expect(puts).toEqual([{ regelsoort: 'huur', ledger_id: 'l-8000' }])
    expect(screen.getByText(/huur → 8000 Huuropbrengsten/)).toBeInTheDocument()
    unmount()
    // 422 = zichtbaar naast de knop, nooit stil.
    status = 422
    render(<RekeningKiezenActie bevinding={b} onGelukt={gelukt} />)
    const combobox2 = await screen.findByLabelText('Omzetrekening voor huur')
    await gebruiker.click(combobox2)
    await gebruiker.type(combobox2, 'Huur')
    await gebruiker.click(await screen.findByRole('option', { name: /Huuropbrengsten/ }))
    await gebruiker.click(screen.getByRole('button', { name: 'Omzetrekening voor huur kiezen' }))
    expect(await screen.findByText(/geen actieve omzetrekening/)).toBeInTheDocument()
  })

  it('Opnieuw aanbieden: één klik → POST mét administratie; geweigerd = reden zichtbaar; 409 zichtbaar', async () => {
    let antwoord: unknown = { document_id: 'doc-1', administratie_id: 'adm-1', uitkomst: 'geweigerd', reden: 'harde checks blokkeren — duplicaat', doel_pad: '/verkoop/adm-1/doc-1' }
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
    const b = bevinding({ administratie_id: 'adm-1', detail: { afwijking_soort: 'vastly_verkoop_niet_geboekt', document_id: 'doc-1', bestandsnaam: 'factuur-RUB-2026-0034-ubl.xml', reden: 'x' } })
    const { unmount } = render(<OpnieuwAanbiedenActie bevinding={b} onGelukt={gelukt} />)
    await gebruiker.click(screen.getByRole('button', { name: 'factuur-RUB-2026-0034-ubl.xml opnieuw aanbieden' }))
    await waitFor(() => expect(gelukt).toHaveBeenCalledTimes(1))
    expect(posts[0].url).toContain('/reconciliatie/vastly/documenten/doc-1/opnieuw-aanbieden')
    expect(posts[0].body).toEqual({ administratie_id: 'adm-1' })
    expect(String(gelukt.mock.calls[0][0])).toContain('nog niet geboekt: harde checks blokkeren — duplicaat')
    expect(screen.getByText(/niet geboekt — harde checks/)).toBeInTheDocument()
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
