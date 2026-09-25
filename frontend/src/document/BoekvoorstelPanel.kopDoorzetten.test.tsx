import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

/** FV-07 (feedbackrun A 25-09): project en btw-code één keer op factuurniveau kiezen → doorgezet naar álle regels (per
 * regel daarna overschrijfbaar); de eerstvolgende PUT draagt `kop_doorgezet` (server-tijdlijn "kop → regels"). FV-12: de
 * knop "Verdelen over projecten" bij het regelblok. Eigen testbestand náást BoekvoorstelPanel.test.tsx (gedeeld bestand,
 * parallelle bouwrun). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const GB = 'cccccccc-0000-0000-0000-000000004110'
const HOOG = 'dddddddd-0000-0000-0000-000000000021'
const LAAG = 'dddddddd-0000-0000-0000-000000000009'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'
const TILBURG = 'ffffffff-0000-0000-0000-000000026127'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function regel(omschrijving: string) {
  return { id: null, ledger_id: GB, taxrate_id: HOOG, project_id: null, netto_bedrag: '100.00', btw_bedrag: '21.00', omschrijving }
}

function installFetchMock(putBodies: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') return Promise.resolve(new Response(null, { status: 404 }))
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: GB, code: '4110', naam: 'Steigerhuur', soort: 2 }] }))
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(
          jsonResponse({
            btw_codes: [
              { id: HOOG, naam: 'NL, Hoog Tarief', percentage: 0.21 },
              { id: LAAG, naam: 'NL, Laag Tarief', percentage: 0.09 },
            ],
          }),
        )
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Floor' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [{ id: TILBURG, naam: '26127 Tilburg (Heijmans)' }] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: true }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            vendor_id: VENDOR_ID,
            referentie: '26219',
            factuurdatum: '2026-08-28',
            totaalbedrag: '363.00',
            rlz_boekstuknummer: null,
            opgeslagen: true,
            regels: [regel('huur'), regel('montage'), regel('transport')],
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

describe('BoekvoorstelPanel — kop → regels (FV-07) en Verdelen-knop (FV-12), 25-09', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('btw-code op factuurniveau zet alle drie de regels om (btw herrekend) en reist één keer als kop_doorgezet mee', async () => {
    const gebruiker = userEvent.setup()
    const putBodies: unknown[] = []
    installFetchMock(putBodies)
    renderPanel()
    const kop = await screen.findByTestId('kop-doorzetten')
    const btwKop = within(kop).getByLabelText('Alle regels — btw')
    await gebruiker.click(btwKop)
    await gebruiker.click(await screen.findByRole('option', { name: /Laag/ }))
    // Alle regels dragen nu het lage tarief én een herrekend btw-bedrag (18-09-regel: btw volgt het tarief).
    const btwVelden = screen.getAllByLabelText('Btw bedrag') as HTMLInputElement[]
    await waitFor(() => expect(btwVelden.map((v) => v.value)).toEqual(['9,00', '9,00', '9,00']))
    await waitFor(() => expect(putBodies.length).toBeGreaterThan(0), { timeout: 4000 })
    const metVlag = putBodies.filter((b) => (b as { kop_doorgezet?: unknown }).kop_doorgezet)
    expect(metVlag.length).toBe(1)
    expect((metVlag[0] as { kop_doorgezet: unknown }).kop_doorgezet).toEqual({ btw: 3, btw_code: 'NL, Laag Tarief' })
    expect((putBodies[putBodies.length - 1] as { regels: { taxrate_id: string }[] }).regels.every((r) => r.taxrate_id === LAAG)).toBe(true)
  })

  it('project op factuurniveau zet alle regels om; de knop "Verdelen over projecten" staat bij het regelblok', async () => {
    const gebruiker = userEvent.setup()
    const putBodies: unknown[] = []
    installFetchMock(putBodies)
    const onVerdelen = vi.fn()
    renderPanel(onVerdelen)
    const kop = await screen.findByTestId('kop-doorzetten')
    await gebruiker.click(within(kop).getByLabelText('Alle regels — project'))
    await gebruiker.click(await screen.findByRole('option', { name: /Tilburg/ }))
    await waitFor(() => expect(putBodies.length).toBeGreaterThan(0), { timeout: 4000 })
    const laatste = putBodies[putBodies.length - 1] as { regels: { project_id: string | null }[]; kop_doorgezet?: unknown }
    expect(laatste.regels.map((r) => r.project_id)).toEqual([TILBURG, TILBURG, TILBURG])
    expect(putBodies.some((b) => JSON.stringify((b as { kop_doorgezet?: unknown }).kop_doorgezet ?? null).includes('"project":3'))).toBe(true)
    const knop = screen.getByTestId('verdelen-knop')
    expect(knop).toHaveClass('btn')
    await gebruiker.click(knop)
    expect(onVerdelen).toHaveBeenCalledTimes(1)
  })
})
