/** Gebruikers & toegang (fase 3 modernisering 15-08): lijst, zelfbescherming-UI, opnieuw
 * mailen (fail-zichtbaar), accordeurs-blok met kill-switch. */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    open_herstel_verloopt_op: null,
    staande_goedkeuringen: 0,
    geblokkeerd_op: null,
    geblokkeerd_door_naam: null,
    ...overrides,
  }
}

function installMock(opties: {
  rol?: string
  gebruikers?: unknown[]
  postAanroepen?: string[]
  mailVerzonden?: boolean
  apparaten?: unknown[]
  openWerk?: unknown
}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === '/auth/token/vernieuwen' && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ access_token: fakeAccessToken(opties.rol ?? 'beheerder') }))
      }
      if (url.startsWith('/auth/gebruikers?') && (!init || init.method === undefined)) {
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
      if (url.endsWith('/herstel-link') && init?.method === 'POST') {
        opties.postAanroepen?.push(url)
        return Promise.resolve(
          jsonResponse({
            uitnodiging_id: 'h-1',
            gebruiker_id: ACCORDEUR_ID,
            token: 'herstel-token',
            verloopt_op: new Date(Date.now() + 72 * 3600e3).toISOString(),
            mail_verzonden: opties.mailVerzonden ?? true,
            mail_fout: (opties.mailVerzonden ?? true) ? null : 'SMTP niet geconfigureerd',
          }),
        )
      }
      if (url.includes('/intrekken') && init?.method === 'POST') {
        opties.postAanroepen?.push(url)
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      // Archiveren (26-08 punt 1): open-werk-telling vóór de bevestiging + de actie zelf.
      if (url.endsWith('/open-werk') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse(opties.openWerk ?? { open_accorderingen: 0, weekstaten_ter_keuring: 0, eigen_open_weekstaten: 0 }),
        )
      }
      if ((url.endsWith('/archiveren') || url.endsWith('/dearchiveren')) && init?.method === 'POST') {
        opties.postAanroepen?.push(url)
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm(pad = '/gebruikers') {
  return render(
    <MemoryRouter initialEntries={[pad]}>
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

  it('een actieve accordeur krijgt "Herstel-link" — bevestigen POST naar het herstel-endpoint (punt 7, 25-08)', async () => {
    const posts: string[] = []
    installMock({
      gebruikers: [
        gebruiker({ id: ACCORDEUR_ID, naam: 'R. de Groot', e_mail: 'r.degroot@molenhof.nl', rol: 'klant_accordeur' }),
        gebruiker({ naam: 'Kantoor K.', rol: 'boekhouding' }),
      ],
      postAanroepen: posts,
    })
    renderScherm('/gebruikers?groep=accordeurs')

    await waitFor(() => expect(screen.getByText('R. de Groot')).toBeInTheDocument())
    // Precies één knop: de accordeur wél, de kantoorgebruiker (wachtwoord + TOTP) níét.
    expect(screen.getAllByRole('button', { name: 'Herstel-link' })).toHaveLength(1)
    const gebruikerEvent = userEvent.setup()
    await gebruikerEvent.click(screen.getByRole('button', { name: 'Herstel-link' }))
    expect(screen.getByText(/Bestaande passkeys en akkoorden blijven staan/)).toBeInTheDocument()
    await gebruikerEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(posts).toContain(`/auth/gebruikers/${ACCORDEUR_ID}/herstel-link`))
  })

  it('mislukt het mailen van de herstel-link, dan staat de link zichtbaar om handmatig te delen', async () => {
    installMock({
      gebruikers: [gebruiker({ id: ACCORDEUR_ID, naam: 'R. de Groot', rol: 'klant_accordeur' })],
      mailVerzonden: false,
    })
    renderScherm('/gebruikers?groep=accordeurs')

    await waitFor(() => expect(screen.getByRole('button', { name: 'Herstel-link' })).toBeInTheDocument())
    const gebruikerEvent = userEvent.setup()
    await gebruikerEvent.click(screen.getByRole('button', { name: 'Herstel-link' }))
    await gebruikerEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(screen.getByText(/mailen mislukte/)).toBeInTheDocument())
    expect(screen.getByText(/activeren\?token=herstel-token&herstel=1/)).toBeInTheDocument()
  })

  it('een geblokkeerde of nog niet geactiveerde externe gebruiker krijgt géén herstel-knop', async () => {
    installMock({
      gebruikers: [
        gebruiker({ id: ACCORDEUR_ID, rol: 'klant_accordeur', status: 'geblokkeerd', geblokkeerd_op: '2026-08-25T09:00:00Z' }),
        gebruiker({
          rol: 'klant_accordeur',
          status: 'uitgenodigd',
          open_uitnodiging_verloopt_op: new Date(Date.now() + 68 * 3600e3).toISOString(),
        }),
      ],
    })
    renderScherm('/gebruikers?groep=accordeurs')

    await waitFor(() => expect(screen.getByRole('button', { name: 'Opnieuw mailen' })).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Herstel-link' })).not.toBeInTheDocument()
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
    renderScherm('/gebruikers?groep=accordeurs')

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
    renderScherm('/gebruikers?groep=accordeurs')

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

  it('tabs per groep met tellers; kantoor is de default en oude #accordeurs-ankers landen op de accordeurs-tab', async () => {
    installMock({
      gebruikers: [
        gebruiker({ id: ANDER_ID, naam: 'Demi de Vries' }),
        gebruiker({ id: ACCORDEUR_ID, naam: 'R. de Groot', rol: 'klant_accordeur' }),
        gebruiker({ id: 'ffffffff-0000-0000-0000-00000000000f', naam: 'Z. Zzp', rol: 'zzper' }),
      ],
    })
    const { unmount } = renderScherm()
    await waitFor(() => expect(screen.getByText('Demi de Vries')).toBeInTheDocument())
    expect(screen.getByRole('tab', { name: 'Kantoor (1)' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tab', { name: 'Veldwerkers (1)' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Klant-accordeurs (1)' })).toBeInTheDocument()
    expect(screen.queryByText('R. de Groot')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ Medewerker uitnodigen' })).toBeInTheDocument()

    await userEvent.setup().click(screen.getByRole('tab', { name: 'Klant-accordeurs (1)' }))
    await waitFor(() => expect(screen.getByText('R. de Groot')).toBeInTheDocument())
    expect(screen.queryByText('Demi de Vries')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ Accordeur uitnodigen' })).toBeInTheDocument()
    unmount()

    renderScherm('/gebruikers#accordeurs')
    await waitFor(() => expect(screen.getByText('R. de Groot')).toBeInTheDocument())
  })

  it('zoekveld filtert op naam/e-mail/administratie en paginering houdt 25 rijen per pagina', async () => {
    const veel = Array.from({ length: 30 }, (_, i) =>
      gebruiker({
        id: `aaaaaaaa-1111-0000-0000-${String(i).padStart(12, '0')}`,
        naam: `Medewerker ${String(i).padStart(2, '0')}`,
        e_mail: `m${i}@ak-nijenhuis.nl`,
      }),
    )
    installMock({ gebruikers: veel })
    renderScherm()
    await waitFor(() => expect(screen.getByText('Medewerker 00')).toBeInTheDocument())
    expect(screen.getByText('Medewerker 24')).toBeInTheDocument()
    expect(screen.queryByText('Medewerker 25')).not.toBeInTheDocument()
    expect(screen.getByText(/1–25 van 30 gebruikers/)).toBeInTheDocument()

    const gebruikerEvent = userEvent.setup()
    await gebruikerEvent.click(screen.getByRole('button', { name: 'Volgende pagina' }))
    expect(screen.getByText('Medewerker 25')).toBeInTheDocument()
    expect(screen.queryByText('Medewerker 00')).not.toBeInTheDocument()

    await gebruikerEvent.type(screen.getByRole('searchbox', { name: 'Zoek gebruikers' }), 'm7@')
    expect(screen.getByText('Medewerker 07')).toBeInTheDocument()
    expect(screen.queryByText('Medewerker 08')).not.toBeInTheDocument()
    expect(screen.getByText(/1 van 30 gebruikers/)).toBeInTheDocument()
    await gebruikerEvent.clear(screen.getByRole('searchbox', { name: 'Zoek gebruikers' }))
    await gebruikerEvent.type(screen.getByRole('searchbox', { name: 'Zoek gebruikers' }), 'molenhof')
    expect(screen.getByText('30 gebruikers')).toBeInTheDocument() // administratienaam matcht iedereen
  })

  it('accordeur met veel administraties toont één chip met een bekijk-dialoog; de actiekolom is sticky (3e)', async () => {
    const ids = [ADMINISTRATIE_ID, ...Array.from({ length: 10 }, (_, i) => `dddddddd-0000-0000-0000-${String(i + 1).padStart(12, '0')}`)]
    installMock({
      gebruikers: [gebruiker({ id: ACCORDEUR_ID, naam: 'R. de Groot', rol: 'klant_accordeur', administratie_ids: ids })],
    })
    renderScherm('/gebruikers?groep=accordeurs')
    await waitFor(() => expect(screen.getByText('R. de Groot')).toBeInTheDocument())
    expect(screen.getByText('11 administraties')).toBeInTheDocument()
    // Actieknoppen staan in de sticky actiekolom (3e).
    expect(screen.getByRole('button', { name: 'Blokkeren' }).closest('td')).toHaveClass('acties')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Administraties van R. de Groot bekijken' }))
    expect(await screen.findByRole('dialog')).toHaveTextContent('Molenhof Beheer B.V.')
  })
})

describe('GebruikersScreen — archiveren (feedbackronde 26-08 punt 1)', () => {
  it('gearchiveerden staan niet in de default-lijst; het filter "gearchiveerd (N)" toont ze mét Dearchiveren', async () => {
    installMock({
      gebruikers: [
        gebruiker({ id: ANDER_ID, naam: 'Actieve Collega' }),
        gebruiker({
          id: ACCORDEUR_ID,
          naam: 'Oud Account',
          status: 'gearchiveerd',
          gearchiveerd_op: '2026-08-26T09:00:00Z',
          gearchiveerd_door_naam: 'Peter',
        }),
      ],
    })
    renderScherm()
    await waitFor(() => expect(screen.getByText('Actieve Collega')).toBeInTheDocument())
    expect(screen.queryByText('Oud Account')).not.toBeInTheDocument()
    // Teller op de tab telt alleen actieven; het filter draagt de archief-telling.
    expect(screen.getByRole('tab', { name: 'Kantoor (1)' })).toBeInTheDocument()
    const filter = screen.getByRole('button', { name: 'gearchiveerd (1)' })
    expect(filter).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(filter)
    expect(screen.getByText('Oud Account')).toBeInTheDocument()
    expect(screen.queryByText('Actieve Collega')).not.toBeInTheDocument()
    expect(screen.getByText('gearchiveerd')).toBeInTheDocument()
    expect(screen.getByText(/gearchiveerd sinds .* door Peter/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dearchiveren' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Blokkeren' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Archiveren' })).not.toBeInTheDocument()
  })

  it('archiveren toont een bevestiging mét open-werk-aantallen en POST naar /archiveren', async () => {
    const postAanroepen: string[] = []
    installMock({
      gebruikers: [gebruiker({ id: ACCORDEUR_ID, naam: 'Test Accordeur', rol: 'klant_accordeur' })],
      postAanroepen,
      openWerk: { open_accorderingen: 2, weekstaten_ter_keuring: 0, eigen_open_weekstaten: 0 },
    })
    renderScherm('/gebruikers?groep=accordeurs')
    await waitFor(() => expect(screen.getByText('Test Accordeur')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Archiveren' }))
    await waitFor(() => expect(screen.getByText(/open werk: 2 open accorderingen/)).toBeInTheDocument())
    expect(screen.getByText(/er wordt niets verwijderd/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(postAanroepen).toContain(`/auth/gebruikers/${ACCORDEUR_ID}/archiveren`))
  })
})
