// Inzicht › Open vragen kantoorbreed (design-ronde 03-09 blok B2, mockup inzicht-kantoorbreed.html ④): rendert de
// server-side lijst (vraag vet + subregel, administratie, wacht-chip oranje ≥ 7 dagen), tellers-chips, filters
// sturen de query (toegewezen / ouder dan / administratie-facet), paginering-voet, lege stand en de
// "Beantwoorden →"-deeplink naar het vragen-deelscherm van de klantpagina.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OpenVragenKantoorbreed, subregel, wachtLabel } from './OpenVragenKantoorbreed'
import { openVragenQuery } from './vragenApi'

const ADM_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADM_B = 'bbbbbbbb-0000-0000-0000-000000000002'
const TELLERS = { open: 9, aan_mij: 3, blokkeert_boeken: 8, administraties: 2 }

function rij(over: Record<string, unknown>) {
  return {
    vraag_id: 'v-1',
    document_id: 'd-1',
    administratie_id: ADM_A,
    administratie_naam: 'BWC Steigers B.V.',
    vraag_tekst: 'Is dit privé of zakelijk getankt?',
    laatste_bericht: null,
    laatste_bericht_door: null,
    laatste_bericht_op: null,
    gesteld_door_id: 'g-1',
    gesteld_door_naam: 'Peter',
    gesteld_op: '2026-08-26T10:00:00Z',
    aan_de_beurt_id: 'g-2',
    aan_de_beurt_naam: 'Barbara',
    aan_mij: false,
    wacht_dagen: 8,
    document_bestandsnaam: 'shell.pdf',
    document_status: 'vraag_open',
    leverancier_naam: 'Shell',
    referentie: '04-9284',
    totaalbedrag: '96.20',
    blokkeert_boeken: true,
    ...over,
  }
}

