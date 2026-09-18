// Peter 17-09: leveranciersroute — lijst mét samenvatting, editor (naam, leveranciers als chips, lagen), 409-tekst letterlijk,
// route uitzetten; niet-Beheerder ziet alleen de lijst.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LeverancierRoutes } from './LeverancierRoutes'
import type { LeverancierRouteDto } from '../accordering/accorderingApi'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ROUTE: LeverancierRouteDto = {
  id: 'r1',
  naam: 'Route Q',
  actief: true,
  leveranciers: [{ vendor_id: 'v-q', naam: 'Firma Q B.V.' }],
  lagen: [
    { volgnummer: 1, accordeur_gebruiker_id: 'g-sophia', accordeur_naam: 'Sophia', bedrag_drempel: null },
    { volgnummer: 2, accordeur_gebruiker_id: 'g-dir', accordeur_naam: 'D. Directeur', bedrag_drempel: '5000.00' },
  ],
  samenvatting: 'laag 1 Sophia → laag 2 D. Directeur · > € 5.000,00 · alleen Firma Q B.V.',
}

function stub(state: { routes: LeverancierRouteDto[]; posts: unknown[]; conflict?: string }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
      const pad = String(invoer).split('?')[0]
      if (pad === '/administraties/a1/accordering/leverancier-routes' && (!init?.method || init.method === 'GET'))
        return Promise.resolve(jsonResponse({ routes: state.routes }))
      if (pad === '/administraties/a1/accordering/leverancier-routes' && init?.method === 'POST') {
        state.posts.push(JSON.parse(String(init.body)))
        if (state.conflict) return Promise.resolve(jsonResponse({ detail: state.conflict }, 409))
        return Promise.resolve(jsonResponse({ routes: [...state.routes, ROUTE], rondes_herberekend: 1, rondes_vervallen: 0 }, 201))
      }
      if (pad === '/administraties/a1/accordering/leverancier-routes/r1' && init?.method === 'DELETE')
        return Promise.resolve(jsonResponse({ routes: [], rondes_herberekend: 1, rondes_vervallen: 0 }))
      return Promise.resolve(jsonResponse({ detail: `onbekend pad ${pad}` }, 404))
    }),
  )
}

const KANDIDATEN = [
  { id: 'g-sophia', naam: 'Sophia' },
  { id: 'g-dir', naam: 'D. Directeur' },
]
const CREDITEUREN = [
  { id: 'v-q', naam: 'Firma Q B.V.' },
  { id: 'v-r', naam: 'Firma R B.V.' },
]

afterEach(() => vi.unstubAllGlobals())

