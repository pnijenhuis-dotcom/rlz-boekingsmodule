import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccorderingSectie } from './AccorderingSectie'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function stap(overrides: Record<string, unknown> = {}) {
  return {
    volgnummer: 1,
    accordeur_gebruiker_id: 'x',
    accordeur_naam: 'S. Bakker',
    bedrag_drempel: null,
    vereist: true,
    besluit: null,
    besluit_bron: null,
    reden: null,
    besloten_op: null,
    aan_de_beurt: true,
    ...overrides,
  }
}

function installFetchMock(accordering: unknown, intrekkenAanroepen?: string[], laatstHerinnerd?: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/intrekken') && init?.method === 'POST') {
        intrekkenAanroepen?.push(url)
        return Promise.resolve(jsonResponse({ ...(accordering as object), status: 'ingetrokken' }))
      }
      if (url.endsWith('/accordering/herinneringen')) {
        return Promise.resolve(
          jsonResponse({ laatst_herinnerd: laatstHerinnerd ? { [DOCUMENT_ID]: laatstHerinnerd } : {} }),
        )
      }
      if (url.includes('/accordering/documenten/')) return Promise.resolve(jsonResponse(accordering))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

const OPEN_ACCORDERING = {
  id: 'acc-1',
  document_id: DOCUMENT_ID,
  status: 'open',
  aangeboden_op: '2026-08-08T10:00:00Z',
  afgerond_op: null,
  stappen: [stap()],
}

describe('AccorderingSectie', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('rendert niets zolang er geen accorderingsronde is', async () => {
    installFetchMock(null)
    const { container } = render(
      <AccorderingSectie
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        documentStatus="klaar_om_te_boeken"
        onGewijzigd={() => {}}
      />,
    )
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    expect(container.querySelector('.panel')).toBeNull()
  })

  it('toont de lagen met besluit-chips, drempel en staande-regel-herkomst', async () => {
    installFetchMock({
      id: 'acc-1',
      document_id: DOCUMENT_ID,
      status: 'open',
      aangeboden_op: '2026-08-08T10:00:00Z',
      afgerond_op: null,
      stappen: [
        stap({
          besluit: 'akkoord',
          besluit_bron: 'staande_regel',
          besloten_op: '2026-08-08T10:00:01Z',
          aan_de_beurt: false,
        }),
        stap({
          volgnummer: 2,
          accordeur_naam: 'R. Jansen',
          bedrag_drempel: '1000.00',
          aan_de_beurt: true,
        }),
      ],
    })
    render(
      <AccorderingSectie
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        documentStatus="ter_accordering"
        onGewijzigd={() => {}}
      />,
    )

    expect(await screen.findByText('Klant-accordering')).toBeInTheDocument()
    expect(screen.getByText('automatisch akkoord — staande goedkeuring')).toBeInTheDocument()
    expect(screen.getByText('aan de beurt')).toBeInTheDocument()
    expect(screen.getByText('alleen > € 1000.00')).toBeInTheDocument()
    expect(screen.getByText('S. Bakker')).toBeInTheDocument()
  })

  it('kan een open ronde terughalen (intrekken)', async () => {
    const intrekkenAanroepen: string[] = []
    const onGewijzigd = vi.fn()
    installFetchMock(
      {
        id: 'acc-1',
        document_id: DOCUMENT_ID,
        status: 'open',
        aangeboden_op: '2026-08-08T10:00:00Z',
        afgerond_op: null,
        stappen: [stap()],
      },
      intrekkenAanroepen,
    )
    render(
      <AccorderingSectie
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        documentStatus="ter_accordering"
        onGewijzigd={onGewijzigd}
      />,
    )

    await userEvent.click(await screen.findByRole('button', { name: /Terughalen uit accordering/ }))
    await waitFor(() => expect(intrekkenAanroepen).toHaveLength(1))
    expect(onGewijzigd).toHaveBeenCalled()
  })

  it('dagrem: vandaag al herinnerd = knop disabled mét tijdstip (geen fout-ná-klik)', async () => {
    installFetchMock(OPEN_ACCORDERING, undefined, new Date().toISOString())
    render(
      <AccorderingSectie
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        documentStatus="ter_accordering"
        onGewijzigd={() => {}}
      />,
    )

    const knop = await screen.findByRole('button', { name: /Vandaag al herinnerd om \d{2}:\d{2}/ })
    expect(knop).toBeDisabled()
  })

  it('dagrem: gisteren herinnerd = knop gewoon actief (nieuwe dag, nieuwe claim)', async () => {
    const gisteren = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
    installFetchMock(OPEN_ACCORDERING, undefined, gisteren)
    render(
      <AccorderingSectie
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        documentStatus="ter_accordering"
        onGewijzigd={() => {}}
      />,
    )

    const knop = await screen.findByRole('button', { name: 'Herinner accordeur' })
    expect(knop).toBeEnabled()
    expect(screen.getByText(/laatst herinnerd/)).toBeInTheDocument()
  })
})
