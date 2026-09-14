/** Dialogen van het veldwerkers-beheer — dekking verhuisd uit gebruikers/VeldwerkersPanel.test.tsx (veldwerkers-run
 * 14-09): crediteur & tarieven (factuurmatch fase 3, 22-08) en de dialogen zonder picker-poort (fixrun 07-09 blok C3).
 * De ingang is nu /veldwerkers (VeldwerkersScreen); de dialogen zelf staan in VeldwerkerModals.tsx en
 * gebruikers/DossierModal.tsx. */
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { VeldgebruikerDto } from '../meerwerk/meerwerkApi'
import { VeldwerkersScreen } from './VeldwerkersScreen'

const ZZP_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'
const DETA_ID = 'bbbbbbbb-0000-0000-0000-00000000000b'
const ADMIN_A = 'aaaaaaaa-0000-0000-0000-00000000000a'
const ADMIN_B = 'bbbbbbbb-0000-0000-0000-00000000000b'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-00000000000e'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function veldGebruiker(overrides: Record<string, unknown>): VeldgebruikerDto {
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
    dossiers: [],
    administratie_ids: [ADMIN_B],
    ...overrides,
  } as VeldgebruikerDto
}

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

function installMock(
  veld: unknown[],
  administraties: { id: string; naam: string; uren_meerwerk_ingeschakeld?: boolean }[],
  aanroepen: string[] = [],
) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      aanroepen.push(url)
      if (url === '/uren/beheer/veldgebruikers') return Promise.resolve(jsonResponse(veld))
      if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties }))
      const dossier = url.match(/\/uren\/kantoor\/dossier\/([^/]+)\//)
      if (dossier) return Promise.resolve(jsonResponse(dossierAntwoord(dossier[1])))
      if (url.match(/\/administraties\/[^/]+\/crediteuren/)) return Promise.resolve(jsonResponse({ crediteuren: [] }))
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderScherm() {
  return render(
    <MemoryRouter initialEntries={['/veldwerkers']}>
      <VeldwerkersScreen />
    </MemoryRouter>,
  )
}

async function openMenuItem(naam: string, item: string) {
  const ge = userEvent.setup()
  await ge.click(await screen.findByRole('button', { name: `Meer acties voor ${naam}` }))
  await ge.click(await screen.findByRole('menuitem', { name: item }))
}

afterEach(() => vi.unstubAllGlobals())

const UNIVERSAL = { id: ADMIN_B, naam: 'Universal Steigerbouw', uren_meerwerk_ingeschakeld: true }

describe('crediteur & tarieven (factuurmatch fase 3) op /veldwerkers', () => {
  it('toont de crediteur-koppeling mét ZZP-uurtarief en de afwijkingswaarschuwing (kantoor-only)', async () => {
    installMock(
      [
        veldGebruiker({
          crediteuren: [
            { administratie_id: ADMIN_B, administratie_naam: 'Universal Steigerbouw', vendor_id: VENDOR_ID, vendor_naam: 'Milan K. Montage', uurtarief: '42.50', autoboeken_ingeschakeld: false },
          ],
          uren_afwijking_aantal: 2,
          uren_afwijking_som: '3.5',
        }),
      ],
      [UNIVERSAL],
    )
    renderScherm()
    await waitFor(() => expect(screen.getByText(/Milan K\. Montage/)).toBeInTheDocument())
    expect(screen.getByText(/€\s*42,50\/u/)).toBeInTheDocument()
    // Afwijkings-logging (besluit 22-08): optelbaar per veldwerker, alleen hier — kantoor.
    expect(screen.getByText(/2× correctie bij keuring/)).toBeInTheDocument()
    expect(screen.getByText(/3,5\s*u\s*meer ingediend dan goedgekeurd/)).toBeInTheDocument()
    // Autoboek-opt-in (fase 4) staat UIT — geen ⚡-badge; het menu-item heet dan "Crediteur/tarief…".
    expect(screen.queryByText(/⚡ autoboeken/)).not.toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Meer acties voor Milan K.' }))
    expect(await screen.findByRole('menuitem', { name: 'Crediteur/tarief…' })).toBeInTheDocument()
  })

  it('toont de ⚡-badge zodra de autoboek-opt-in (fase 4) op de koppeling aanstaat', async () => {
    installMock(
      [
        veldGebruiker({
          crediteuren: [
            { administratie_id: ADMIN_B, administratie_naam: 'Universal Steigerbouw', vendor_id: VENDOR_ID, vendor_naam: 'Milan K. Montage', uurtarief: '42.50', autoboeken_ingeschakeld: true },
          ],
        }),
      ],
      [UNIVERSAL],
    )
    renderScherm()
    await waitFor(() => expect(screen.getByText(/⚡ autoboeken/)).toBeInTheDocument())
  })

  it("toont zonder koppeling de hint en bij de detacheerder het bureau-tarief per ZZP'er; 'Bureau-tarieven…' opent de tarievendialoog", async () => {
    installMock(
      [
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
      ],
      [UNIVERSAL],
    )
    renderScherm()
    await waitFor(() => expect(screen.getAllByText(/zonder crediteur-koppeling geen factuurmatch/).length).toBe(2))
    expect(screen.getByText(/Milan K\. · €\s*51,00\/u/)).toBeInTheDocument()
    expect(screen.getByText(/Stefan B\. · geen tarief/)).toBeInTheDocument()
    await openMenuItem('Karin S.', 'Bureau-tarieven…')
    const dialoog = await screen.findByRole('dialog')
    expect(within(dialoog).getByText('Bureau-tarieven van Karin S.')).toBeInTheDocument()
    expect(within(dialoog).getByLabelText('Milan K.')).toHaveValue(51)
    expect(within(dialoog).getByLabelText('Stefan B.')).toHaveAttribute('placeholder', 'geen tarief bekend')
  })
})

describe('dialogen zonder picker-poort (C3, 07-09) op /veldwerkers', () => {
  it('dossier opent voorgeselecteerd met één administratie in scope — zonder picker', async () => {
    const aanroepen: string[] = []
    installMock([veldGebruiker({})], [UNIVERSAL], aanroepen)
    renderScherm()
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Dossier' }))

    await waitFor(() => expect(aanroepen.some((u) => u.includes(`/uren/kantoor/dossier/${ADMIN_B}/${ZZP_ID}`))).toBe(true))
    const dialoog = screen.getByRole('dialog')
    expect(within(dialoog).queryByLabelText('Administratie')).not.toBeInTheDocument()
    expect(within(dialoog).queryByTestId('standaard-administratie-uitleg')).not.toBeInTheDocument()
  })

  it('dossier via de badge in de Dossier-kolom: meerdere in scope → recentste planning voorgeselecteerd; de picker wisselt', async () => {
    const aanroepen: string[] = []
    installMock([veldGebruiker({ recentste_planning_administratie_id: ADMIN_B })], [{ id: ADMIN_A, naam: 'BLOW B.V.' }, UNIVERSAL], aanroepen)
    renderScherm()
    const ge = userEvent.setup()
    await ge.click(await screen.findByTitle('ZZP-dossier openen (documenten, KvK/btw, herinneringen)'))

    await waitFor(() => expect(aanroepen.some((u) => u.includes(`/uren/kantoor/dossier/${ADMIN_B}/`))).toBe(true))
    expect(aanroepen.some((u) => u.includes(`/uren/kantoor/dossier/${ADMIN_A}/`))).toBe(false)
    const dialoog = screen.getByRole('dialog')
    expect(within(dialoog).getByTestId('standaard-administratie-uitleg')).toHaveTextContent('recentste planning')

    // Wissel-filter: de picker blijft staan en wisselt naar BLOW.
    await ge.click(within(dialoog).getByLabelText('Administratie'))
    await ge.click(await screen.findByRole('option', { name: 'BLOW B.V.' }))
    await waitFor(() => expect(aanroepen.some((u) => u.includes(`/uren/kantoor/dossier/${ADMIN_A}/`))).toBe(true))
    expect(within(dialoog).queryByTestId('standaard-administratie-uitleg')).not.toBeInTheDocument()
  })

  it('crediteur koppelen: zonder koppeling of planning wint de administratie mét uren-&-meerwerk-opt-in (niet de eerste in de lijst)', async () => {
    const aanroepen: string[] = []
    installMock([veldGebruiker({})], [{ id: ADMIN_A, naam: 'BLOW B.V.' }, UNIVERSAL], aanroepen)
    renderScherm()
    await openMenuItem('Milan K.', 'Crediteur koppelen…')

    await waitFor(() => expect(aanroepen.some((u) => u.includes(`/administraties/${ADMIN_B}/crediteuren`))).toBe(true))
    expect(aanroepen.some((u) => u.includes(`/administraties/${ADMIN_A}/crediteuren`))).toBe(false)
    const dialoog = screen.getByRole('dialog')
    expect(within(dialoog).getByLabelText('Administratie')).toBeInTheDocument()
    expect(within(dialoog).getByTestId('standaard-administratie-uitleg')).toHaveTextContent('uren & meerwerk')
  })
})
