import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AfwijzingDto } from '../api/types'
import { AfwijsModal } from './AfwijsModal'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const EIGENAAR_ID = 'dddddddd-0000-0000-0000-000000000004'
const COLLEGA_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetchMock(opties: {
  eigenaarId?: string | null
  afwijsAanroepen?: { url: string; body: unknown }[]
  afwijsStatus?: number
  afwijsFout?: string
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
        // Expliciete null = administratie zonder eigenaar (zelfde mock-conventie als
        // VraagModal.test.tsx).
        const eigenaarId = opties.eigenaarId !== undefined ? opties.eigenaarId : EIGENAAR_ID
        return Promise.resolve(jsonResponse({ eigenaar_gebruiker_id: eigenaarId }))
      }
      if (url.endsWith('/afwijzen') && init?.method === 'POST') {
        opties.afwijsAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        if (opties.afwijsStatus && opties.afwijsStatus >= 400) {
          return Promise.resolve(jsonResponse({ detail: opties.afwijsFout ?? 'fout' }, opties.afwijsStatus))
        }
        return Promise.resolve(jsonResponse({ id: 'a1', status: 'open' }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('AfwijsModal (mockup #afwijsmodal)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function renderModal(onAfgewezen: (a: AfwijzingDto) => void = () => {}) {
    return render(
      <AfwijsModal
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        onAfgewezen={onAfgewezen}
        onAnnuleren={() => {}}
      />,
    )
  }

  it('selecteert de administratie-eigenaar als standaard voor "Ter controle naar"', async () => {
    installFetchMock({})
    renderModal()

    await waitFor(() => expect(screen.getByLabelText('Ter controle naar')).toHaveValue(EIGENAAR_ID))
    expect(screen.getByText('M. de Boer — eigenaar administratie (standaard)')).toBeInTheDocument()
  })

  it('toont "— kies een medewerker —" zonder voorselectie als de administratie geen eigenaar heeft', async () => {
    installFetchMock({ eigenaarId: null })
    renderModal()

    await waitFor(() => expect(screen.getByLabelText('Ter controle naar')).toBeEnabled())
    expect(screen.getByLabelText('Ter controle naar')).toHaveValue('')
    expect(screen.getByText('— kies een medewerker —')).toBeInTheDocument()
  })

  it('afwijzen is uitgeschakeld zolang de reden leeg is (verplichte reden)', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({})
    renderModal()

    await waitFor(() => expect(screen.getByLabelText(/Reden van afwijzing/)).toBeInTheDocument())
    const afwijsKnop = screen.getByRole('button', { name: 'Afwijzen' })
    expect(afwijsKnop).toBeDisabled()

    // Alleen witruimte telt niet als reden.
    await gebruiker.type(screen.getByLabelText(/Reden van afwijzing/), '   ')
    expect(afwijsKnop).toBeDisabled()

    await gebruiker.type(screen.getByLabelText(/Reden van afwijzing/), 'Niet onze bestelling')
    expect(afwijsKnop).toBeEnabled()
  })

  it('verstuurt reden + gekozen toewijzing en meldt de zichtbaarheid vooraf', async () => {
    const gebruiker = userEvent.setup()
    const afwijsAanroepen: { url: string; body: unknown }[] = []
    const afgewezen = vi.fn()
    installFetchMock({ afwijsAanroepen })
    renderModal(afgewezen)

    expect(screen.getByText(/blijft zichtbaar in de werkvoorraad/)).toBeInTheDocument()

    await waitFor(() => expect(screen.getByLabelText('Ter controle naar')).toHaveValue(EIGENAAR_ID))
    await gebruiker.selectOptions(screen.getByLabelText('Ter controle naar'), COLLEGA_ID)
    await gebruiker.type(screen.getByLabelText(/Reden van afwijzing/), 'Niet onze bestelling')
    await gebruiker.click(screen.getByRole('button', { name: 'Afwijzen' }))

    await waitFor(() => expect(afgewezen).toHaveBeenCalled())
    expect(afwijsAanroepen).toHaveLength(1)
    expect(afwijsAanroepen[0].url).toContain(`/documenten/${DOCUMENT_ID}/afwijzen`)
    expect(afwijsAanroepen[0].body).toEqual({ reden: 'Niet onze bestelling', toegewezen_aan: COLLEGA_ID })
  })

  it('toont een backend-weigering zichtbaar in de modal', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ afwijsAanroepen: [], afwijsStatus: 409, afwijsFout: 'Vanuit status geboekt kan niet afgewezen worden' })
    renderModal()

    await waitFor(() => expect(screen.getByLabelText('Ter controle naar')).toHaveValue(EIGENAAR_ID))
    await gebruiker.type(screen.getByLabelText(/Reden van afwijzing/), 'Dubbel document')
    await gebruiker.click(screen.getByRole('button', { name: 'Afwijzen' }))

    await waitFor(() =>
      expect(screen.getByText(/Vanuit status geboekt kan niet afgewezen worden/)).toBeInTheDocument(),
    )
  })
})
