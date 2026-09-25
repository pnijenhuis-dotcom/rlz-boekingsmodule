import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BETAALSTATUS_OPTIES_FALLBACK, BoekvoorstelPanel } from './BoekvoorstelPanel'

/** Blok 4 feedbackrun A 25-09 (FV-16, aangepaste vorm): de check-rij "Factuurdatum valt in een ingediende
 * aangifteperiode" is ORANJE (Signaal, geen blokkade) mét de actie "Boeken (btw in volgend tijdvak)"; de klik POST
 * de bevestig-route en het verse rapport toont de rij oranje "bevestigd door …" zonder actie. */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000000003'
const TAXRATE_ID = 'dddddddd-0000-0000-0000-000000000004'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'
const NAAM = 'Factuurdatum valt in een ingediende aangifteperiode'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const BOEKVOORSTEL = {
  document_id: DOCUMENT_ID,
  vendor_id: VENDOR_ID,
  referentie: 'RLZ-2080142898',
  factuurdatum: '2026-07-20',
  totaalbedrag: '938.06',
  rlz_boekstuknummer: null,
  opgeslagen: true,
  regels: [
    {
      id: null,
      ledger_id: LEDGER_ID,
      taxrate_id: TAXRATE_ID,
      project_id: null,
      netto_bedrag: '775.26',
      btw_bedrag: '162.80',
      omschrijving: 'Huur juli',
    },
  ],
  regels_samenvoegen: false,
  samenvoegen_toegestaan: true,
  samengevoegde_regel: null,
  betaalstatus_opties: BETAALSTATUS_OPTIES_FALLBACK,
}

const MELDING =
  'Factuurdatum 2026-07-20 valt in de ingediende btw-aangifte 2026-07-01 t/m 2026-09-30 — RLZ verschuift de btw naar het eerstvolgende open tijdvak'

function rapport(bevestigd: boolean) {
  return {
    geblokkeerd: false,
    resultaten: [
      { naam: 'Verplichte velden', ok: true, melding: 'Alle verplichte velden zijn ingevuld' },
      bevestigd
        ? { naam: NAAM, ok: true, signaal: true, melding: `${MELDING}; bewust geboekt (btw in volgend tijdvak) — bevestigd door P. Nijenhuis op 2026-09-25`, acties: [] }
        : { naam: NAAM, ok: true, signaal: true, melding: MELDING, acties: [{ code: 'aangifte_bevestigen', label: 'Boeken (btw in volgend tijdvak)', regel: 0, taxrate_id: null }] },
    ],
    extern_gecontroleerd_op: '2026-09-25T09:00:00Z',
    extern_uit_cache: false,
    extern_nog_niet: false,
  }
}

function installFetchMock(): { bevestigCalls: number } {
  const stand = { bevestigCalls: 0 }
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') return Promise.resolve(new Response(null, { status: 404 }))
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '4400', naam: 'Huur', soort: 2 }] }))
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [{ id: TAXRATE_ID, naam: 'NL, Hoog Tarief', percentage: 0.21 }] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Universal Nederland B.V.' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) return Promise.resolve(jsonResponse(BOEKVOORSTEL))
      if (url.includes('/boekvoorstel/checks') && init?.method === 'POST') return Promise.resolve(jsonResponse(rapport(stand.bevestigCalls > 0)))
      if (url.endsWith('/boekvoorstel/aangifte-periode-bevestigen') && init?.method === 'POST') {
        stand.bevestigCalls += 1
        return Promise.resolve(jsonResponse(rapport(true)))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return stand
}

function rij(): HTMLElement | null {
  const cel = screen.queryAllByText(NAAM).find((el) => el.tagName === 'B')
  return cel ? cel.closest('tr') : null
}

describe('BoekvoorstelPanel — factuurdatum in ingediende aangifteperiode (blok 4, 25-09)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont de rij als Signaal (geen blokkade) mét de actie en legt de bewuste keuze vast via de bevestig-route', async () => {
    const stand = installFetchMock()
    render(
      <BoekvoorstelPanel administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} status="te_controleren" onGeboekt={() => {}} onHersteld={() => {}} />,
    )
    await waitFor(() => expect(rij()).not.toBeNull())
    const r = rij() as HTMLElement
    expect(within(r).getByText('Signaal')).toBeInTheDocument()
    expect(within(r).queryByText('Blokkerend')).not.toBeInTheDocument()
    const knop = within(r).getByRole('button', { name: 'Boeken (btw in volgend tijdvak)' })
    expect(knop.className).toContain('btn')
    await userEvent.click(knop)
    await waitFor(() => expect(stand.bevestigCalls).toBe(1))
    await waitFor(() => expect(within(rij() as HTMLElement).getByText(/bevestigd door P\. Nijenhuis/)).toBeInTheDocument())
    expect(within(rij() as HTMLElement).queryByRole('button', { name: 'Boeken (btw in volgend tijdvak)' })).not.toBeInTheDocument()
    expect(within(rij() as HTMLElement).getByText('Signaal')).toBeInTheDocument()
  })
})
