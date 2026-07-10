import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { InstellingenScreen } from './InstellingenScreen'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Alleen de payload moet kloppen — decodeerJwtPayload() verifieert geen handtekening (puur
 * UI-weergave, zie api/client.ts). Header/signature-delen zijn dummy's. */
function fakeAccessToken(rol: string): string {
  const payload = btoa(JSON.stringify({ sub: 'gebruiker-id', rol })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

function administratie(overrides: Record<string, unknown> = {}) {
  return {
    id: ADMINISTRATIE_ID,
    naam: 'Testklant B.V.',
    boeken_ingeschakeld: false,
    project_verplicht: false,
    ...overrides,
  }
}

function installFetchMock(opties: {
  rol: string
  administraties?: unknown[]
  killSwitch?: boolean
  putAanroepen?: { url: string; body: unknown }[]
}) {
  const administraties = opties.administraties ?? [administratie()]
  let killSwitch = opties.killSwitch ?? true
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === '/auth/token/vernieuwen' && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ access_token: fakeAccessToken(opties.rol) }))
      }
      if (url === '/instellingen/administraties') {
        return Promise.resolve(jsonResponse({ administraties }))
      }
      if (url === '/instellingen/boeken-kill-switch' && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse({ ingeschakeld: killSwitch }))
      }
      if (url === '/instellingen/boeken-kill-switch' && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { ingeschakeld: boolean }
        killSwitch = body.ingeschakeld
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse({ ingeschakeld: killSwitch }))
      }
      if (url.endsWith('/boeken-instelling') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as unknown
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
      }
      if (url.endsWith('/project-instelling') && init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as unknown
        opties.putAanroepen?.push({ url, body })
        return Promise.resolve(jsonResponse(body))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/instellingen']}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<div>WERKVOORRAAD-SCHERM</div>} />
          <Route path="/instellingen" element={<InstellingenScreen />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('InstellingenScreen — rolgedrag (design-pass taak 3)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('een niet-Beheerder wordt weggestuurd en ziet het scherm niet', async () => {
    installFetchMock({ rol: 'boekhouding' })
    renderScherm()

    await waitFor(() => expect(screen.getByText('WERKVOORRAAD-SCHERM')).toBeInTheDocument())
    expect(screen.queryByText('Administraties')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /kill switch/i })).not.toBeInTheDocument()
  })

  it('een Beheerder ziet de administraties-lijst en de kill switch', async () => {
    installFetchMock({ rol: 'beheerder', administraties: [administratie({ naam: 'Kempen Facilities B.V.' })] })
    renderScherm()

    await waitFor(() => expect(screen.getByText('Kempen Facilities B.V.')).toBeInTheDocument())
    expect(screen.getByRole('heading', { name: /kill switch/i })).toBeInTheDocument()
    expect(screen.queryByText('WERKVOORRAAD-SCHERM')).not.toBeInTheDocument()
  })
})

describe('InstellingenScreen — toggle-flow (Beheerder)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('een toggle-klik opent een bevestigingsdialoog en wijzigt pas na bevestigen', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'BLOW B.V.', boeken_ingeschakeld: false })],
      putAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('BLOW B.V.')).toBeInTheDocument())
    const rij = screen.getByText('BLOW B.V.').closest('tr')
    if (!rij) throw new Error('rij niet gevonden')
    const boekenToggle = within(rij).getAllByRole('checkbox')[1]

    await gebruiker.click(boekenToggle)

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/Boeken wordt ingeschakeld voor "BLOW B.V."/)).toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    expect(boekenToggle).not.toBeChecked()

    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(putAanroepen).toHaveLength(1)
    expect(putAanroepen[0].url).toContain(`/administraties/${ADMINISTRATIE_ID}/boeken-instelling`)
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: true })
    await waitFor(() => expect(boekenToggle).toBeChecked())
  })

  it('annuleren sluit de dialoog zonder een aanroep te doen en laat de toggle ongewijzigd', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      rol: 'beheerder',
      administraties: [administratie({ naam: 'BLOW B.V.', project_verplicht: false })],
      putAanroepen,
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('BLOW B.V.')).toBeInTheDocument())
    const rij = screen.getByText('BLOW B.V.').closest('tr')
    if (!rij) throw new Error('rij niet gevonden')
    const projectToggle = within(rij).getAllByRole('checkbox')[0]

    await gebruiker.click(projectToggle)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Annuleren' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(putAanroepen).toHaveLength(0)
    expect(projectToggle).not.toBeChecked()
  })

  it('de globale kill switch vraagt ook een bevestiging', async () => {
    const gebruiker = userEvent.setup()
    const putAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ rol: 'beheerder', killSwitch: true, putAanroepen })
    renderScherm()

    // De heading rendert al vóórdat de Promise.all met instellingen-data terug is — wacht dus op
    // de checkbox zelf (die pas ná het laden bestaat), anders is deze test een race/flake.
    await waitFor(() => expect(screen.getAllByRole('checkbox').length).toBeGreaterThan(0))
    const killSwitchToggle = screen.getAllByRole('checkbox')[0]
    await gebruiker.click(killSwitchToggle)

    expect(screen.getByText(/stopgezet, ongeacht de toggle per administratie/)).toBeInTheDocument()
    await gebruiker.click(screen.getByRole('button', { name: 'Bevestigen' }))

    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0].url).toBe('/instellingen/boeken-kill-switch')
    expect(putAanroepen[0].body).toEqual({ ingeschakeld: false })
  })
})
