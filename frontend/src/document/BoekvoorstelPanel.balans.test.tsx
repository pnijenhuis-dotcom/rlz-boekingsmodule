import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

/** Punt 6 "Boeken prettig 1" (Peter 02-10): projecteis en projectverdeling gelden alleen voor KOSTENrekeningen (soort 2
 * uit de sync). Een regel op een balansrekening (voorraad 3xxx, activa 0xxx, tussenrekening) toont geen projectveld, telt
 * niet mee in "N regels zonder project" en wordt door "Alle regels — project" overgeslagen. Eigen testbestand náást
 * BoekvoorstelPanel.test.tsx (gedeeld bestand, parallelle bouwrun). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const GB_KOSTEN = 'cccccccc-0000-0000-0000-000000004110'
const GB_VOORRAAD = 'cccccccc-0000-0000-0000-000000003000'
const HOOG = 'dddddddd-0000-0000-0000-000000000021'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'
const TILBURG = 'ffffffff-0000-0000-0000-000000026127'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function regel(ledgerId: string, omschrijving: string) {
  return { id: null, ledger_id: ledgerId, taxrate_id: HOOG, project_id: null, netto_bedrag: '100.00', btw_bedrag: '21.00', omschrijving }
}

function installFetchMock(putBodies: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') return Promise.resolve(new Response(null, { status: 404 }))
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(
          jsonResponse({
            rekeningen: [
              { ledger_id: GB_KOSTEN, code: '4110', naam: 'Brandstof', soort: 2 },
              { ledger_id: GB_VOORRAAD, code: '3000', naam: 'Voorraad steigermateriaal', soort: 3 },
            ],
          }),
        )
      }
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [{ id: HOOG, naam: 'NL, Hoog Tarief', percentage: 0.21 }] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Universal Nederland' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [{ id: TILBURG, naam: '26127 Tilburg (Heijmans)' }] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: true }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            vendor_id: VENDOR_ID,
            referentie: 'RLZ-2080142625',
            factuurdatum: '2026-06-30',
            totaalbedrag: '242.00',
            rlz_boekstuknummer: null,
            opgeslagen: true,
            regels: [regel(GB_VOORRAAD, 'steigerdelen voorraad'), regel(GB_KOSTEN, 'brandstof diesel')],
            regels_samenvoegen: false,
            samenvoegen_toegestaan: false,
            samengevoegde_regel: null,
          }),
        )
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') {
        putBodies.push(JSON.parse(String(init.body)))
        return Promise.resolve(jsonResponse({ boekvoorstel: {}, checks: { geblokkeerd: false, resultaten: [] } }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderPanel(onVerdelenGevraagd?: () => void) {
  return render(
    <BoekvoorstelPanel
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      status="te_controleren"
      onGeboekt={() => {}}
      onHersteld={() => {}}
      onVerdelenGevraagd={onVerdelenGevraagd}
    />,
  )
}

describe('BoekvoorstelPanel — balansrekeningen zonder project (punt 6, 02-10)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('de voorraadregel heeft geen projectveld; alleen de kostenregel telt als "zonder project"', async () => {
    installFetchMock([])
    renderPanel(() => {})
    const balans = await screen.findByTestId('regel-project-balans')
    expect(balans).toHaveTextContent('— geen project (balansrekening)')
    expect(screen.getAllByTestId('regel-project-balans')).toHaveLength(1)
    // Eén projectcombobox (de kostenregel); de kop-combobox heet "Alle regels — project" en telt niet mee.
    expect(screen.getAllByLabelText('Project (verplicht)')).toHaveLength(1)
    expect(await screen.findByTestId('project-leeg-actie')).toHaveTextContent('1 regel zonder project')
  })

  it('"Alle regels — project" slaat de balansregel over en meldt het juiste aantal', async () => {
    const gebruiker = userEvent.setup()
    const putBodies: unknown[] = []
    installFetchMock(putBodies)
    renderPanel(() => {})
    const kop = await screen.findByTestId('kop-doorzetten')
    await gebruiker.click(within(kop).getByLabelText('Alle regels — project'))
    await gebruiker.click(await screen.findByRole('option', { name: /Tilburg/ }))
    await waitFor(() => expect(putBodies.length).toBeGreaterThan(0), { timeout: 4000 })
    const laatste = putBodies[putBodies.length - 1] as { regels: { project_id: string | null }[] }
    expect(laatste.regels.map((r) => r.project_id)).toEqual([null, TILBURG])
    const metVlag = putBodies.filter((b) => (b as { kop_doorgezet?: { project?: number } }).kop_doorgezet?.project)
    expect((metVlag[0] as { kop_doorgezet: { project: number } }).kop_doorgezet.project).toBe(1)
  })
})
