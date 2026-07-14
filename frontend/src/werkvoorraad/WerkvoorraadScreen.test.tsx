import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WerkvoorraadScreen } from './WerkvoorraadScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const GEBOEKT_DOCUMENT_ID = 'cccccccc-0000-0000-0000-000000000003'
const VERWIJDERD_DOCUMENT_ID = 'dddddddd-0000-0000-0000-000000000004'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function document(overrides: Record<string, unknown>) {
  return {
    id: DOCUMENT_ID,
    bestandsnaam: 'factuur.pdf',
    status: 'te_controleren',
    bron: 'upload',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-07-09T10:00:00Z',
    laatst_gewijzigd_op: '2026-07-09T10:00:00Z',
    ...overrides,
  }
}

interface MockOpties {
  documenten?: unknown[]
  verwijderdeDocumenten?: unknown[]
  verwijderenAanroepen?: { url: string; body: unknown }[]
  herstellenAanroepen?: string[]
  verwijderenStatus?: number
}

function installFetchMock(opties: MockOpties) {
  const documenten = opties.documenten ?? [document({})]
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Testklant' }] }))
      }
      if (url.includes('/verwijderen') && init?.method === 'POST') {
        opties.verwijderenAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(
          jsonResponse({ document_id: DOCUMENT_ID, status: 'verwijderd' }, opties.verwijderenStatus ?? 200),
        )
      }
      if (url.includes('/herstellen') && init?.method === 'POST') {
        opties.herstellenAanroepen?.push(url)
        return Promise.resolve(jsonResponse({ document_id: VERWIJDERD_DOCUMENT_ID, status: 'te_controleren' }))
      }
      if (url.includes('/documenten') && (!init || init.method === undefined)) {
        const toontVerwijderd = url.includes('toon_verwijderd=true')
        return Promise.resolve(
          jsonResponse({ documenten: toontVerwijderd ? (opties.verwijderdeDocumenten ?? documenten) : documenten }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <WerkvoorraadScreen />
    </MemoryRouter>,
  )
}

describe('WerkvoorraadScreen — verwijderen/herstellen (design-pass taak 4)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont het prullenbak-icoon en opent de bevestigingsdialoog met de bestandsnaam', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [document({})] })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Document verwijderen' }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/"factuur\.pdf" wordt niet definitief verwijderd/)).toBeInTheDocument()
  })

  it('bevestigen stuurt de optionele reden mee en herlaadt de lijst', async () => {
    const gebruiker = userEvent.setup()
    const verwijderenAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ documenten: [document({})], verwijderenAanroepen })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Document verwijderen' }))
    await gebruiker.type(screen.getByLabelText('Reden (optioneel)'), 'Dubbele upload')
    await gebruiker.click(screen.getByRole('button', { name: 'Verwijderen' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(verwijderenAanroepen).toHaveLength(1)
    expect(verwijderenAanroepen[0].url).toContain(`/documenten/${DOCUMENT_ID}/verwijderen`)
    expect(verwijderenAanroepen[0].body).toEqual({ reden: 'Dubbele upload' })
  })

  it('annuleren sluit de dialoog zonder een aanroep te doen', async () => {
    const gebruiker = userEvent.setup()
    const verwijderenAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ documenten: [document({})], verwijderenAanroepen })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Document verwijderen' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(verwijderenAanroepen).toHaveLength(0)
  })

  it('een fout bij verwijderen blijft in de dialoog zichtbaar (bv. "geboekt" dat toch nog faalt)', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ documenten: [document({})], verwijderenStatus: 409 })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Document verwijderen' }))
    await gebruiker.click(screen.getByRole('button', { name: 'Verwijderen' }))

    await waitFor(() => expect(within(screen.getByRole('dialog')).getByText(/Fout/)).toBeInTheDocument())
  })

  it('hard: het prullenbak-icoon wordt helemaal niet getoond voor een geboekt document (bewaarplicht)', async () => {
    installFetchMock({
      documenten: [document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'geboekte-factuur.pdf', status: 'geboekt' })],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('geboekte-factuur.pdf')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Document verwijderen' })).not.toBeInTheDocument()
  })

  it('hard: het prullenbak-icoon wordt ook niet getoond bij een lopende accordering', async () => {
    installFetchMock({
      documenten: [
        document({ id: GEBOEKT_DOCUMENT_ID, bestandsnaam: 'ter-accordering.pdf', status: 'ter_accordering' }),
      ],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('ter-accordering.pdf')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Document verwijderen' })).not.toBeInTheDocument()
  })

  it('pollt de lijst vanzelf zolang een document in de extractie-wachtrij of bij de worker staat', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      installFetchMock({
        documenten: [document({ bestandsnaam: 'monsterfactuur.pdf', status: 'extractie_wachtrij' })],
      })
      renderScherm()

      await waitFor(() => expect(screen.getByText('monsterfactuur.pdf')).toBeInTheDocument())
      expect(screen.getByText('In wachtrij (extractie)')).toBeInTheDocument()

      const lijstAanroepen = () =>
        vi
          .mocked(fetch)
          .mock.calls.filter(([url]) => String(url).includes('/documenten') && !String(url).includes('/documenten/'))
          .length
      const voor = lijstAanroepen()
      await vi.advanceTimersByTimeAsync(3500)
      expect(lijstAanroepen()).toBeGreaterThan(voor)
    } finally {
      vi.useRealTimers()
    }
  })

  it('pollt niet als er geen lopende extracties zijn', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      installFetchMock({ documenten: [document({})] })
      renderScherm()

      await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
      const lijstAanroepen = () =>
        vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/documenten')).length
      const voor = lijstAanroepen()
      await vi.advanceTimersByTimeAsync(7000)
      expect(lijstAanroepen()).toBe(voor)
    } finally {
      vi.useRealTimers()
    }
  })

  it('"toon verwijderde documenten" haalt de lijst met toon_verwijderd=true op en toont een herstelknop', async () => {
    const gebruiker = userEvent.setup()
    const herstellenAanroepen: string[] = []
    installFetchMock({
      documenten: [document({})],
      verwijderdeDocumenten: [
        document({ id: VERWIJDERD_DOCUMENT_ID, bestandsnaam: 'verwijderde-factuur.pdf', status: 'verwijderd' }),
      ],
      herstellenAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    expect(screen.queryByText('verwijderde-factuur.pdf')).not.toBeInTheDocument()

    await gebruiker.click(screen.getByLabelText('Toon verwijderde documenten'))
    await waitFor(() => expect(screen.getByText('verwijderde-factuur.pdf')).toBeInTheDocument())

    await gebruiker.click(screen.getByRole('button', { name: /Herstellen/ }))
    await waitFor(() => expect(herstellenAanroepen).toHaveLength(1))
    expect(herstellenAanroepen[0]).toContain(`/documenten/${VERWIJDERD_DOCUMENT_ID}/herstellen`)
  })
})

