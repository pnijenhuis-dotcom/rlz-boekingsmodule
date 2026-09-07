/** Veldwerkers-paneel (factuurmatch fase 3, 22-08): crediteur-koppeling + tarieven zichtbaar,
 * bureau-tarief per gekoppelde ZZP'er op de detacheerder-rij, en de kantoor-only
 * afwijkingsstatistiek (afkeuringen mét correctievoorstel) als waarschuwing. */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GebruikerOverzichtDto } from './gebruikersApi'
import { VeldwerkersPanel } from './VeldwerkersPanel'

const ZZP_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const DETA_ID = 'bbbbbbbb-0000-0000-0000-00000000000b'
const ADMINISTRATIE_ID = 'dddddddd-0000-0000-0000-00000000000d'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-00000000000e'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function veldGebruiker(overrides: Record<string, unknown>) {
  return {
    gebruiker_id: ZZP_ID,
    naam: 'Milan K.',
    e_mail: 'milan@test.local',
    rol: 'zzper',
    status: 'actief',
    projecten: [],
    zzpers: [],
    crediteuren: [],
    uren_afwijking_aantal: 0,
    uren_afwijking_som: '0',
    ...overrides,
  }
}

function overzichtGebruiker(overrides: Record<string, unknown>): GebruikerOverzichtDto {
  return {
    id: ZZP_ID,
    naam: 'Milan K.',
    e_mail: 'milan@test.local',
    rol: 'zzper',
    status: 'actief',
    administratie_ids: [],
    heeft_totp: false,
    aantal_passkeys: 1,
    open_uitnodiging_verloopt_op: null,
    staande_goedkeuringen: 0,
    ...overrides,
  } as unknown as GebruikerOverzichtDto
}

