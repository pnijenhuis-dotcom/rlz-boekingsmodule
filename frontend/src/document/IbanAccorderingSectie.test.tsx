import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IbanAccorderingSectie } from './IbanAccorderingSectie'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const AANVRAGER_ID = 'dddddddd-0000-0000-0000-000000000004'
const ACCORDEUR_ID = 'eeeeeeee-0000-0000-0000-000000000005'

// Ingelogde gebruiker per test instelbaar (vier-ogen is rol-afhankelijke UI).
const authMock = { gebruikerId: AANVRAGER_ID, rol: 'boekhouding' as string | null }
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => authMock,
}))

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const OPEN_ACCORDERING = {
  id: 'ffffffff-0000-0000-0000-000000000001',
  document_id: DOCUMENT_ID,
  document_status: 'wacht_op_iban_accordering',
  vendor_id: 'cccccccc-0000-0000-0000-000000000003',
  nieuw_iban: 'NL91ABNA0417164300',
  soort: 'g_rekening',
  status: 'open',
  status_voor_accordering: 'te_controleren',
  aangevraagd_door: AANVRAGER_ID,
  aangevraagd_op: '2026-07-15T10:00:00Z',
  besloten_door: null,
  besloten_op: null,
  afwijs_reden: null,
}

function installFetchMock(opties: {
  accorderingen: unknown[]
  accordeurs?: string[]
  acties?: { url: string; body: unknown }[]
}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if ((url.includes('/accorderen') || url.includes('/afwijzen')) && init?.method === 'POST') {
        opties.acties?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse({ ...OPEN_ACCORDERING, status: 'geaccordeerd' }))
      }
      if (url.includes('/iban-accordering') && init?.method === 'POST') {
        opties.acties?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse(OPEN_ACCORDERING, 201))
      }
      if (url.includes('/iban-accorderingen')) {
        return Promise.resolve(jsonResponse({ accorderingen: opties.accorderingen }))
      }
      if (url.endsWith('/iban-accordeurs')) {
        return Promise.resolve(jsonResponse({ accordeurs: opties.accordeurs ?? [ACCORDEUR_ID] }))
      }
      if (url.endsWith('/medewerkers')) {
        return Promise.resolve(
          jsonResponse({
            medewerkers: [
              { id: AANVRAGER_ID, naam: 'P. Aanvrager' },
              { id: ACCORDEUR_ID, naam: 'M. Accordeur' },
            ],
          }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderSectie(onGewijzigd: () => void = () => {}) {
  return render(
    <IbanAccorderingSectie
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      onGewijzigd={onGewijzigd}
    />,
  )
}

describe('IbanAccorderingSectie (vier-ogen, docs/ontwerp/iban-wissel-accordering.md)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    authMock.gebruikerId = AANVRAGER_ID
    authMock.rol = 'boekhouding'
  })

  it('aanvrager ziet de wachtstatus met accordeur-naam maar GEEN accordeer-acties', async () => {
    installFetchMock({ accorderingen: [OPEN_ACCORDERING] })
    renderSectie()

    await screen.findByText(/Wacht op accordering door/)
    expect(screen.getByText('M. Accordeur')).toBeInTheDocument()
    // Gemaskeerd IBAN, nooit het volledige nummer in de wachtstatus-tekst.
    expect(screen.getByText('NL91ABNA…300')).toBeInTheDocument()
    expect(screen.queryByText('NL91ABNA0417164300')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Accorderen/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Afwijzen/ })).not.toBeInTheDocument()
  })

  it('niet-accordeur (ook niet de aanvrager) ziet dezelfde read-only wachtstatus', async () => {
    authMock.gebruikerId = 'aaaaaaaa-9999-0000-0000-000000000009'
    installFetchMock({ accorderingen: [OPEN_ACCORDERING] })
    renderSectie()

    await screen.findByText(/Wacht op accordering door/)
    expect(screen.queryByRole('button', { name: /Accorderen/ })).not.toBeInTheDocument()
  })

  it('accordeur ≠ aanvrager ziet het accordeer-paneel met fraude-waarschuwing en kan accorderen', async () => {
    authMock.gebruikerId = ACCORDEUR_ID
    const acties: { url: string; body: unknown }[] = []
    const gewijzigd = vi.fn()
    installFetchMock({ accorderingen: [OPEN_ACCORDERING], acties })
    renderSectie(gewijzigd)

    await screen.findByText(/uw accordering gevraagd/)
    expect(screen.getByText(/IBAN-wissel-fraude/)).toBeInTheDocument()
    expect(screen.getByText(/G-rekening \(WKA\)/)).toBeInTheDocument()
    expect(screen.getByText(/aangeboden door P. Aanvrager/)).toBeInTheDocument()

    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getByRole('button', { name: /Accorderen en deblokkeren/ }))
    await waitFor(() => expect(gewijzigd).toHaveBeenCalled())
    expect(acties).toHaveLength(1)
    expect(acties[0].url).toContain(`/iban-accorderingen/${OPEN_ACCORDERING.id}/accorderen`)
  })

  it('afwijzen vereist een reden: knop uitgeschakeld tot er tekst staat, reden reist mee', async () => {
    authMock.gebruikerId = ACCORDEUR_ID
    const acties: { url: string; body: unknown }[] = []
    const gewijzigd = vi.fn()
    installFetchMock({ accorderingen: [OPEN_ACCORDERING], acties })
    renderSectie(gewijzigd)

    const gebruiker = userEvent.setup()
    await gebruiker.click(await screen.findByRole('button', { name: 'Afwijzen…' }))
    const afwijsKnop = screen.getByRole('button', { name: 'Afwijzen' })
    expect(afwijsKnop).toBeDisabled()
    await gebruiker.type(screen.getByLabelText(/Reden van afwijzing/), 'Telefonisch niet bevestigd')
    expect(afwijsKnop).toBeEnabled()
    await gebruiker.click(afwijsKnop)

    await waitFor(() => expect(gewijzigd).toHaveBeenCalled())
    expect(acties[0].url).toContain(`/iban-accorderingen/${OPEN_ACCORDERING.id}/afwijzen`)
    expect(acties[0].body).toEqual({ reden: 'Telefonisch niet bevestigd' })
  })

  it('lege accordeur-set: beheerder ziet het accordeer-paneel', async () => {
    authMock.gebruikerId = ACCORDEUR_ID
    authMock.rol = 'beheerder'
    installFetchMock({ accorderingen: [OPEN_ACCORDERING], accordeurs: [] })
    renderSectie()

    await screen.findByText(/uw accordering gevraagd/)
    expect(screen.getByRole('button', { name: /Accorderen en deblokkeren/ })).toBeInTheDocument()
    // Terugval zichtbaar benoemd voor wie er níét bij kan: "de beheerder(s)".
  })

  it('lege accordeur-set: gewone medewerker (≠ aanvrager) blijft read-only met "de beheerder(s)"', async () => {
    authMock.gebruikerId = ACCORDEUR_ID
    authMock.rol = 'boekhouding'
    installFetchMock({ accorderingen: [OPEN_ACCORDERING], accordeurs: [] })
    renderSectie()

    await screen.findByText(/Wacht op accordering door/)
    expect(screen.getByText('de beheerder(s)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Accorderen/ })).not.toBeInTheDocument()
  })

  it('na een afwijzing toont de sectie het document als verdacht mét reden en her-aanvraag', async () => {
    const afgewezen = {
      ...OPEN_ACCORDERING,
      status: 'afgewezen',
      besloten_door: ACCORDEUR_ID,
      besloten_op: '2026-07-15T11:00:00Z',
      afwijs_reden: 'Rekeningnummer telefonisch niet bevestigd',
    }
    const acties: { url: string; body: unknown }[] = []
    installFetchMock({ accorderingen: [afgewezen], acties })
    renderSectie()

    await screen.findByText(/afgewezen — verdacht/)
    expect(screen.getByText(/Rekeningnummer telefonisch niet bevestigd/)).toBeInTheDocument()
    expect(screen.getByText(/afgewezen door/)).toBeInTheDocument()
    expect(screen.getByText('M. Accordeur')).toBeInTheDocument()

    // Her-aanvraag: volledige nieuwe vier-ogen-ronde.
    const gebruiker = userEvent.setup()
    await gebruiker.click(screen.getByRole('button', { name: 'Opnieuw ter accordering aanbieden' }))
    await waitFor(() => expect(acties).toHaveLength(1))
    expect(acties[0].url).toContain(`/documenten/${DOCUMENT_ID}/iban-accordering`)
    expect(acties[0].body).toMatchObject({ nieuw_iban: 'NL91ABNA0417164300' })
  })
})
