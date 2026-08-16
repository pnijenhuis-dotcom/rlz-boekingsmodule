/** Gebruikers & toegang (fase 3 modernisering 15-08): lijst, zelfbescherming-UI, opnieuw
 * mailen (fail-zichtbaar), accordeurs-blok met kill-switch. */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { GebruikersScreen } from './GebruikersScreen'

const EIGEN_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const ANDER_ID = 'bbbbbbbb-0000-0000-0000-00000000000b'
const ACCORDEUR_ID = 'cccccccc-0000-0000-0000-00000000000c'
const ADMINISTRATIE_ID = 'dddddddd-0000-0000-0000-00000000000d'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function fakeAccessToken(rol: string): string {
  const payload = btoa(JSON.stringify({ sub: EIGEN_ID, rol })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

function gebruiker(overrides: Record<string, unknown>) {
  return {
    id: ANDER_ID,
    naam: 'Demi de Vries',
    e_mail: 'demi@ak-nijenhuis.nl',
    rol: 'boekhouding',
    status: 'actief',
    administratie_ids: [ADMINISTRATIE_ID],
    heeft_totp: true,
    aantal_passkeys: 0,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
    ...overrides,
  }
}

function installMock(opties: {
  rol?: string
  gebruikers?: unknown[]
  postAanroepen?: string[]
  mailVerzonden?: boolean
  apparaten?: unknown[]
}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === '/auth/token/vernieuwen' && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ access_token: fakeAccessToken(opties.rol ?? 'beheerder') }))
      }
      if (url === '/auth/gebruikers' && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse({ gebruikers: opties.gebruikers ?? [] }))
      }
      if (url === '/auth/administraties') {
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Molenhof Beheer B.V.' }] }))
      }
      if (url.endsWith('/uitnodiging-opnieuw') && init?.method === 'POST') {
        opties.postAanroepen?.push(url)
        return Promise.resolve(
          jsonResponse({
            uitnodiging_id: 'u-1',
            gebruiker_id: ANDER_ID,
            token: 'nieuw-token',
            verloopt_op: new Date(Date.now() + 72 * 3600e3).toISOString(),
            mail_verzonden: opties.mailVerzonden ?? true,
            mail_fout: (opties.mailVerzonden ?? true) ? null : 'SMTP niet geconfigureerd',
          }),
        )
      }
      if (url.includes('/apparaten') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            apparaten: opties.apparaten ?? [
              {
                id: 'app-1',
                apparaat_naam: 'iPhone van R.',
                is_dev_stub: false,
                aangemaakt_op: '2026-08-11T10:00:00Z',
                laatst_gebruikt_op: null,
                ingetrokken_op: null,
              },
            ],
          }),
        )
      }
      if (url.includes('/intrekken') && init?.method === 'POST') {
        opties.postAanroepen?.push(url)
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/gebruikers']}>
      <AuthProvider>
        <GebruikersScreen />
      </AuthProvider>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('GebruikersScreen', () => {
  it('toont kantoorgebruikers met rol, scope en beveiligingsstatus', async () => {
    installMock({
      gebruikers: [gebruiker({ heeft_totp: true, aantal_passkeys: 2 })],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('Demi de Vries')).toBeInTheDocument())
    expect(screen.getByText('demi@ak-nijenhuis.nl')).toBeInTheDocument()
    expect(screen.getByText('🔑 2 passkeys')).toBeInTheDocument()
    expect(screen.getByText('🔐 TOTP')).toBeInTheDocument()
    expect(screen.getByText('1 administratie')).toBeInTheDocument()
  })

  it('de eigen rij is niet zelf te muteren (zelfbescherming — alleen een ándere Beheerder)', async () => {
    installMock({
      gebruikers: [gebruiker({ id: EIGEN_ID, naam: 'Peter Nijenhuis', rol: 'beheerder' })],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('Peter Nijenhuis')).toBeInTheDocument())
    // Geen rol-select voor de eigen rij, wel de uitleg.
    expect(screen.queryByRole('combobox', { name: 'Rol van Peter Nijenhuis' })).not.toBeInTheDocument()
    expect(screen.getByText(/eigen rol\/scope wijzigt alleen een ándere Beheerder/)).toBeInTheDocument()
  })

  it('een open uitnodiging toont "Opnieuw mailen" en POST naar het nieuwe endpoint', async () => {
    const posts: string[] = []
    installMock({
      gebruikers: [
        gebruiker({
          status: 'uitgenodigd',
          heeft_totp: false,
          open_uitnodiging_verloopt_op: new Date(Date.now() + 68 * 3600e3).toISOString(),
        }),
      ],
      postAanroepen: posts,
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText(/verloopt over/)).toBeInTheDocument())
    const gebruikerEvent = userEvent.setup()
    await gebruikerEvent.click(screen.getByRole('button', { name: 'Opnieuw mailen' }))
    await waitFor(() => expect(posts).toContain(`/auth/gebruikers/${ANDER_ID}/uitnodiging-opnieuw`))
  })

  it('een mailfout bij opnieuw mailen is zichtbaar (fail-zichtbaar, nooit stil)', async () => {
    installMock({
      gebruikers: [
        gebruiker({
          status: 'uitgenodigd',
          open_uitnodiging_verloopt_op: new Date(Date.now() + 68 * 3600e3).toISOString(),
        }),
      ],
      postAanroepen: [],
      mailVerzonden: false,
    })
    renderScherm()

    await waitFor(() => expect(screen.getByRole('button', { name: 'Opnieuw mailen' })).toBeInTheDocument())
    await userEvent.setup().click(screen.getByRole('button', { name: 'Opnieuw mailen' }))
    await waitFor(() => expect(screen.getByText(/het mailen mislukte: SMTP niet geconfigureerd/)).toBeInTheDocument())
  })

  it('het accordeurs-blok toont administraties, staande goedkeuringen en de kill-switch met bevestiging', async () => {
    const posts: string[] = []
    installMock({
      gebruikers: [
        gebruiker({
          id: ACCORDEUR_ID,
          naam: 'R. de Groot',
          e_mail: 'r.degroot@molenhof.nl',
          rol: 'klant_accordeur',
          aantal_passkeys: 1,
          staande_goedkeuringen: 2,
        }),
      ],
      postAanroepen: posts,
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText('R. de Groot')).toBeInTheDocument())
    expect(screen.getByText('Molenhof Beheer B.V.')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/iPhone van R\./)).toBeInTheDocument())

    const gebruikerEvent = userEvent.setup()
    await gebruikerEvent.click(screen.getByRole('button', { name: 'Kill-switch' }))
    // Niets gebeurt vóór de bevestiging.
    expect(posts).toHaveLength(0)
    expect(screen.getByText(/per direct geblokkeerd/)).toBeInTheDocument()
    await gebruikerEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(posts).toContain('/auth/apparaten/app-1/intrekken'))
  })

  it('dubbele dev-stub-credentials tonen als één apparaat en de kill-switch trekt ze állemaal in', async () => {
    const posts: string[] = []
    const stub = {
      apparaat_naam: 'LAN-telefoon (dev-stub)',
      is_dev_stub: true,
      aangemaakt_op: '2026-08-11T10:00:00Z',
      laatst_gebruikt_op: null,
      ingetrokken_op: null,
    }
    installMock({
      gebruikers: [
        gebruiker({ id: ACCORDEUR_ID, naam: 'R. de Groot', rol: 'klant_accordeur', aantal_passkeys: 1 }),
      ],
      postAanroepen: posts,
      apparaten: [
        { ...stub, id: 'stub-1' },
        { ...stub, id: 'stub-2' },
        {
          id: 'echt-1',
          apparaat_naam: 'iPhone van R.',
          is_dev_stub: false,
          aangemaakt_op: '2026-08-11T10:00:00Z',
          laatst_gebruikt_op: null,
          ingetrokken_op: null,
        },
      ],
    })
    renderScherm()

    await waitFor(() => expect(screen.getByText(/LAN-telefoon \(dev-stub\)/)).toBeInTheDocument())
    // Eén chip voor de gedupliceerde stub, de echte passkey blijft een eigen rij.
    expect(screen.getAllByText(/LAN-telefoon/)).toHaveLength(1)
    expect(screen.getByText(/iPhone van R\./)).toBeInTheDocument()

    const gebruikerEvent = userEvent.setup()
    await gebruikerEvent.click(screen.getAllByRole('button', { name: 'Kill-switch' })[0])
    await gebruikerEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    // Beide onderliggende credentials worden ingetrokken — nooit stil eentje laten staan.
    await waitFor(() => expect(posts).toContain('/auth/apparaten/stub-1/intrekken'))
    expect(posts).toContain('/auth/apparaten/stub-2/intrekken')
    expect(posts).not.toContain('/auth/apparaten/echt-1/intrekken')
  })

  it('een niet-Beheerder krijgt een nette melding, geen lege tabel', async () => {
    installMock({ rol: 'boekhouding', gebruikers: [] })
    renderScherm()

    await waitFor(() =>
      expect(screen.getByText(/alleen toegankelijk voor de Beheerder-rol/)).toBeInTheDocument(),
    )
  })
})