/** Leverancierskeuze is sinds 18-09 een zoekbare combobox (open documenten bovenaan): typen → optie kiezen. */
async function kiesLeverancier(naam: string) {
  const invoer = screen.getByRole('combobox', { name: 'leverancier' })
  await userEvent.click(invoer)
  await userEvent.type(invoer, naam.slice(0, 5))
  await userEvent.click(await screen.findByRole('option', { name: new RegExp(naam.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }))
}

describe('LeverancierRoutes', () => {
  it('toont de lege stand als actie en de samenvatting per route', async () => {
    stub({ routes: [], posts: [] })
    const eerste = render(<LeverancierRoutes administratieId="a1" kandidaten={KANDIDATEN} crediteuren={CREDITEUREN} isBeheerder />)
    await screen.findByText('Nog geen leveranciersroute — alle facturen volgen de gewone route.')
    expect(screen.getByRole('button', { name: '+ Leveranciersroute' })).toBeInTheDocument()
    eerste.unmount()
    stub({ routes: [ROUTE], posts: [] })
    render(<LeverancierRoutes administratieId="a1" kandidaten={KANDIDATEN} crediteuren={CREDITEUREN} isBeheerder={false} />)
    await screen.findByText(/alleen Firma Q B.V./)
    expect(screen.queryByRole('button', { name: 'Wijzigen' })).not.toBeInTheDocument()
  })

  it('maakt een route mét leverancier-chips en lagen en toont de rondes-telling', async () => {
    const state = { routes: [] as LeverancierRouteDto[], posts: [] as unknown[] }
    stub(state)
    render(<LeverancierRoutes administratieId="a1" kandidaten={KANDIDATEN} crediteuren={CREDITEUREN} isBeheerder />)
    await screen.findByRole('button', { name: '+ Leveranciersroute' })
    await userEvent.click(screen.getByRole('button', { name: '+ Leveranciersroute' }))
    await userEvent.type(screen.getByLabelText('Naam leveranciersroute'), 'Route Q')
    await kiesLeverancier('Firma Q B.V.')
    expect(screen.getByTestId('leverancier-chip')).toHaveTextContent('Firma Q B.V.')
    await userEvent.selectOptions(screen.getByLabelText('Accordeur route-laag 1'), 'g-sophia')
    await userEvent.click(screen.getByRole('button', { name: '+ Laag toevoegen' }))
    await userEvent.selectOptions(screen.getByLabelText('Accordeur route-laag 2'), 'g-dir')
    await userEvent.type(screen.getByLabelText('Bedragdrempel route-laag 2'), '5000')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(state.posts).toHaveLength(1))
    expect(state.posts[0]).toEqual({
      naam: 'Route Q',
      vendor_ids: ['v-q'],
      modus: 'vervangt',
      positie: null,
      lagen: [
        { volgnummer: 1, accordeur_gebruiker_id: 'g-sophia', bedrag_drempel: null },
        { volgnummer: 2, accordeur_gebruiker_id: 'g-dir', bedrag_drempel: '5000' },
      ],
    })
    await screen.findByText(/alleen Firma Q B.V./)
    expect(screen.getByText(/Opgeslagen\./)).toBeInTheDocument()
  })

  it('toont de 409-reden letterlijk en zet een route uit ná bevestiging', async () => {
    const state = { routes: [ROUTE], posts: [] as unknown[], conflict: "Leverancier 'Firma Q B.V.' zit al in leveranciersroute 'Route Q' — een leverancier kan in maar één route zitten (haal 'm daar eerst uit)" }
    stub(state)
    vi.stubGlobal('confirm', vi.fn(() => true))
    render(<LeverancierRoutes administratieId="a1" kandidaten={KANDIDATEN} crediteuren={CREDITEUREN} isBeheerder />)
    await screen.findByText(/alleen Firma Q B.V./)
    await userEvent.click(screen.getByRole('button', { name: '+ Leveranciersroute' }))
    await userEvent.type(screen.getByLabelText('Naam leveranciersroute'), 'Route 2')
    await kiesLeverancier('Firma Q B.V.')
    await userEvent.selectOptions(screen.getByLabelText('Accordeur route-laag 1'), 'g-dir')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await screen.findByText(/zit al in leveranciersroute 'Route Q'/)
    await userEvent.click(screen.getByRole('button', { name: 'Annuleren' }))
    await userEvent.click(screen.getByRole('button', { name: 'Route uitzetten' }))
    await screen.findByText('Nog geen leveranciersroute — alle facturen volgen de gewone route.')
    expect(screen.getByText(/Route uitgezet\./)).toBeInTheDocument()
  })

  it('kiest "Bovenop de gewone route" mét positie, toont de chip en meldt ontbrekende accordeurs mét twee acties (Peter 18-09)', async () => {
    const state = { routes: [] as LeverancierRouteDto[], posts: [] as unknown[] }
    stub(state)
    render(<LeverancierRoutes administratieId="a1" naam="Bouwadvies Oost Nederland B.V." kandidaten={[]} crediteuren={CREDITEUREN} isBeheerder />)
    await userEvent.click(await screen.findByRole('button', { name: '+ Leveranciersroute' }))
    // Geen accordeurs in de administratie → dezelfde melding + acties als op de kaart.
    const melding = screen.getByTestId('geen-accordeurs-melding')
    expect(melding.querySelector('[data-testid="accordeur-uitnodigen"]')).toHaveAttribute(
      'href',
      '/gebruikers?groep=accordeurs&uitnodig=accordeur&administratie=a1',
    )
    expect(melding.querySelector('[data-testid="accordeur-koppelen"]')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Naam leveranciersroute'), 'Directie extra')
    await kiesLeverancier('Firma R B.V.')
    await userEvent.click(screen.getByLabelText('Bovenop de gewone route'))
    expect(screen.getByLabelText('Extra laag ná de laatste laag')).toBeChecked()
    await userEvent.click(screen.getByLabelText('Extra laag vóór laag 1'))
    expect(screen.getByText('Extra laag 1')).toBeInTheDocument()
    // Zonder accordeur-keuze blijft opslaan mogelijk qua knop (lagen leeg → server weigert); hier alleen de payload-vorm.
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(state.posts).toHaveLength(1))
    expect(state.posts[0]).toMatchObject({ naam: 'Directie extra', vendor_ids: ['v-r'], modus: 'bovenop', positie: 'voor' })
  })

  it('toont bij een bovenop-route de chip "bovenop de gewone route"', async () => {
    stub({ routes: [{ ...ROUTE, modus: 'bovenop', positie: 'na', samenvatting: 'bovenop de gewone route (ná de laatste laag): + laag 1 Sophia · alleen Firma Q B.V.' }], posts: [] })
    render(<LeverancierRoutes administratieId="a1" kandidaten={KANDIDATEN} crediteuren={CREDITEUREN} isBeheerder={false} />)
    expect(await screen.findByTestId('route-modus-chip')).toHaveTextContent('bovenop de gewone route')
    expect(screen.getByText(/ná de laatste laag/)).toBeInTheDocument()
  })
})
