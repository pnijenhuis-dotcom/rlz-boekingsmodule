import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

/* BUG 23-09 (Peter, BLOW, Van Rumpt 2025135 € 1.277,50): 7 opgeslagen regels mét bedragen, scan zonder regelbedragen →
 * `samengevoegde_regel` null → vinkje "Splitsen per regel" stil weg, Peter kruiste 6 regels weg. Doelgedrag: de server
 * berekent de één-regel-variant uit de OPGESLAGEN regels (vinkje terug); kan dat niet, dan zegt een chip waarom. */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = '3405157f-5a1c-46e8-ba16-980e03d79ee4'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000004600'
const HOOG = '1e44993a-0000-0000-0000-000000000021'
const LAAG = 'dddddddd-0000-0000-0000-000000000009'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function regel(i: number, overrides: Record<string, unknown> = {}) {
  return {
    id: `r${i}`,
    ledger_id: LEDGER_ID,
    taxrate_id: HOOG,
    project_id: null,
    netto_bedrag: '150.83',
    btw_bedrag: null,
    omschrijving: `Regel ${i}`,
    btw_bron: null,
    ...overrides,
  }
}

const BASIS = {
  document_id: DOCUMENT_ID,
  vendor_id: VENDOR_ID,
  referentie: '2025135',
  factuurdatum: '2026-09-01',
  totaalbedrag: '1277.50',
  rlz_boekstuknummer: null,
  opgeslagen: true,
  regels_samenvoegen: false,
  regels_modus_hersteld: false,
  samenvoegen_toegestaan: true,
  samengevoegde_regel: null,
  samenvoegen_niet_mogelijk_reden: null,
}

const ZEVEN_MET_VARIANT = {
  ...BASIS,
  regels: Array.from({ length: 7 }, (_, i) => regel(i + 1)),
  samengevoegde_regel: {
    id: null, ledger_id: LEDGER_ID, taxrate_id: HOOG, project_id: null,
    netto_bedrag: '1055.81', btw_bedrag: '221.69', omschrijving: 'Factuur 2025135 — samengevoegd (7 regels)', btw_bron: null,
  },
}

function installFetchMock(boekvoorstel: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '4600', naam: 'Verpakking', soort: 2 }] }))
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(jsonResponse({ btw_codes: [{ id: HOOG, naam: 'NL, Hoog tarief', percentage: '0.21' }, { id: LAAG, naam: 'NL, Laag tarief', percentage: '0.09' }] }))
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Van Rumpt' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) return Promise.resolve(jsonResponse(boekvoorstel))
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') {
        return Promise.resolve(jsonResponse({ boekvoorstel, checks: { geblokkeerd: false, resultaten: [] } }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderPanel() {
  return render(
    <BoekvoorstelPanel administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} status="te_controleren" onGeboekt={() => {}} onHersteld={() => {}} />,
  )
}

describe('BoekvoorstelPanel — samenvoegen uit opgeslagen regels (BUG 23-09, Van Rumpt 2025135)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('7 opgeslagen regels zonder scanbedragen + samengevoegde variant van de server → het vinkje staat er weer, geen chip', async () => {
    installFetchMock(ZEVEN_MET_VARIANT)
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(7))
    expect(screen.getByLabelText('Splitsen per regel')).toBeInTheDocument()
    expect(screen.queryByTestId('samenvoegen-niet-mogelijk-chip')).not.toBeInTheDocument()
  })

  it('geen variant mét reden van de server → chip "samenvoegen niet mogelijk: verschillende btw-codes", geen vinkje', async () => {
    installFetchMock({
      ...BASIS,
      regels: [regel(1, { btw_bedrag: '31.67' }), regel(2, { taxrate_id: LAAG, btw_bedrag: '13.57' })],
      samenvoegen_niet_mogelijk_reden: 'verschillende btw-codes',
    })
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(2))
    expect(screen.queryByLabelText('Splitsen per regel')).not.toBeInTheDocument()
    expect(screen.getByTestId('samenvoegen-niet-mogelijk-chip')).toHaveTextContent('samenvoegen niet mogelijk: verschillende btw-codes')
  })

  it('geen variant zonder reden van een oude server → generieke chip-tekst (nooit stil weg)', async () => {
    const { samenvoegen_niet_mogelijk_reden: _weg, ...zonderVeld } = { ...BASIS, regels: [regel(1), regel(2)] }
    installFetchMock(zonderVeld)
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(2))
    expect(screen.getByTestId('samenvoegen-niet-mogelijk-chip')).toHaveTextContent('samenvoegen niet mogelijk: geen samengevoegde regel te berekenen')
  })

  it('één opgeslagen regel → geen vinkje en geen chip (er is niets te splitsen)', async () => {
    installFetchMock({ ...BASIS, regels: [regel(1, { btw_bedrag: '31.67' })] })
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(1))
    expect(screen.queryByLabelText('Splitsen per regel')).not.toBeInTheDocument()
    expect(screen.queryByTestId('samenvoegen-niet-mogelijk-chip')).not.toBeInTheDocument()
  })
})
