// Bulk-afvoer op de Mogelijk-duplicaat-tab (B2 07-09): checkbox-kolom alleen op die tab, kop-checkbox = zichtbare
// rijen, "alle N op deze tab" (server-side `alle: true`), knop mét teller, Radix-bevestigingsdialoog mét aantal,
// uitkomst-paneel (afgevoerd / overgeslagen mét redenen uitklapbaar) en herladen van de lijst.

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WerkvoorraadScreen } from './WerkvoorraadScreen'

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'
const BULK_PAD = `/administraties/${ADMIN}/documenten/duplicaten/afvoeren-bulk`

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function doc(overrides: Record<string, unknown>) {
  return {
    id: 'bbbbbbbb-0000-0000-0000-000000000002',
    bestandsnaam: 'factuur.pdf',
    soort: 'inkoopfactuur',
    status: 'te_controleren',
    bron: 'upload',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-09-04T10:00:00Z',
    laatst_gewijzigd_op: '2026-09-04T10:00:00Z',
    automatisch_geboekt: false,
    afwijzing: null,
    leverancier: null,
    totaalbedrag: null,
    factuurdatum: null,
    duplicaatsignaal: { uitkomst: 'mogelijk_duplicaat', aantal_treffers: 1, berekend_op: '2026-09-04T10:00:00Z' },
    ...overrides,
  }
}

const DUP_A = doc({ id: 'd-a', bestandsnaam: 'a.pdf', leverancier: 'Alfa BV' })
const DUP_B = doc({ id: 'd-b', bestandsnaam: 'b.pdf', leverancier: 'Beta BV' })
const DUP_C = doc({ id: 'd-c', bestandsnaam: 'c.pdf', leverancier: 'Gamma BV' })
const GEBOEKT = doc({ id: 'd-geboekt', bestandsnaam: 'geboekt.pdf', leverancier: 'Delta BV', status: 'geboekt' })
const SCHOON = doc({ id: 'd-schoon', bestandsnaam: 'schoon.pdf', leverancier: 'Epsilon BV', duplicaatsignaal: null })

