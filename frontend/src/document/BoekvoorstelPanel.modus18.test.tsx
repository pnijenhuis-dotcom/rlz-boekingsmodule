import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

/* BUG 18-09 (Peter, casus Zilver Horeca Fac-25-022711, BLOW): "hij splitst nu per regel zonder het vinkje?" — de server had
 * 21 losse regels opgeslagen (geen samengevoegde variant) terwijl de voorkeur "samenvoegen" zei; het scherm toonde ze als
 * samengevoegd (vinkje uit, hint "Samengevoegd…", 21 rijen) en rekende 9 % geheugen-btw op de 0 %-Emballageregels.
 * Doelgedrag: één afgeleide stand (vinkje, hint, tabel), chip "weergave hersteld"; bruto volgt het FACTUUR-regeltarief;
 * chip "factuur 0 %" (btw_bron factuur_regel); chip "niet gelezen (afgedekt)"; chip pinbon-totaal (groen / oranje). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000007049'
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
    taxrate_id: LAAG,
    project_id: null,
    netto_bedrag: null,
    btw_bedrag: null,
    omschrijving: '',
    btw_bron: null,
    ...overrides,
  }
}

const OPGESLAGEN_DRIE_REGELS = {
  document_id: DOCUMENT_ID,
  vendor_id: VENDOR_ID,
  referentie: 'Fac-25-022711',
  factuurdatum: '2025-12-17',
  totaalbedrag: null,
  rlz_boekstuknummer: null,
  opgeslagen: true,
  regels: [
    regel({ id: 'r1', netto_bedrag: '17.95', btw_bedrag: '1.62', omschrijving: 'Twix 32 x 50 gram', btw_bron: 'factuur_regel', factuur_btw_percentage: '0.0900' }),
    regel({ id: 'r2', taxrate_id: NUL, netto_bedrag: '10.80', btw_bedrag: '0.00', omschrijving: 'Emballage ( 24 Stuks )', btw_bron: 'factuur_regel', factuur_btw_percentage: '0.0000' }),
    regel({ id: 'r3', netto_bedrag: null, omschrijving: 'Balisto Yobbery 20 x 37 Gr', bedrag_niet_gelezen: true, factuur_btw_percentage: '0.0900' }),
  ],
  // De voorkeur zegt "samenvoegen", de server liet de modus al de data volgen:
  regels_samenvoegen: false,
  regels_modus_hersteld: true,
  samenvoegen_toegestaan: true,
  samengevoegde_regel: null,
  totaal_bron: null,
  totaal_pinbon: '738.27',
  totaal_pinbon_status: 'niet_toetsbaar',
}

function installFetchMock(boekvoorstel: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '7049', naam: 'Diverse inkopen', soort: 2 }] }))
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(
          jsonResponse({
            btw_codes: [
              { id: LAAG, naam: 'NL, Laag tarief', percentage: '0.09' },
              { id: NUL, naam: 'NL, Nul tarief', percentage: '0' },
            ],
          }),
        )
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Zilverhoreca Groothandel B.V.' }] }))
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
    <BoekvoorstelPanel
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      status="te_controleren"
      onGeboekt={() => {}}
      onHersteld={() => {}}
    />,
  )
}

describe('BoekvoorstelPanel — samenvoegen-bug 18-09 (Zilver Horeca)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('modus volgt de data: drie opgeslagen regels = losse weergave mét chip "weergave hersteld"', async () => {
    installFetchMock(OPGESLAGEN_DRIE_REGELS)
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(3))
    // Geen samengevoegde variant → geen vinkje ("samenvoegenBeschikbaar" vereist een berekende één-regel-variant); wél de
    // chip die zegt wat er gebeurd is — nooit stil.
    const chip = screen.getByTestId('modus-hersteld-chip')
    expect(chip).toHaveTextContent('weergave hersteld: 3 opgeslagen regels, modus stond op samengevoegd')
    expect(screen.queryByText(/Samengevoegd tot één boekingsregel/)).not.toBeInTheDocument()
  })

  it('tweede grendel: zegt de DTO tóch "samenvoegen" bij > 1 opgeslagen regels, dan toont het scherm de losse regels', async () => {
    installFetchMock({ ...OPGESLAGEN_DRIE_REGELS, regels_samenvoegen: true, regels_modus_hersteld: false })
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(3))
    expect(screen.getByTestId('modus-hersteld-chip')).toBeInTheDocument()
  })

  it('bruto volgt het factuur-regeltarief (Emballage 0 % blijft 10,80), chip "factuur 0 %" en chip "niet gelezen (afgedekt)"', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock(OPGESLAGEN_DRIE_REGELS)
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(3))
    const chips = screen.getAllByTestId('regel-btw-standaard-chip')
    expect(chips.map((c) => c.textContent)).toEqual(expect.arrayContaining(['factuur 9 %', 'factuur 0 %']))
    expect(screen.getByTestId('regel-bedrag-niet-gelezen-chip')).toHaveTextContent('niet gelezen (afgedekt)')

    await gebruiker.click(screen.getByRole('button', { name: 'Netto' }))
    const bruto = screen.getAllByLabelText('Bruto bedrag').map((el) => (el as HTMLInputElement).value)
    // 17,95 × 1,09 = 19,57; Emballage 10,80 × 1,00 = 10,80 (en niet 11,77 uit het 9 %-geheugen-tarief).
    expect(bruto[0]).toBe('19,57')
    expect(bruto[1]).toBe('10,80')
  })

  it('pinbon-totaal: oranje chip als de regels niet volledig gelezen zijn, groen "uit pinbon" als de som sluit', async () => {
    installFetchMock(OPGESLAGEN_DRIE_REGELS)
    const { unmount } = renderPanel()
    await waitFor(() => expect(screen.getByTestId('totaal-pinbon-chip')).toBeInTheDocument())
    expect(screen.getByTestId('totaal-pinbon-chip')).toHaveTextContent('pinbon zegt € 738,27 — regels niet volledig gelezen')
    expect(screen.getByLabelText('Totaalbedrag (incl. btw)')).toHaveValue('')
    unmount()
    vi.unstubAllGlobals()
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })

    installFetchMock({
      ...OPGESLAGEN_DRIE_REGELS,
      regels: OPGESLAGEN_DRIE_REGELS.regels.slice(0, 2),
      totaalbedrag: '30.37',
      totaal_bron: 'pinbon',
      totaal_pinbon: '30.37',
      totaal_pinbon_status: 'groen',
    })
    renderPanel()
    await waitFor(() => expect(screen.getByTestId('totaal-pinbon-chip')).toHaveTextContent('uit pinbon'))
    expect(screen.getByLabelText('Totaalbedrag (incl. btw)')).toHaveValue('30.37')
  })
})
