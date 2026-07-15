import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { VraagDto } from '../api/types'
import { VraagModal } from './VraagModal'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const EIGENAAR_ID = 'dddddddd-0000-0000-0000-000000000004'
const COLLEGA_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetchMock(opties: {
  eigenaarId?: string | null
  stelAanroepen?: { url: string; body: unknown }[]
  stelStatus?: number
  stelFout?: string
}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/medewerkers')) {
        return Promise.resolve(
          jsonResponse({
            medewerkers: [
              { id: COLLEGA_ID, naam: 'J. Willems' },
              { id: EIGENAAR_ID, naam: 'M. de Boer' },
            ],
          }),
        )
      }
      if (url.endsWith('/eigenaar')) {
        // Expliciete null = administratie zonder eigenaar (?? zou null stil naar de default
        // terugvouwen en het geen-eigenaar-pad ontestbaar maken).
        const eigenaarId = opties.eigenaarId !== undefined ? opties.eigenaarId : EIGENAAR_ID
        return Promise.resolve(jsonResponse({ eigenaar_gebruiker_id: eigenaarId }))
      }
      if (url.endsWith('/vraag') && init?.method === 'POST') {
        opties.stelAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        if (opties.stelStatus && opties.stelStatus >= 400) {
          return Promise.resolve(jsonResponse({ detail: opties.stelFout ?? 'fout' }, opties.stelStatus))
        }
        return Promise.resolve(jsonResponse({ id: 'v1', status: 'open' }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('VraagModal (mockup #vraagmodal)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function renderModal(onGesteld: (v: VraagDto) => void = () => {}) {
    return render(
      <VraagModal
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        onGesteld={onGesteld}
        onAnnuleren={() => {}}
      />,
    )
  }

  it('selecteert de administratie-eigenaar als standaard-toewijzing', async () => {
    installFetchMock({})
    renderModal()

    await waitFor(() =>
      expect(screen.getByLabelText('Toewijzen aan')).toHaveValue(EIGENAAR_ID),
    )
    expect(screen.getByText('M. de Boer — eigenaar administratie (standaard)')).toBeInTheDocument()
  })

  it('toont "— kies een medewerker —" zonder voorselectie als de administratie geen eigenaar heeft', async () => {
    installFetchMock({ eigenaarId: null })
    renderModal()

    await waitFor(() => expect(screen.getByLabelText('Toewijzen aan')).toBeEnabled())
    expect(screen.getByLabelText('Toewijzen aan')).toHaveValue('')
    expect(screen.getByText('— kies een medewerker —')).toBeInTheDocument()
    expect(screen.queryByText(/eigenaar administratie \(standaard\)/)).not.toBeInTheDocument()
  })

  it('versturen is uitgeschakeld zolang de vraagtekst leeg is', async () => {
    installFetchMock({})
    renderModal()

    await waitFor(() => expect(screen.getByLabelText('Toewijzen aan')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Vraag versturen' })).toBeDisabled()
  })

  it('verstuurt vraagtekst + gekozen toewijzing en meldt de blokkade vooraf', async () => {
    const gebruiker = userEvent.setup()
    const stelAanroepen: { url: string; body: unknown }[] = []
    const gesteld = vi.fn()
    installFetchMock({ stelAanroepen })
    renderModal(gesteld)

    expect(screen.getByText(/Boeken is geblokkeerd tot de vraag beantwoord/)).toBeInTheDocument()

    await waitFor(() => expect(screen.getByLabelText('Toewijzen aan')).toHaveValue(EIGENAAR_ID))
    await gebruiker.selectOptions(screen.getByLabelText('Toewijzen aan'), COLLEGA_ID)
    await gebruiker.type(screen.getByLabelText('Vraag'), 'Op welke kostenpost?')
    await gebruiker.click(screen.getByRole('button', { name: 'Vraag versturen' }))

    await waitFor(() => expect(gesteld).toHaveBeenCalled())
    expect(stelAanroepen).toHaveLength(1)
    expect(stelAanroepen[0].url).toContain(`/documenten/${DOCUMENT_ID}/vraag`)
    expect(stelAanroepen[0].body).toEqual({ vraag_tekst: 'Op welke kostenpost?', toegewezen_aan: COLLEGA_ID })
  })

  it('toont een backend-weigering zichtbaar in de modal', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ stelAanroepen: [], stelStatus: 409, stelFout: 'Er staat al een open vraag op dit document' })
    renderModal()

    await waitFor(() => expect(screen.getByLabelText('Toewijzen aan')).toHaveValue(EIGENAAR_ID))
    await gebruiker.type(screen.getByLabelText('Vraag'), 'Dubbele vraag')
    await gebruiker.click(screen.getByRole('button', { name: 'Vraag versturen' }))

    await waitFor(() =>
      expect(screen.getByText(/Er staat al een open vraag op dit document/)).toBeInTheDocument(),
    )
  })
})
