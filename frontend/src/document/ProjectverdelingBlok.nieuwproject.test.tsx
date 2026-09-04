import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProjectverdelingDto } from '../api/types'
import { ProjectverdelingBlok } from './ProjectverdelingBlok'

/* Fix C3 (04-09, besluit Peter): "+ Nieuw project aanmaken…" als vaste onderste rij in de
 * project-combobox — je verlaat het controlescherm niet meer voor een project dat nog niet
 * bestaat. Getest op de projectverdeling (zelfde wiring als de projectkolom van het
 * boekvoorstel): zichtbaarheid per rol, dialoog openen, en ná aanmaken de projectcache
 * herladen mét het nieuwe project meteen in díe regel. */

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOC = 'bbbbbbbb-0000-0000-0000-000000000002'
const TILBURG = 'cccccccc-0000-0000-0000-000000000011'
const NIEUW = 'cccccccc-0000-0000-0000-000000000099'

const rolMock = { rol: 'boekhouding' as string | null }
vi.mock('../auth/AuthContext', () => ({
  useAuthOptioneel: () => ({ rol: rolMock.rol }),
}))

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const MET_VAST: ProjectverdelingDto = {
  document_id: DOC,
  status: 'voorstel',
  opgeslagen: true,
  prefill: false,
  basisbedrag: '1000.00',
  vaste_regels: [{ project_id: TILBURG, bedrag: '600.00', hint: '', project_naam: '26127 Tilburg (Heijmans)' }],
  pro_rato: false,
  pro_rato_periode: null,
  pro_rato_periode_label: null,
  pro_rato_bedrag: '400.00',
  delen: [{ project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'vast', bedrag: '600.00' }],
  omzetstanden: [],
  aantal_projecten_met_omzet: 1,
  omzet_cache_leeg: false,
  compleet: false,
  blokkade: null,
  boek_cyclus: 0,
  hercontrole: null,
}

function installFetchMock() {
  let projectAangemaakt = false
  const projecten = () => [
    { id: TILBURG, naam: '26127 Tilburg (Heijmans)' },
    ...(projectAangemaakt ? [{ id: NIEUW, naam: '26128 Breda (Moeskops)' }] : []),
  ]
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith(`/administraties/${ADM}/projecten`)) return Promise.resolve(jsonResponse({ projecten: projecten() }))
      if (url.endsWith('/volgend-nummer')) return Promise.resolve(jsonResponse({ projectnummer: '26128' }))
      if (url.endsWith(`/projecten/${ADM}`) && method === 'POST') {
        projectAangemaakt = true
        return Promise.resolve(jsonResponse({ rlz_project_id: NIEUW, projectnaam: '26128 Breda (Moeskops)', bestond_al: false }, 201))
      }
      if (url.endsWith('/projectverdeling') && method === 'PUT') return Promise.resolve(jsonResponse(MET_VAST))
      if (url.endsWith('/projectverdeling')) return Promise.resolve(jsonResponse(MET_VAST))
      return Promise.resolve(jsonResponse({ detail: `onbekend pad ${url}` }, 404))
    }),
  )
}

function renderBlok() {
  return render(
    <ProjectverdelingBlok administratieId={ADM} documentId={DOC} status="te_controleren" soort="inkoopfactuur" boekvoorstelVersie={0} />,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  rolMock.rol = 'boekhouding'
})

describe('ProjectverdelingBlok — "+ Nieuw project aanmaken…" (fix C3 04-09)', () => {
  it('boekhouding ziet de voet-actie, maakt het project aan en het staat direct in die regel', async () => {
    installFetchMock()
    renderBlok()
    const veld = await screen.findByRole('combobox', { name: /Project \(vast\)/ })
    await userEvent.click(veld)

    const voet = screen.getByRole('button', { name: '+ Nieuw project aanmaken…' })
    await userEvent.click(voet)

    // Dialoog open mét het voorgestelde volgende vrije nummer.
    expect(await screen.findByText('Nieuw project')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText(/Projectnummer/)).toHaveValue('26128'))
    await userEvent.type(screen.getByLabelText(/Plaats/), 'Breda')
    await userEvent.type(screen.getByLabelText(/Opdrachtgever/), 'Moeskops')
    expect(screen.getByText('26128 Breda (Moeskops)')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Aanmaken in RLZ' }))

    // Dialoog dicht; het nieuwe project staat geselecteerd in de vaste regel (projectcache
    // herladen via de herlaadsleutel).
    await waitFor(() => expect(screen.queryByText('Nieuw project')).not.toBeInTheDocument())
    await waitFor(() =>
      expect(screen.getByRole('combobox', { name: /Project \(vast\)/ })).toHaveValue('26128 Breda (Moeskops)'),
    )
  })

  it('een niet-kantoorrol ziet de voet-actie niet (fail-closed, spiegel van de backend-poort)', async () => {
    rolMock.rol = 'klant_accordeur'
    installFetchMock()
    renderBlok()
    await userEvent.click(await screen.findByRole('combobox', { name: /Project \(vast\)/ }))
    expect(screen.queryByRole('button', { name: '+ Nieuw project aanmaken…' })).not.toBeInTheDocument()
  })
})
