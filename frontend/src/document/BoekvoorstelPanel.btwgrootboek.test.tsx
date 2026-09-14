import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

/** Btw-code volgt de standaard van de grootboekrekening (opdracht Peter 14-09, casus L.H.G. Holding "Kosten mobiele
 * telefonie"): de grootboek-lijst draagt `standaard_taxrate_id`; kiest de mens (een andere) rekening, dan volgt de
 * btw-code die standaard mét chip "standaard grootboek" — zolang de btw niet van de mens is. Eigen testbestand náást
 * BoekvoorstelPanel.regelvoorstel.test.tsx (zelfde mock-patroon). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const GB_4403 = 'cccccccc-0000-0000-0000-000000004403' // Telefoonkosten — geen default in RLZ
const GB_4404 = 'cccccccc-0000-0000-0000-000000004404' // Kosten mobiele telefonie — default hoog
const GB_4405 = 'cccccccc-0000-0000-0000-000000004405' // Internetkosten — default verwijst naar een verdwenen tarief
const TAXRATE_HOOG = 'dddddddd-0000-0000-0000-000000000021'
const TAXRATE_LAAG = 'dddddddd-0000-0000-0000-000000000009'
const TAXRATE_VERDWENEN = 'dddddddd-0000-0000-0000-000000000099'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function regel(overrides: Record<string, unknown>) {
  return {
    id: null,
    ledger_id: null,
    taxrate_id: null,
    project_id: null,
    netto_bedrag: '100.00',
    btw_bedrag: null,
    omschrijving: 'Abonnement mobiel',
    btw_bron: null,
    gb_bron: null,
    gb_voorstel_detail: null,
    ...overrides,
  }
}

function installFetchMock(regels: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') return Promise.resolve(new Response(null, { status: 404 }))
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(
          jsonResponse({
            rekeningen: [
              { ledger_id: GB_4403, code: '4403', naam: 'Telefoonkosten', soort: 2, standaard_taxrate_id: null },
              { ledger_id: GB_4404, code: '4404', naam: 'Kosten mobiele telefonie', soort: 2, standaard_taxrate_id: TAXRATE_HOOG },
              { ledger_id: GB_4405, code: '4405', naam: 'Internetkosten', soort: 2, standaard_taxrate_id: TAXRATE_VERDWENEN },
            ],
          }),
        )
      }
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(
          jsonResponse({
            btw_codes: [
              { id: TAXRATE_HOOG, naam: 'NL, Hoog Tarief', percentage: 0.21 },
              { id: TAXRATE_LAAG, naam: 'NL, Laag Tarief', percentage: 0.09 },
            ],
          }),
        )
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'KPN B.V.' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            vendor_id: VENDOR_ID,
            referentie: 'KPN-2026-0914',
            factuurdatum: '2026-09-01',
            totaalbedrag: '121.00',
            rlz_boekstuknummer: null,
            opgeslagen: false,
            regels,
            regels_samenvoegen: false,
            samenvoegen_toegestaan: true,
            samengevoegde_regel: null,
          }),
        )
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') return Promise.resolve(jsonResponse({}))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderPanel() {
  return render(
    <BoekvoorstelPanel administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} status="te_controleren" onGeboekt={() => {}} onHersteld={() => {}} />,
  )
}

async function kiesGrootboek(gebruiker: ReturnType<typeof userEvent.setup>, naam: RegExp) {
  await gebruiker.click(screen.getAllByLabelText('Grootboek', { exact: false })[0])
  await gebruiker.click(await screen.findByRole('option', { name: naam }))
}

describe('BoekvoorstelPanel — btw volgt de standaard van de grootboekrekening (14-09)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('server-prefill mét btw_bron grootboek = grijze chip "standaard grootboek"', async () => {
    installFetchMock([regel({ ledger_id: GB_4404, taxrate_id: TAXRATE_HOOG, btw_bron: 'grootboek', btw_bedrag: '21.00' })])
    renderPanel()
    const btwVeld = (await screen.findAllByLabelText('Btw-code', { exact: false }))[0]
    await waitFor(() => expect(btwVeld).toHaveValue('21% · NL, Hoog Tarief'))
    const chip = screen.getByTestId('regel-btw-standaard-chip')
    expect(chip).toHaveTextContent('standaard grootboek')
    expect(chip).toHaveClass('chip', 'handmatig')
    expect(chip).toHaveAttribute('data-bron', 'grootboek')
  })

  it('kies "Kosten mobiele telefonie" → btw-code én btw-bedrag volgen de standaard, chip verschijnt', async () => {
    installFetchMock([regel({})])
    const gebruiker = userEvent.setup()
    renderPanel()
    await screen.findAllByLabelText('Grootboek', { exact: false })
    await waitFor(() => expect(screen.queryByText('Grootboek laden…')).toBeNull())
    await kiesGrootboek(gebruiker, /Kosten mobiele telefonie/)
    const btwVeld = screen.getAllByLabelText('Btw-code', { exact: false })[0]
    await waitFor(() => expect(btwVeld).toHaveValue('21% · NL, Hoog Tarief'))
    expect(screen.getByTestId('regel-btw-standaard-chip')).toHaveTextContent('standaard grootboek')
    expect(screen.getAllByLabelText('Btw bedrag')[0]).toHaveValue('21,00')

    // Wissel naar een rekening zónder default: de gevolgde btw gaat weg (nooit de default van een andere rekening).
    await kiesGrootboek(gebruiker, /Telefoonkosten/)
    await waitFor(() => expect(btwVeld).toHaveValue(''))
    expect(screen.queryByTestId('regel-btw-standaard-chip')).toBeNull()
  })

  it('mens koos zelf een btw-code → een grootboek-wissel raakt die niet', async () => {
    installFetchMock([regel({})])
    const gebruiker = userEvent.setup()
    renderPanel()
    await screen.findAllByLabelText('Btw-code', { exact: false })
    await gebruiker.click(screen.getAllByLabelText('Btw-code', { exact: false })[0])
    await gebruiker.click(await screen.findByRole('option', { name: /NL, Laag Tarief/ }))
    const btwVeld = screen.getAllByLabelText('Btw-code', { exact: false })[0]
    await waitFor(() => expect(btwVeld).toHaveValue('9% · NL, Laag Tarief'))
    await kiesGrootboek(gebruiker, /Kosten mobiele telefonie/)
    await waitFor(() => expect(screen.getAllByLabelText('Grootboek', { exact: false })[0]).toHaveValue('4404 · Kosten mobiele telefonie'))
    expect(btwVeld).toHaveValue('9% · NL, Laag Tarief')
    expect(screen.queryByTestId('regel-btw-standaard-chip')).toBeNull()
  })

  it('een default die naar een verdwenen tarief verwijst vult nooit; een btw uit de factuur blijft staan', async () => {
    installFetchMock([regel({ taxrate_id: TAXRATE_LAAG, btw_bron: 'factuur', btw_bedrag: '9.00' })])
    const gebruiker = userEvent.setup()
    renderPanel()
    const btwVeld = (await screen.findAllByLabelText('Btw-code', { exact: false }))[0]
    await waitFor(() => expect(btwVeld).toHaveValue('9% · NL, Laag Tarief'))
    await kiesGrootboek(gebruiker, /Internetkosten/)
    await waitFor(() => expect(screen.getAllByLabelText('Grootboek', { exact: false })[0]).toHaveValue('4405 · Internetkosten'))
    expect(btwVeld).toHaveValue('9% · NL, Laag Tarief')
    // Rekening mét default wint NIET van de factuur-afleiding: de server-winnaarsvolgorde (factuur > geheugen > grootboek)
    // geldt óók client-side — alleen een lege, grootboek-gevolgde of administratie-default-btw volgt de rekening.
    await kiesGrootboek(gebruiker, /Kosten mobiele telefonie/)
    await waitFor(() => expect(screen.getAllByLabelText('Grootboek', { exact: false })[0]).toHaveValue('4404 · Kosten mobiele telefonie'))
    expect(btwVeld).toHaveValue('9% · NL, Laag Tarief')
  })
})
