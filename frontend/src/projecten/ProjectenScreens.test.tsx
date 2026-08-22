/** Projectenmodule (mockup projecten-invoer.html, akkoord Peter 22-08): lijst mét
 * compleetheids-badges + zonder-specs-teller, nieuw-project-modal met naamconventie-preview,
 * resultaat-detail (tegels + weektabel + onbepaalbaar-waarschuwing) en het cumulatieve
 * overzicht (totalen + signalen). */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProjectenScreen } from './ProjectenScreen'
import { ProjectResultaatScreen } from './ProjectResultaatScreen'
import { ProjectenOverzichtScreen } from './ProjectenOverzichtScreen'

const ADMINISTRATIE_ID = 'dddddddd-0000-0000-0000-00000000000d'
const PROJECT_ID = 'aaaaaaaa-0000-0000-0000-00000000000a'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installMock(handlers: Record<string, () => Response>) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/auth/administraties'))
        return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'Universal Steigerbouw' }] }))
      for (const [fragment, handler] of Object.entries(handlers)) {
        if (url.includes(fragment)) return Promise.resolve(handler())
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('ProjectenScreen (lijst)', () => {
  it('toont badges, voortgang en de zonder-specs-teller', async () => {
    installMock({
      '/volgend-nummer': () => jsonResponse({ projectnummer: '26127' }),
      [`/projecten/${ADMINISTRATIE_ID}`]: () =>
        jsonResponse({
          projecten: [
            {
              project_id: PROJECT_ID,
              naam: '144 Breda (Moeskops)',
              is_actief: true,
              opdrachtgever: 'Moeskops Bouw',
              werknummer_opdrachtgever: 'BAM-88412',
              specs_status: 'compleet',
              documenten: { contract: 1, offerte: 1 },
              staffels: 4,
              gebouwd_m2: '3280',
              contract_m2: '4200',
              doorlopende_huur: false,
              heeft_activiteit: true,
            },
            {
              project_id: 'bbbbbbbb-0000-0000-0000-00000000000b',
              naam: '25013 Deurne (Bots)',
              is_actief: true,
              opdrachtgever: null,
              werknummer_opdrachtgever: null,
              specs_status: 'geen',
              documenten: {},
              staffels: 0,
              gebouwd_m2: '0',
              contract_m2: null,
              doorlopende_huur: false,
              heeft_activiteit: true,
            },
          ],
          zonder_specs: 1,
        }),
    })
    render(
      <MemoryRouter initialEntries={[`/projecten?administratie=${ADMINISTRATIE_ID}`]}>
        <Routes>
          <Route path="/projecten" element={<ProjectenScreen />} />
        </Routes>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('144 Breda (Moeskops)')).toBeInTheDocument())
    expect(screen.getByText('1 zonder specs')).toBeInTheDocument()
    expect(screen.getByText('compleet')).toBeInTheDocument()
    expect(screen.getByText('contract + offerte')).toBeInTheDocument()
    expect(screen.getByText('4 regels')).toBeInTheDocument()
    expect(screen.getByText(/3\.280 \/ 4\.200 m²/)).toBeInTheDocument()
    expect(screen.getByText(/78%/)).toBeInTheDocument()
    // Nieuw project: naamconventie-preview verschijnt zodra de velden gevuld zijn.
    fireEvent.click(screen.getByRole('button', { name: '+ Nieuw project' }))
    await waitFor(() => expect(screen.getByLabelText(/Projectnummer/)).toHaveValue('26127'))
    fireEvent.change(screen.getByLabelText(/Plaats/), { target: { value: 'Tilburg' } })
    fireEvent.change(screen.getByLabelText(/Opdrachtgever/), { target: { value: 'Heijmans' } })
    expect(screen.getByText('26127 Tilburg (Heijmans)')).toBeInTheDocument()
  })
})