const RIJEN = [
  rij({}),
  rij({
    vraag_id: 'v-2',
    document_id: 'd-2',
    administratie_id: ADM_B,
    administratie_naam: 'Universal Steigerbouw B.V.',
    vraag_tekst: 'Welke kostenplaats voor deze lift?',
    leverancier_naam: 'Riwal',
    referentie: null,
    totaalbedrag: '2140.00',
    aan_mij: true,
    aan_de_beurt_naam: 'Test-Beheerder',
    wacht_dagen: 2,
    laatste_bericht: 'Zie de bon in de mail.',
    laatste_bericht_door: 'Barbara',
    laatste_bericht_op: '2026-09-02T09:00:00Z',
  }),
]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetch(aanroepen: string[], opties: { rijen?: unknown[]; totaal?: number } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.startsWith('/vragen?')) {
        aanroepen.push(url)
        const params = new URL(url, 'http://x').searchParams
        let rijen = opties.rijen ?? RIJEN
        if (params.get('toegewezen') === 'mij') rijen = rijen.filter((r) => (r as { aan_mij: boolean }).aan_mij)
        if (params.get('ouder_dan_dagen')) {
          const n = Number(params.get('ouder_dan_dagen'))
          rijen = rijen.filter((r) => (r as { wacht_dagen: number }).wacht_dagen >= n)
        }
        if (params.get('administratie_id')) {
          rijen = rijen.filter((r) => (r as { administratie_id: string }).administratie_id === params.get('administratie_id'))
        }
        return Promise.resolve(
          json({
            rijen,
            totaal: opties.totaal ?? rijen.length,
            pagina: Number(params.get('pagina') ?? 1),
            per_pagina: 25,
            tellers: TELLERS,
            administraties: [
              { administratie_id: ADM_A, administratie_naam: 'BWC Steigers B.V.', aantal: 1 },
              { administratie_id: ADM_B, administratie_naam: 'Universal Steigerbouw B.V.', aantal: 1 },
            ],
          }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function Locatie() {
  const loc = useLocation()
  return <div data-testid="locatie">{loc.pathname + loc.search}</div>
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/?filter=vragen']}>
      <Routes>
        <Route
          path="/"
          element={
            <>
              <OpenVragenKantoorbreed />
              <Locatie />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

describe('OpenVragenKantoorbreed (blok B2 03-09)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('rendert de rijen uit GET /vragen: vraag vet + subregel, administratie, wacht-chip (oranje ≥ 7 d) en tellers', async () => {
    const aanroepen: string[] = []
    installFetch(aanroepen)
    renderScherm()

    await waitFor(() => expect(screen.getAllByTestId('open-vraag-rij')).toHaveLength(2))
    // Eén server-call, geen fan-out per administratie.
    expect(aanroepen).toEqual(['/vragen?pagina=1'])
    expect(screen.getByRole('heading', { name: 'Inzicht › Open vragen' })).toBeInTheDocument()
    expect(screen.getByTestId('chip-open')).toHaveTextContent('9 open')
    expect(screen.getByTestId('chip-aan-mij')).toHaveTextContent('3 aan mij')

    const [eerste, tweede] = screen.getAllByTestId('open-vraag-rij')
    expect(within(eerste).getByText('“Is dit privé of zakelijk getankt?”')).toBeInTheDocument()
    expect(within(eerste).getByText('Shell · 04-9284 · € 96,20 · aan Barbara')).toBeInTheDocument()
    expect(within(eerste).getByText('BWC Steigers B.V.')).toBeInTheDocument()
    expect(within(eerste).getByText('8 dagen')).toHaveClass('text-warn')
    expect(within(tweede).getByText('Riwal · € 2.140,00 · aan u')).toBeInTheDocument()
    expect(within(tweede).getByText('2 dagen')).toHaveClass('text-muted')
    expect(within(tweede).getByText(/laatste bericht van Barbara/)).toBeInTheDocument()
    expect(screen.getByText(/1 van 1 › · oudste eerst · 9 open over 2 administraties/)).toBeInTheDocument()
  })

  it('"Beantwoorden →" is de primaire (teal) knop en navigeert naar het vragen-deelscherm van de klantpagina', async () => {
    const gebruiker = userEvent.setup()
    installFetch([])
    renderScherm()

    await waitFor(() => expect(screen.getAllByTestId('open-vraag-rij')).toHaveLength(2))
    const knop = screen.getByRole('button', { name: 'Beantwoorden: Welke kostenplaats voor deze lift?' })
    expect(knop).toHaveClass('bg-primary')
    await gebruiker.click(knop)
    expect(screen.getByTestId('locatie')).toHaveTextContent(`/?administratie=${ADM_B}&sectie=vragen&document=d-2`)
  })

  it('filters "Toegewezen" en "Ouder dan" wijzigen de query en zetten de pagina terug op 1', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: string[] = []
    installFetch(aanroepen)
    renderScherm()

    await waitFor(() => expect(screen.getAllByTestId('open-vraag-rij')).toHaveLength(2))
    await gebruiker.selectOptions(screen.getByLabelText('Toegewezen'), 'mij')
    await waitFor(() => expect(aanroepen.at(-1)).toBe('/vragen?pagina=1&toegewezen=mij'))
    await waitFor(() => expect(screen.getAllByTestId('open-vraag-rij')).toHaveLength(1))
    expect(screen.getByText('“Welke kostenplaats voor deze lift?”')).toBeInTheDocument()

    await gebruiker.selectOptions(screen.getByLabelText('Ouder dan'), '7')
    await waitFor(() => expect(aanroepen.at(-1)).toBe('/vragen?pagina=1&toegewezen=mij&ouder_dan_dagen=7'))
    // Niets aan mij én ouder dan 7 dagen → lege stand mét handelingsperspectief (filters wissen).
    await waitFor(() => expect(screen.getByTestId('lege-stand')).toHaveTextContent('Geen open vragen binnen dit filter.'))
    await gebruiker.click(screen.getByRole('button', { name: 'Filters wissen' }))
    await waitFor(() => expect(aanroepen.at(-1)).toBe('/vragen?pagina=1'))
    await waitFor(() => expect(screen.getAllByTestId('open-vraag-rij')).toHaveLength(2))
  })

  it('de administratie-facet is een filter (leeg = alle) en is met "alle" weer te wissen', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: string[] = []
    installFetch(aanroepen)
    renderScherm()

    await waitFor(() => expect(screen.getAllByTestId('open-vraag-rij')).toHaveLength(2))
    const combobox = screen.getByLabelText('Administratie (filter)')
    await gebruiker.click(combobox)
    await gebruiker.type(combobox, 'Universal')
    // De combobox rendert de optie gevirtualiseerd (meetkopie + zichtbare rij) — de eerste optie-rol aanklikken.
    await gebruiker.click((await screen.findAllByRole('option', { name: /Universal Steigerbouw B.V. \(1\)/ }))[0])
    await waitFor(() => expect(aanroepen.at(-1)).toBe(`/vragen?pagina=1&administratie_id=${ADM_B}`))
    await waitFor(() => expect(screen.getAllByTestId('open-vraag-rij')).toHaveLength(1))

    await gebruiker.click(screen.getByRole('button', { name: 'alle' }))
    await waitFor(() => expect(aanroepen.at(-1)).toBe('/vragen?pagina=1'))
  })

  it('lege stand zonder filter: "Geen open vragen — nergens."', async () => {
    installFetch([], { rijen: [] })
    renderScherm()
    await waitFor(() => expect(screen.getByTestId('lege-stand')).toHaveTextContent('Geen open vragen — nergens.'))
    expect(screen.queryByRole('button', { name: 'Filters wissen' })).not.toBeInTheDocument()
  })

  it('paginering verschijnt boven 25 rijen en de voet toont "n van m"', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: string[] = []
    installFetch(aanroepen, { totaal: 60 })
    renderScherm()

    await waitFor(() => expect(screen.getByText(/1 van 3 › · oudste eerst/)).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Volgende pagina' }))
    await waitFor(() => expect(aanroepen.at(-1)).toBe('/vragen?pagina=2'))
    await waitFor(() => expect(screen.getByText(/2 van 3 › · oudste eerst/)).toBeInTheDocument())
  })

  it('fout bij laden = FoutMelding mét opnieuw-knop, geen kale string', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('kapot', { status: 500 }))))
    renderScherm()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('De open vragen konden niet geladen worden.'))
    expect(screen.getByRole('button', { name: /Opnieuw/ })).toBeInTheDocument()
  })
})

describe('helpers', () => {
  it('wachtLabel en subregel', () => {
    expect(wachtLabel(0)).toBe('vandaag')
    expect(wachtLabel(1)).toBe('1 dag')
    expect(wachtLabel(8)).toBe('8 dagen')
    expect(subregel(rij({ leverancier_naam: null, referentie: null, totaalbedrag: null }) as never)).toBe('shell.pdf · aan Barbara')
  })

  it('openVragenQuery laat defaults weg en trimt de zoekterm', () => {
    expect(openVragenQuery({})).toBe('pagina=1')
    expect(openVragenQuery({ pagina: 2, toegewezen: 'alle', q: '  ' })).toBe('pagina=2')
    expect(openVragenQuery({ toegewezen: 'mij', ouderDanDagen: 0, administratieId: ADM_A, q: ' lift ' })).toBe(
      `pagina=1&administratie_id=${ADM_A}&toegewezen=mij&ouder_dan_dagen=0&q=lift`,
    )
  })
})