/** fetch-stub: GET-lijst (telt de ladingen), POST bulk (legt de body vast). Alles anders 404 (verrijking = stil). */
function installFetch(documenten: unknown[], bulkAntwoord: unknown) {
  const posts: unknown[] = []
  let lijstLadingen = 0
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMIN, naam: 'Kempen Facilities B.V.' }] }))
      }
      if (url.endsWith(BULK_PAD) && init?.method === 'POST') {
        posts.push(JSON.parse(String(init.body)))
        return Promise.resolve(jsonResponse(bulkAntwoord))
      }
      if (url.includes(`/administraties/${ADMIN}/documenten`) && (!init || init.method === undefined)) {
        lijstLadingen += 1
        return Promise.resolve(jsonResponse({ documenten }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return { posts, ladingen: () => lijstLadingen }
}

function renderTab(status = '__mogelijk_duplicaat') {
  return render(
    <MemoryRouter initialEntries={[`/?administratie=${ADMIN}&status=${status}`]}>
      <WerkvoorraadScreen />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Mogelijk-duplicaat-tab — bulk afvoeren', () => {
  it('checkbox per afvoerbare rij, geboekte rij uitgeschakeld mét reden; kop-checkbox selecteert de pagina; knop telt', async () => {
    installFetch([DUP_A, DUP_B, DUP_C, GEBOEKT], { resultaten: [], geselecteerd: 0, afgevoerd: 0, al_afgevoerd: 0, overgeslagen: 0 })
    renderTab()
    await waitFor(() => expect(screen.getByText('Alfa BV')).toBeInTheDocument())

    const balk = screen.getByTestId('duplicaat-bulk-balk')
    expect(balk).toHaveTextContent('3 afvoerbaar')
    const knop = within(balk).getByRole('button', { name: 'Afvoeren als duplicaat' })
    expect(knop).toBeDisabled()

    // Geboekt: staat op de tab (signaal), maar niet selecteerbaar — checkbox uit mét uitleg, geen stil verdwijnen.
    const geboektCb = screen.getByRole('checkbox', { name: /Delta BV: Vanuit status "geboekt"/ })
    expect(geboektCb).toBeDisabled()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Selecteer Alfa BV voor afvoeren als duplicaat' }))
    expect(within(balk).getByRole('button', { name: 'Afvoeren als duplicaat (1)' })).toBeEnabled()
    expect(balk).toHaveTextContent('1 van 3 geselecteerd')

    await userEvent.click(within(balk).getByRole('checkbox', { name: 'Alle zichtbare duplicaten selecteren' }))
    expect(within(balk).getByRole('button', { name: 'Afvoeren als duplicaat (3)' })).toBeEnabled()
    // Geen banner: alles op de tab is al zichtbaar geselecteerd.
    expect(screen.queryByTestId('duplicaat-bulk-alle-banner')).not.toBeInTheDocument()
  })

  it('bevestigingsdialoog mét aantal → POST document_ids → uitkomst-paneel mét redenen uitklapbaar + lijst herladen', async () => {
    const stub = installFetch([DUP_A, DUP_B, GEBOEKT], {
      resultaten: [
        { document_id: 'd-a', bestandsnaam: 'a.pdf', uitkomst: 'afgevoerd', reden: 'Duplicaat van F-1 (boekstuk INK-7)', origineel: null },
        {
          document_id: 'd-b',
          bestandsnaam: 'b.pdf',
          uitkomst: 'overgeslagen',
          reden: 'Geen harde duplicaat-match (meer): crediteur, referentie en totaalbedrag komen niet alle drie overeen',
          origineel: null,
        },
      ],
      geselecteerd: 2,
      afgevoerd: 1,
      al_afgevoerd: 0,
      overgeslagen: 1,
    })
    renderTab()
    await waitFor(() => expect(screen.getByText('Alfa BV')).toBeInTheDocument())
    const ladingenVoor = stub.ladingen()

    const balk = screen.getByTestId('duplicaat-bulk-balk')
    await userEvent.click(within(balk).getByRole('checkbox', { name: 'Alle zichtbare duplicaten selecteren' }))
    await userEvent.click(within(balk).getByRole('button', { name: 'Afvoeren als duplicaat (2)' }))

    const dialoog = await screen.findByTestId('duplicaat-bulk-dialoog')
    expect(dialoog).toHaveTextContent('Afvoeren als duplicaat — 2 documenten')
    expect(dialoog).toHaveTextContent('terughalen kan per document via Heropenen')
    expect(stub.posts).toHaveLength(0) // niets vóór de bevestiging
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Afvoeren als duplicaat (2)' }))

    await waitFor(() => expect(stub.posts).toHaveLength(1))
    expect(stub.posts[0]).toEqual({ document_ids: ['d-a', 'd-b'] })

    const paneel = await screen.findByTestId('duplicaat-bulk-resultaat')
    expect(paneel).toHaveTextContent('1 afgevoerd als duplicaat, 1 overgeslagen.')
    await userEvent.click(within(paneel).getByText('Redenen (1 overgeslagen)'))
    expect(paneel).toHaveTextContent('b.pdf: Geen harde duplicaat-match (meer)')
    await waitFor(() => expect(stub.ladingen()).toBeGreaterThan(ladingenVoor))
    expect(screen.queryByTestId('duplicaat-bulk-dialoog')).not.toBeInTheDocument()
  })

  it('zoekterm verbergt rijen → banner "Alle N op deze tab" → server-side alle: true', async () => {
    const stub = installFetch([DUP_A, DUP_B, DUP_C], { resultaten: [], geselecteerd: 3, afgevoerd: 3, al_afgevoerd: 0, overgeslagen: 0 })
    renderTab()
    await waitFor(() => expect(screen.getByText('Alfa BV')).toBeInTheDocument())

    await userEvent.type(screen.getByRole('textbox', { name: 'Zoek in documenten' }), 'Alfa')
    await waitFor(() => expect(screen.queryByText('Beta BV')).not.toBeInTheDocument())

    const balk = screen.getByTestId('duplicaat-bulk-balk')
    expect(balk).toHaveTextContent('1 afvoerbaar zichtbaar, 3 op deze tab')
    await userEvent.click(within(balk).getByRole('checkbox', { name: 'Alle zichtbare duplicaten selecteren' }))
    expect(within(balk).getByRole('button', { name: 'Afvoeren als duplicaat (1)' })).toBeEnabled()

    const banner = screen.getByTestId('duplicaat-bulk-alle-banner')
    await userEvent.click(within(banner).getByRole('button', { name: 'Alle 3 afvoerbare documenten op deze tab selecteren' }))
    expect(within(balk).getByRole('button', { name: 'Afvoeren als duplicaat (3)' })).toBeEnabled()
    expect(balk).toHaveTextContent('Alle 3 afvoerbare documenten op deze tab geselecteerd')

    await userEvent.click(within(balk).getByRole('button', { name: 'Afvoeren als duplicaat (3)' }))
    const dialoog = await screen.findByTestId('duplicaat-bulk-dialoog')
    expect(dialoog).toHaveTextContent('Alle 3 afvoerbare documenten op de tab "Mogelijk duplicaat"')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Afvoeren als duplicaat (3)' }))
    await waitFor(() => expect(stub.posts).toEqual([{ alle: true }]))
  })

  it('annuleren in de dialoog doet niets; buiten de duplicaat-tab geen selectiekolom of balk', async () => {
    const stub = installFetch([DUP_A, SCHOON], { resultaten: [], geselecteerd: 0, afgevoerd: 0, al_afgevoerd: 0, overgeslagen: 0 })
    renderTab()
    await waitFor(() => expect(screen.getByText('Alfa BV')).toBeInTheDocument())
    const balk = screen.getByTestId('duplicaat-bulk-balk')
    await userEvent.click(within(balk).getByRole('checkbox', { name: 'Alle zichtbare duplicaten selecteren' }))
    await userEvent.click(within(balk).getByRole('button', { name: 'Afvoeren als duplicaat (1)' }))
    const dialoog = await screen.findByTestId('duplicaat-bulk-dialoog')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Annuleren' }))
    await waitFor(() => expect(screen.queryByTestId('duplicaat-bulk-dialoog')).not.toBeInTheDocument())
    expect(stub.posts).toHaveLength(0)

    // Naar het filter "Alle": de duplicaat-bulk verdwijnt, de gewone rijen hebben geen checkbox.
    await userEvent.click(screen.getByRole('button', { name: /^Alle \(2\)/ }))
    await waitFor(() => expect(screen.queryByTestId('duplicaat-bulk-balk')).not.toBeInTheDocument())
    expect(screen.queryByRole('checkbox', { name: /voor afvoeren als duplicaat/ })).not.toBeInTheDocument()
  })
})