describe('ProjectResultaatScreen', () => {
  it('toont de vier tegels, de weektabel en de onbepaalbaar-waarschuwing', async () => {
    installMock({
      '/resultaat': () =>
        jsonResponse({
          project_id: PROJECT_ID,
          project_naam: '144 Breda (Moeskops)',
          opdrachtgever: 'Moeskops',
          baten_geboekt: '128400.00',
          kosten_geboekt: '96150.00',
          uren_onderweg_bedrag: '9860.00',
          uren_onderweg_uren: '210',
          onbepaalbaar_uren: '12.5',
          meerwerk_onderweg_bedrag: '2620.00',
          onderweg_saldo: '-7240.00',
          verwachte_marge: '25010.00',
          marge_pct: '19.1',
          weken: [
            {
              jaar: 2026,
              weeknummer: 31,
              baten: '42800.00',
              kosten_geboekt: '18410.00',
              kosten_onderweg: '0',
              onderweg_onbepaalbaar_uren: '0',
              saldo: '24390.00',
              cumulatief: '24390.00',
              baten_detail: ['termijn 2'],
              kosten_detail: [],
            },
            {
              jaar: 2026,
              weeknummer: 33,
              baten: '0',
              kosten_geboekt: '21300.00',
              kosten_onderweg: '3120.00',
              onderweg_onbepaalbaar_uren: '0',
              saldo: '-24420.00',
              cumulatief: '-30.00',
              baten_detail: [],
              kosten_detail: ['uit weekstaten'],
            },
          ],
        }),
    })
    render(
      <MemoryRouter initialEntries={[`/projecten/${ADMINISTRATIE_ID}/${PROJECT_ID}/resultaat`]}>
        <Routes>
          <Route path="/projecten/:administratieId/:projectId/resultaat" element={<ProjectResultaatScreen />} />
        </Routes>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('Resultaat — 144 Breda (Moeskops)')).toBeInTheDocument())
    expect(screen.getByText('Baten gefactureerd (RLZ)')).toBeInTheDocument()
    expect(screen.getByText(/128\.400/)).toBeInTheDocument()
    expect(screen.getByText(/19,1%/)).toBeInTheDocument()
    expect(screen.getByText(/12,5 getekende uren zónder tarief/)).toBeInTheDocument()
    expect(screen.getByText('wk 31')).toBeInTheDocument()
    expect(screen.getByText('termijn 2')).toBeInTheDocument()
    expect(screen.getByText('uit weekstaten')).toBeInTheDocument()
  })
})

describe('ProjectenOverzichtScreen', () => {
  it('toont totaal-tegels en de signalen per project (laagste marge eerst uit de backend)', async () => {
    installMock({
      '/resultaat-overzicht': () =>
        jsonResponse({
          baten_totaal: '486900.00',
          kosten_totaal_incl_onderweg: '391320.00',
          uren_onderweg_totaal: '31480.00',
          onbepaalbaar_uren_totaal: '0',
          meerwerk_onderweg_totaal: '2620.00',
          marge_totaal: '95580.00',
          marge_pct: '19.6',
          aandacht: 2,
          rijen: [
            {
              project_id: PROJECT_ID,
              project_naam: '25013 Deurne',
              opdrachtgever: 'Bots Bouwgroep',
              baten: '18200.00',
              kosten_incl_onderweg: '21940.00',
              marge: '-3740.00',
              marge_pct: '-20.5',
              trend: 'dalend',
              kosten_zonder_omzet_weken: 3,
              meerwerk_te_lang_niet_doorbelast: 0,
              doorlopende_huur: false,
              onbepaalbaar_uren: '0',
            },
            {
              project_id: 'bbbbbbbb-0000-0000-0000-00000000000b',
              project_naam: '25011 Zwolle',
              opdrachtgever: 'Ben Kuijer',
              baten: '61080.00',
              kosten_incl_onderweg: '38900.00',
              marge: '22180.00',
              marge_pct: '36.3',
              trend: 'stijgend',
              kosten_zonder_omzet_weken: 0,
              meerwerk_te_lang_niet_doorbelast: 0,
              doorlopende_huur: true,
              onbepaalbaar_uren: '0',
            },
          ],
        }),
    })
    render(
      <MemoryRouter initialEntries={[`/projecten-resultaat?administratie=${ADMINISTRATIE_ID}`]}>
        <Routes>
          <Route path="/projecten-resultaat" element={<ProjectenOverzichtScreen />} />
        </Routes>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('Resultaat — alle actieve projecten')).toBeInTheDocument())
    expect(screen.getByText(/486\.900/)).toBeInTheDocument()
    expect(screen.getByText(/waarvan .*31\.480.* uren-onderweg/)).toBeInTheDocument()
    expect(screen.getByText('2 projecten')).toBeInTheDocument()
    expect(screen.getByText('kosten zonder omzet 3 wkn')).toBeInTheDocument()
    expect(screen.getByText('doorlopende huur loopt')).toBeInTheDocument()
    expect(screen.getByText('▼ dalend')).toBeInTheDocument()
  })
})