function installMock(veld: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/uren/beheer/veldgebruikers')) return Promise.resolve(jsonResponse(veld))
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderPaneel(gebruikers: GebruikerOverzichtDto[]) {
  return render(
    <VeldwerkersPanel
      gebruikers={gebruikers}
      administraties={[{ id: ADMINISTRATIE_ID, naam: 'Universal Steigerbouw' } as never]}
      onUitnodigen={() => {}}
      actieKolom={() => null}
    />,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('VeldwerkersPanel — crediteur & tarieven (factuurmatch fase 3)', () => {
  it('toont de crediteur-koppeling mét ZZP-uurtarief en de afwijkingswaarschuwing (kantoor-only)', async () => {
    installMock([
      veldGebruiker({
        crediteuren: [
          {
            administratie_id: ADMINISTRATIE_ID,
            administratie_naam: 'Universal Steigerbouw',
            vendor_id: VENDOR_ID,
            vendor_naam: 'Milan K. Montage',
            uurtarief: '42.50',
            autoboeken_ingeschakeld: false,
          },
        ],
        uren_afwijking_aantal: 2,
        uren_afwijking_som: '3.5',
      }),
    ])
    renderPaneel([overzichtGebruiker({})])
    await waitFor(() => expect(screen.getByText(/Milan K\. Montage/)).toBeInTheDocument())
    expect(screen.getByText(/€\s*42,50\/u/)).toBeInTheDocument()
    expect(screen.getByText('crediteur/tarief')).toBeInTheDocument()
    // afwijkings-logging (besluit 22-08): optelbaar per veldwerker, alleen hier — kantoor
    expect(screen.getByText(/2× correctie bij keuring/)).toBeInTheDocument()
    expect(screen.getByText(/3,5\s*u\s*meer ingediend dan goedgekeurd/)).toBeInTheDocument()
    // Autoboek-opt-in (fase 4) staat UIT — geen ⚡-badge.
    expect(screen.queryByText(/⚡ autoboeken/)).not.toBeInTheDocument()
  })

  it('toont de ⚡-badge zodra de autoboek-opt-in (fase 4) op de koppeling aanstaat', async () => {
    installMock([
      veldGebruiker({
        crediteuren: [
          {
            administratie_id: ADMINISTRATIE_ID,
            administratie_naam: 'Universal Steigerbouw',
            vendor_id: VENDOR_ID,
            vendor_naam: 'Milan K. Montage',
            uurtarief: '42.50',
            autoboeken_ingeschakeld: true,
          },
        ],
      }),
    ])
    renderPaneel([overzichtGebruiker({})])
    await waitFor(() => expect(screen.getByText(/⚡ autoboeken/)).toBeInTheDocument())
  })

  it('toont zonder koppeling de koppel-knop + hint en bij de detacheerder het bureau-tarief per ZZP\'er', async () => {
    installMock([
      veldGebruiker({}),
      veldGebruiker({
        gebruiker_id: DETA_ID,
        naam: 'Karin S.',
        rol: 'detacheerder',
        zzpers: [
          { gebruiker_id: ZZP_ID, naam: 'Milan K.', uurtarief: '51.00' },
          { gebruiker_id: 'ffffffff-0000-0000-0000-00000000000f', naam: 'Stefan B.', uurtarief: null },
        ],
      }),
    ])
    renderPaneel([
      overzichtGebruiker({}),
      overzichtGebruiker({ id: DETA_ID, naam: 'Karin S.', rol: 'detacheerder' }),
    ])
    await waitFor(() => expect(screen.getAllByText('crediteur koppelen').length).toBe(2))
    expect(screen.getAllByText(/zonder crediteur-koppeling geen factuurmatch/).length).toBeGreaterThan(0)
    expect(screen.getByText(/Milan K\. · €\s*51,00\/u/)).toBeInTheDocument()
    expect(screen.getByText(/Stefan B\. · geen tarief/)).toBeInTheDocument()
    expect(screen.getByText('tarieven…')).toBeInTheDocument()
  })
})


/* Fixrun 07-09 blok C3: de dialogen openen VOORGESELECTEERD — geen administratie-picker als poort
 * (kernprincipe 7). De picker blijft als wissel-filter. */
const ADMIN_A = 'aaaaaaaa-0000-0000-0000-00000000000a'
const ADMIN_B = 'bbbbbbbb-0000-0000-0000-00000000000b'

function dossierAntwoord(administratieId: string) {
  return {
    administratie_id: administratieId,
    gebruiker_id: ZZP_ID,
    gebruiker_naam: 'Milan K.',
    documenten: [],
    aantal_verplicht: 0,
    aantal_aanwezig: 0,
    aantal_ontbrekend: 0,
    aantal_verlopen: 0,
    aantal_verloopt_binnenkort: 0,
    aantal_ter_controle: 0,
    compleet: true,
    compleet_incl_ter_controle: true,
    herinneringen_teller: 0,
    herinneringen_max: 3,
    laatste_herinnering_op: null,
    geblokkeerd: false,
    geblokkeerd_op: null,
    kan_herinneren_vandaag: true,
    kvk_nummer: null,
    btw_nummer: null,
    kvk_naam: null,
    kvk_plaats: null,
    kvk_rechtsvorm: null,
    kvk_bevestigd_op: null,
    kvk_bevestigd_door_naam: null,
    signalen: [],
  }
}

function installDialoogMock(veld: unknown[], aanroepen: string[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      aanroepen.push(url)
      if (url.includes('/uren/beheer/veldgebruikers')) return Promise.resolve(jsonResponse(veld))
      const dossier = url.match(/\/uren\/kantoor\/dossier\/([^/]+)\//)
      if (dossier) return Promise.resolve(jsonResponse(dossierAntwoord(dossier[1])))
      if (url.match(/\/administraties\/[^/]+\/crediteuren/)) return Promise.resolve(jsonResponse({ crediteuren: [] }))
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderMetScope(
  gebruikers: GebruikerOverzichtDto[],
  administraties: { id: string; naam: string; uren_meerwerk_ingeschakeld?: boolean }[],
) {
  return render(
    <VeldwerkersPanel gebruikers={gebruikers} administraties={administraties} onUitnodigen={() => {}} actieKolom={() => null} />,
  )
}

describe('VeldwerkersPanel — dialogen zonder picker-poort (C3, 07-09)', () => {
  it('dossier opent voorgeselecteerd met één administratie in scope — zonder picker', async () => {
    const aanroepen: string[] = []
    installDialoogMock([veldGebruiker({ dossiers: [] })], aanroepen)
    renderMetScope([overzichtGebruiker({})], [{ id: ADMIN_B, naam: 'Universal Steigerbouw', uren_meerwerk_ingeschakeld: true }])
    await userEvent.click(await screen.findByTitle('ZZP-dossier openen (documenten, KvK/btw, herinneringen)'))

    await waitFor(() => expect(aanroepen.some((u) => u.includes(`/uren/kantoor/dossier/${ADMIN_B}/${ZZP_ID}`))).toBe(true))
    const dialoog = screen.getByRole('dialog')
    expect(within(dialoog).queryByLabelText('Administratie')).not.toBeInTheDocument()
    expect(within(dialoog).queryByTestId('standaard-administratie-uitleg')).not.toBeInTheDocument()
  })

  it('dossier: meerdere in scope → recentste planning voorgeselecteerd; de picker wisselt naar een andere administratie', async () => {
    const aanroepen: string[] = []
    installDialoogMock([veldGebruiker({ dossiers: [], recentste_planning_administratie_id: ADMIN_B })], aanroepen)
    renderMetScope(
      [overzichtGebruiker({})],
      [
        { id: ADMIN_A, naam: 'BLOW B.V.' },
        { id: ADMIN_B, naam: 'Universal Steigerbouw', uren_meerwerk_ingeschakeld: true },
      ],
    )
    await userEvent.click(await screen.findByTitle('ZZP-dossier openen (documenten, KvK/btw, herinneringen)'))

    await waitFor(() => expect(aanroepen.some((u) => u.includes(`/uren/kantoor/dossier/${ADMIN_B}/`))).toBe(true))
    expect(aanroepen.some((u) => u.includes(`/uren/kantoor/dossier/${ADMIN_A}/`))).toBe(false)
    const dialoog = screen.getByRole('dialog')
    expect(within(dialoog).getByTestId('standaard-administratie-uitleg')).toHaveTextContent('recentste planning')

    // Wissel-filter: de picker blijft staan en wisselt naar BLOW.
    await userEvent.click(within(dialoog).getByLabelText('Administratie'))
    await userEvent.click(await screen.findByRole('option', { name: 'BLOW B.V.' }))
    await waitFor(() => expect(aanroepen.some((u) => u.includes(`/uren/kantoor/dossier/${ADMIN_A}/`))).toBe(true))
    expect(within(dialoog).queryByTestId('standaard-administratie-uitleg')).not.toBeInTheDocument()
  })

  it('crediteur koppelen: zonder koppeling of planning wint de administratie mét uren-&-meerwerk-opt-in (niet de eerste in de lijst)', async () => {
    const aanroepen: string[] = []
    installDialoogMock([veldGebruiker({ dossiers: [] })], aanroepen)
    renderMetScope(
      [overzichtGebruiker({})],
      [
        { id: ADMIN_A, naam: 'BLOW B.V.' },
        { id: ADMIN_B, naam: 'Universal Steigerbouw', uren_meerwerk_ingeschakeld: true },
      ],
    )
    await userEvent.click(await screen.findByRole('button', { name: 'crediteur koppelen' }))

    await waitFor(() => expect(aanroepen.some((u) => u.includes(`/administraties/${ADMIN_B}/crediteuren`))).toBe(true))
    expect(aanroepen.some((u) => u.includes(`/administraties/${ADMIN_A}/crediteuren`))).toBe(false)
    const dialoog = screen.getByRole('dialog')
    expect(within(dialoog).getByLabelText('Administratie')).toBeInTheDocument()
    expect(within(dialoog).getByTestId('standaard-administratie-uitleg')).toHaveTextContent('uren & meerwerk')
  })
})
