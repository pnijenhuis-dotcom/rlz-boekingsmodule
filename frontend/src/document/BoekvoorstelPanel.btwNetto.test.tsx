import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

/* FV-09 (feedbackrun A 25-09, blok 6): het btw-bedrag volgt het tarief óók bij een wijziging van het NETTO — op een
 * geladen regel mét btw (die telde tot 25-09 als "handmatig" en bewoog niet mee), ná een mens-getypt btw-bedrag (dat
 * wint zolang het netto niet wijzigt; daarna herrekend mét chip) en in de samengevoegde modus. Zonder tarief blijft het
 * btw-veld staan mét de chip "tarief onbekend — btw niet herrekend"; in-kosten-regels houden btw 0. Marge-regel 18-09
 * ongewijzigd (de check blijft de poort). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000004510'
const HOOG = 'dddddddd-0000-0000-0000-000000000021'
const LAAG = 'dddddddd-0000-0000-0000-000000000009'
const NUL = 'dddddddd-0000-0000-0000-000000000000'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function regel(overrides: Record<string, unknown>) {
  return {
    id: null,
    ledger_id: LEDGER_ID,
    taxrate_id: HOOG,
    project_id: null,
    netto_bedrag: null,
    btw_bedrag: null,
    omschrijving: '',
    btw_bron: null,
    ...overrides,
  }
}

function boekvoorstel(overrides: Record<string, unknown> = {}) {
  return {
    document_id: DOCUMENT_ID,
    vendor_id: VENDOR_ID,
    referentie: '88-186308',
    factuurdatum: '2026-09-17',
    totaalbedrag: '116.60',
    rlz_boekstuknummer: null,
    opgeslagen: true,
    regels: [regel({ id: 'r1', netto_bedrag: '96.36', btw_bedrag: '20.24', omschrijving: 'Wijn' })],
    regels_samenvoegen: false,
    samenvoegen_toegestaan: true,
    samengevoegde_regel: null,
    ...overrides,
  }
}

function installFetchMock(bv: unknown) {
  const putBodies: unknown[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '4510', naam: 'Representatiekosten', soort: 2 }] }))
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(
          jsonResponse({
            btw_codes: [
              { id: HOOG, naam: 'NL, Hoog tarief', percentage: '0.21' },
              { id: LAAG, naam: 'NL, Laag tarief', percentage: '0.09' },
              { id: NUL, naam: 'NL, Nul tarief', percentage: '0' },
            ],
          }),
        )
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Rituals Nieuwegein' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) return Promise.resolve(jsonResponse(bv))
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') {
        putBodies.push(JSON.parse(String(init.body)))
        return Promise.resolve(jsonResponse({ boekvoorstel: bv, checks: { geblokkeerd: false, resultaten: [] } }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return putBodies
}

function renderPanel() {
  return render(
    <BoekvoorstelPanel
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      status="te_controleren"
      onGeboekt={() => {}}
      onHersteld={() => {}}
    />,
  )
}

async function zetNetto(user: ReturnType<typeof userEvent.setup>, waarde: string, index = 0) {
  const netto = screen.getAllByLabelText('Netto bedrag')[index] as HTMLInputElement
  await user.clear(netto)
  await user.type(netto, waarde)
}

describe('BoekvoorstelPanel — btw herrekent bij nettowijziging (FV-09, 25-09)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('(a) geladen regel mét btw: netto wijzigen → btw volgt het tarief (96,36 → 100,00 = 21,00)', async () => {
    installFetchMock(boekvoorstel())
    renderPanel()
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(1))
    await zetNetto(user, '100')
    expect((screen.getByLabelText('Btw bedrag') as HTMLInputElement).value).toBe('21,00')
    // Geen "netto gewijzigd"-chip: het btw-bedrag was niet van de mens.
    expect(screen.queryByTestId('regel-btw-herrekend-netto-chip')).not.toBeInTheDocument()
  })

  it('(b) tarief wijzigen → btw mee (bestaand gedrag 18-09 blijft)', async () => {
    installFetchMock(boekvoorstel())
    renderPanel()
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(1))
    const btwCombo = screen.getByRole('combobox', { name: /btw-code/i })
    await user.click(btwCombo)
    await user.click(await screen.findByRole('option', { name: /Laag tarief/ }))
    expect((screen.getByLabelText('Btw bedrag') as HTMLInputElement).value).toBe('8,67')
  })

  it('(d) mens-btw blijft staan zolang het netto niet wijzigt; ná een nettowijziging herrekend mét chip', async () => {
    const puts = installFetchMock(boekvoorstel())
    renderPanel()
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(1))
    const btw = screen.getByLabelText('Btw bedrag') as HTMLInputElement
    await user.clear(btw)
    await user.type(btw, '20.20')
    expect(btw.value).toBe('20.20')
    // Een andere wijziging (omschrijving) raakt de mens-btw niet.
    const omschrijving = screen.getAllByLabelText('Omschrijving')[0]
    await user.type(omschrijving, ' x')
    expect(btw.value).toBe('20.20')
    expect(screen.queryByTestId('regel-btw-herrekend-netto-chip')).not.toBeInTheDocument()
    // Netto wijzigen → herrekend uit het tarief mét chip.
    await zetNetto(user, '200')
    expect(btw.value).toBe('42,00')
    expect(screen.getByTestId('regel-btw-herrekend-netto-chip')).toHaveTextContent('btw herrekend (netto gewijzigd)')
    // De opslag draagt het herrekende bedrag (de server schrijft de tijdlijnregel).
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 })
    const laatste = puts[puts.length - 1] as { regels: { netto_bedrag: string; btw_bedrag: string }[] }
    expect(laatste.regels[0].netto_bedrag).toBe('200')
    expect(laatste.regels[0].btw_bedrag).toBe('42.00')
  })

  it('tarief onbekend: netto wijzigen laat het btw-veld staan mét chip "tarief onbekend — btw niet herrekend"', async () => {
    installFetchMock(boekvoorstel({ regels: [regel({ id: 'r1', taxrate_id: null, netto_bedrag: '96.36', btw_bedrag: '20.24' })] }))
    renderPanel()
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(1))
    await zetNetto(user, '100')
    expect((screen.getByLabelText('Btw bedrag') as HTMLInputElement).value).toBe('20.24')
    expect(screen.getByTestId('regel-btw-niet-herrekend-chip')).toHaveTextContent('tarief onbekend — btw niet herrekend')
  })

  it('btw in de kosten: netto wijzigen houdt btw 0,00 (niets herrekenen behalve de nul)', async () => {
    installFetchMock(
      boekvoorstel({ regels: [regel({ id: 'r1', taxrate_id: NUL, netto_bedrag: '116.60', btw_bedrag: '0.00', btw_in_kosten: true })] }),
    )
    renderPanel()
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(1))
    await zetNetto(user, '120')
    expect((screen.getByLabelText('Btw bedrag') as HTMLInputElement).value).toBe('0,00')
    expect(screen.getByTestId('regel-btw-in-kosten-chip')).toBeInTheDocument()
    expect(screen.queryByTestId('regel-btw-niet-herrekend-chip')).not.toBeInTheDocument()
  })

  it('(c) samengevoegde modus: de ene regel herrekent óók bij nettowijziging; terug naar losse regels houdt hun eigen btw', async () => {
    installFetchMock(
      boekvoorstel({
        regels_samenvoegen: true,
        regels: [regel({ id: 's', netto_bedrag: '150.00', btw_bedrag: '31.50', omschrijving: 'Factuur 88-186308 — samengevoegd (2 regels)' })],
        veldvoorstel: null,
      }),
    )
    renderPanel()
    const user = userEvent.setup()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(1))
    await zetNetto(user, '160')
    expect((screen.getByLabelText('Btw bedrag') as HTMLInputElement).value).toBe('33,60')
  })
})
