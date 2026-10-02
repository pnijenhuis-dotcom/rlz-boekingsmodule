/** Punt 10 run A (Peter 02-10 "als ik dan op het meerwerk regel klik zie ik de 'meerwerk bon', ik wil vanuit daar direct
 * door kunnen klikken naar het project"): in de veld-app draagt de meerwerkbon (vraag van het kantoor) een projectlink
 * ≥ 48 px terug naar de projectkaart; de meerwerkregels zélf staan op die kaart. */
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider, useAuth } from '../auth/AuthContext'
import { UrenFlow } from './UrenFlow'

function NaLogin({ children }: { children: React.ReactNode }) {
  const { status } = useAuth()
  return status === 'ingelogd' ? <>{children}</> : null
}

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const P1 = 'cccccccc-0000-0000-0000-000000000001'

function fakeToken(claims: Record<string, unknown>): string {
  return `kop.${btoa(JSON.stringify(claims))}.handtekening`
}
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const KAART = {
  administratie_id: ADM,
  administratie_naam: 'Universal Steigerbouw',
  project_id: P1,
  project_naam: '26149 Nijmegen (Dura Vermeer)',
  soort_werk: 'steigerbouw',
  contract_m2: '900',
  gebouwd_m2: '0',
  looptijd_tot: null,
  huurtijd_omschrijving: null,
  meerwerk_gemeld: 1,
  te_keuren: 0,
  gekoppeld: true,
}
const MELDING = {
  id: 'mw-1',
  administratie_id: ADM,
  project_id: P1,
  project_naam: KAART.project_naam,
  omschrijving: 'Extra trapsteiger achterzijde',
  aantal: '84',
  eenheid: 'm2',
  datum_uitgevoerd: '2026-09-30',
  in_opdracht_van: 'J. Timmers',
  heeft_foto: true,
  foto_bestandsnaam: 'foto.jpg',
  gemeld_door_naam: 'Irfan',
  gemeld_op: '2026-09-30T14:00:00Z',
  status: 'gemeld',
  prijs_per_eenheid: null,
  bedrag: null,
  facturatie_notitie: null,
  beoordeeld_op: null,
  beoordeeld_door_naam: null,
  afwijs_reden: null,
  doorbelast_op: null,
  verkoopfactuur_referentie: null,
  vraag_tekst: 'Welke zijde precies?',
  vraag_gesteld_op: '2026-10-01T08:00:00Z',
  vraag_antwoord: null,
  vraag_beantwoord_op: null,
}

function installMock() {
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: RequestInfo | URL) => {
      const url = String(invoer)
      const pad = url.split('?')[0]
      if (pad === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeToken({ rol: 'uitvoerder', sub: 'uitv-1' }) }))
      if (pad === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [{ id: ADM, naam: 'Universal Steigerbouw' }] }))
      if (pad === '/uren/uitvoerder/te-keuren') return Promise.resolve(jsonResponse([]))
      if (pad === '/uren/uitvoerder/projecten') return Promise.resolve(jsonResponse([KAART]))
      if (pad === `/uren/uitvoerder/projecten/${ADM}/${P1}`) {
        return Promise.resolve(
          jsonResponse({
            administratie_id: ADM,
            project_id: P1,
            project_naam: KAART.project_naam,
            opdrachtgever: 'Dura Vermeer',
            werknummer_opdrachtgever: null,
            soort_werk: 'steigerbouw',
            contract_m2: '900',
            gebouwd_m2: '0',
            looptijd_van: null,
            looptijd_tot: null,
            huurtijd_omschrijving: null,
            doorlopende_huur_omschrijving: null,
            documenten: [],
            meerwerk: [MELDING],
          }),
        )
      }
      if (pad === '/uren/dossier') return Promise.resolve(jsonResponse({ documenten: [], aantal_ontbrekend: 0, aantal_verlopen: 0, aantal_ter_controle: 0, aantal_verloopt_binnenkort: 0, aantal_aanwezig: 0, aantal_verplicht: 0, geblokkeerd: false, herinneringen_teller: 0, herinneringen_max: 3 }))
      if (pad === '/uren/zzp/weken-overzicht') return Promise.resolve(jsonResponse([]))
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('Veld-app — meerwerkbon ↔ projectkaart (punt 10 run A)', () => {
  it('de meerwerkbon draagt een projectlink (≥ 48 px-klasse) terug naar de projectkaart', async () => {
    installMock()
    render(
      <MemoryRouter>
        <AuthProvider>
          <NaLogin>
            <UrenFlow wisselThema={() => {}} uitloggen={() => Promise.resolve()} />
          </NaLogin>
        </AuthProvider>
      </MemoryRouter>,
    )
    // Projectenlijst → projectkaart (de meerwerkregels staan op de kaart zelf).
    const kaartKnop = await screen.findByRole('button', { name: /26149 Nijmegen/ })
    await userEvent.click(kaartKnop)
    await waitFor(() => expect(screen.getByText('Meerwerk (1)')).toBeInTheDocument())
    expect(screen.getByText('Extra trapsteiger achterzijde')).toBeInTheDocument()
    // Bon (vraag van het kantoor) → projectlink → terug op de kaart.
    await userEvent.click(screen.getByRole('button', { name: /Vraag van het kantoor — beantwoorden/ }))
    const link = await screen.findByTestId('naar-project')
    expect(link).toHaveClass('acc-tekstlink')
    expect(link).toHaveClass('acc-projectlink')
    expect(link).toHaveTextContent('26149 Nijmegen (Dura Vermeer)')
    await userEvent.click(link)
    await waitFor(() => expect(screen.getByText('Meerwerk (1)')).toBeInTheDocument())
  })
})
