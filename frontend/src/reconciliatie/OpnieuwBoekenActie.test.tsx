import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isVerdwenenDocument, OpnieuwBoekenActie } from './OpnieuwBoekenActie'
import type { BevindingDto } from './reconciliatieApi'

// A11 (07-09): "Opnieuw boeken…" op een documenten-afwijking `ontbreekt_in_rlz`/`ontbreekt_in_odoo` — teal knop,
// bevestigingsdialoog mét leverancier/factuurnummer en VERPLICHTE reden (≥ 5 tekens), POST naar het endpoint,
// daarna de melding + de link "Nu boeken →" naar het controlescherm; een serverfout blijft zichtbaar.
// Aangifte-poort (correctie Peter 07-09): 409 met code `btw_mogelijk_aangegeven` → melding + periode in de dialoog; alleen een
// Beheerder krijgt de tweede stap (bevestigings-checkbox + verplichte reden) en de herhaalde POST draagt de vlag + reden.

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

  const BTW_409 = {
    detail: {
      code: 'btw_mogelijk_aangegeven',
      bericht:
        'Btw mogelijk al aangegeven — suppletie-pad: de boekdatum van de verdwenen boeking valt in een ingediende btw-aangifte; opnieuw boeken zou de voorbelasting opnieuw claimen (boekdatum 2026-06-22 valt in de ingediende btw-aangifte 2026-04-01 t/m 2026-06-30). Alleen een Beheerder kan doorzetten, met de bevestiging dat de btw van dit document NIET in de ingediende aangifte zat (verplichte reden; komt in tijdlijn en audit).',
      soort: 'ingediende_periode',
      boekdatum: '2026-06-22',
      periode_start: '2026-04-01',
      periode_eind: '2026-06-30',
      backend: 'rlz',
      bevestiging_mogelijk: true,
      bevestiging_rol: 'beheerder',
    },
  }

  it('aangifte-poort 409: toont de melding + periode; een niet-Beheerder krijgt GEEN bevestigingsstap en kan niet doorzetten', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(jsonResponse(BTW_409, 409)))
    vi.stubGlobal('fetch', fetchMock)
    const onGelukt = vi.fn()
    render(
      <MemoryRouter>
        <OpnieuwBoekenActie bevinding={bevinding()} onGelukt={onGelukt} isBeheerder={false} />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /^Opnieuw boeken/ }))
    await userEvent.type(await screen.findByLabelText('Reden'), 'document verdwenen na kliktest')
    await userEvent.click(screen.getByRole('button', { name: 'Terug naar klaar om te boeken' }))
    const blok = await screen.findByTestId('btw-blokkade')
    expect(blok).toHaveTextContent(/suppletie-pad/)
    expect(blok).toHaveTextContent('22-06-2026')
    expect(blok).toHaveTextContent('01-04-2026 t/m 30-06-2026 (ingediend)')
    expect(blok).toHaveTextContent(/Alleen een Beheerder kan dit doorzetten/)
    expect(screen.queryByRole('checkbox')).toBeNull()
    // De knop is nu de bevestig-variant maar blijft voor deze rol uitgeschakeld; de dialoog blijft open.
    expect(screen.getByRole('button', { name: 'Bevestig en zet terug naar klaar om te boeken' })).toBeDisabled()
    expect(screen.getByTestId('opnieuw-boeken-dialoog')).toBeInTheDocument()
    expect(onGelukt).not.toHaveBeenCalled()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('aangifte-poort 409: een Beheerder bevestigt (checkbox + reden ≥ 5) en de herhaalde POST draagt vlag + reden', async () => {
    const aangeroepen: { body: Record<string, unknown> }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {}
        aangeroepen.push({ body })
        if (body.btw_niet_in_aangifte_bevestigd === true) {
          return Promise.resolve(
            jsonResponse({ document_id: 'doc-1', status: 'klaar_om_te_boeken', boek_cyclus: 1, doel_pad: `/?administratie=${ADMIN}&document=doc-1` }),
          )
        }
        return Promise.resolve(jsonResponse(BTW_409, 409))
      }),
    )
    const onGelukt = vi.fn()
    render(
      <MemoryRouter>
        <OpnieuwBoekenActie bevinding={bevinding()} onGelukt={onGelukt} isBeheerder />
      </MemoryRouter>,
    )
    await userEvent.click(screen.getByRole('button', { name: /^Opnieuw boeken/ }))
    await userEvent.type(await screen.findByLabelText('Reden'), 'document verdwenen na kliktest')
    await userEvent.click(screen.getByRole('button', { name: 'Terug naar klaar om te boeken' }))
    await screen.findByTestId('btw-blokkade')
    const knop = screen.getByRole('button', { name: 'Bevestig en zet terug naar klaar om te boeken' })
    expect(knop).toBeDisabled()
    // Stap 2: checkbox aanvinken → reden-veld verschijnt; pas met ≥ 5 tekens is de knop actief.
    const vink = screen.getByRole('checkbox', { name: /Ik bevestig: de btw van dit document zat NIET in de ingediende aangifte/ })
    expect(screen.queryByLabelText('Reden van de bevestiging')).toBeNull()
    await userEvent.click(vink)
    const bevestigingReden = screen.getByLabelText('Reden van de bevestiging')
    expect(knop).toBeDisabled()
    await userEvent.type(bevestigingReden, 'ok')
    expect(knop).toBeDisabled()
    await userEvent.type(bevestigingReden, ' — aangifte Q2 gecontroleerd, document zat er niet in')
    expect(knop).toBeEnabled()
    await userEvent.click(knop)
    await waitFor(() => expect(onGelukt).toHaveBeenCalled())
    expect(aangeroepen).toHaveLength(2)
    expect(aangeroepen[0].body).not.toHaveProperty('btw_niet_in_aangifte_bevestigd')
    expect(aangeroepen[1].body).toMatchObject({
      administratie_id: ADMIN,
      reden: 'document verdwenen na kliktest',
      btw_niet_in_aangifte_bevestigd: true,
    })
    expect(String(aangeroepen[1].body.bevestiging_reden)).toMatch(/aangifte Q2 gecontroleerd/)
    expect(screen.queryByTestId('opnieuw-boeken-dialoog')).toBeNull()
    expect(screen.getByRole('link', { name: /Naar het document om opnieuw te boeken/ })).toBeInTheDocument()
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