describe('WerkvoorraadScreen — vragenworkflow (PART B)', () => {
  const EIGENAAR_ID = 'eeeeeeee-0000-0000-0000-000000000009'

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function installVraagFetchMock(documenten: unknown[]) {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/auth/administraties')) {
          return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Testklant' }] }))
        }
        if (url.endsWith('/medewerkers')) {
          return Promise.resolve(jsonResponse({ medewerkers: [{ id: EIGENAAR_ID, naam: 'M. de Boer' }] }))
        }
        if (url.includes('/documenten') && (!init || init.method === undefined)) {
          return Promise.resolve(jsonResponse({ documenten }))
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
  }

  it('toont de vraag-open-chip, de toegewezen-naam en de open-vragen-teller', async () => {
    installVraagFetchMock([document({ status: 'vraag_open', toegewezen_aan: EIGENAAR_ID })])
    renderScherm()

    await waitFor(() => expect(screen.getByText('Vraag open')).toBeInTheDocument())
    expect(screen.getByText('M. de Boer')).toBeInTheDocument()
    const teller = screen.getByText('1 vraag open')
    expect(teller.closest('a')).toHaveAttribute('href', `/vragen?administratie=${ADMINISTRATIE_ID}`)
  })

  it('klik op een vraag-regel opent de vraag (vragen-view gefilterd op het document)', async () => {
    const gebruiker = userEvent.setup()
    installVraagFetchMock([document({ status: 'vraag_open', toegewezen_aan: EIGENAAR_ID })])
    render(
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<WerkvoorraadScreen />} />
          <Route path="/vragen" element={<div>vragen-view-probe</div>} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('factuur.pdf'))
    await waitFor(() => expect(screen.getByText('vragen-view-probe')).toBeInTheDocument())
  })

  it('zonder open vragen geen teller-chip', async () => {
    installVraagFetchMock([document({})])
    renderScherm()

    await waitFor(() => expect(screen.getByText('factuur.pdf')).toBeInTheDocument())
    expect(screen.queryByText(/vraag open/)).not.toBeInTheDocument()
  })
})
