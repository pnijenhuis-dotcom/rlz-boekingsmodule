import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

/** Niet-btw-plichtige administratie (BUG Peter 22-09, casus VGG / Studio Lacy Lion 2026-042): de btw-keuzelijst is
 * verborgen mét chip, en de check-actie "Btw in de kosten zetten (alle regels)" herrekent élke regel (bruto, btw 0,
 * "geen btw"-code) en slaat op. */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000000003'
const HOOG_ID = 'dddddddd-0000-0000-0000-000000000004'
const VRIJ_ID = 'dddddddd-0000-0000-0000-000000000010'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const REGEL = {
  id: null,
  volgnummer: 1,
  ledger_id: LEDGER_ID,
  taxrate_id: HOOG_ID,
  project_id: null,
  netto_bedrag: '1535.13',
  btw_bedrag: '322.38',
  omschrijving: 'Schoonmaakkosten',
}

function boekvoorstel(over: Record<string, unknown> = {}) {
  return {
    document_id: DOCUMENT_ID,
    vendor_id: VENDOR_ID,
    referentie: '2026-042',
    factuurdatum: '2026-09-11',
    totaalbedrag: '1857.51',
    rlz_boekstuknummer: null,
    opgeslagen: true,
    regels: [REGEL],
    regels_samenvoegen: false,
    samenvoegen_toegestaan: true,
    samengevoegde_regel: null,
    btw_plichtig: false,
    geen_btw_taxrate_id: VRIJ_ID,
    ...over,
  }
}

function installFetchMock(opties: { btwPlichtig: boolean; putBodies: unknown[]; checksResponse?: unknown }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '4106', naam: 'Schoonmaakkosten', soort: 2 }] }))
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(
          jsonResponse({
            btw_codes: [
              { id: HOOG_ID, naam: 'NL, Hoog Tarief', percentage: '0.2100' },
              { id: VRIJ_ID, naam: 'NL, Geen BTW (Vrijgesteld)', percentage: '0', vrijgesteld: true },
            ],
          }),
        )
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Studio Lacy Lion' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      if (url.endsWith('/boekvoorstel/checks') && init?.method === 'POST') {
        if (opties.checksResponse === undefined) return Promise.resolve(new Response(null, { status: 404 }))
        return Promise.resolve(jsonResponse(opties.checksResponse))
      }
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse(boekvoorstel({ btw_plichtig: opties.btwPlichtig, geen_btw_taxrate_id: opties.btwPlichtig ? null : VRIJ_ID })))
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') {
        opties.putBodies.push(JSON.parse(String(init.body)))
        return Promise.resolve(jsonResponse({ boekvoorstel: boekvoorstel({ btw_plichtig: opties.btwPlichtig }), checks: opties.checksResponse ?? { resultaten: [] } }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

const CHECK_ROOD = {
  resultaten: [
    {
      naam: 'Btw in niet-btw-plichtige administratie',
      ok: false,
      melding: 'Deze administratie is niet btw-plichtig: regel 1: btw € 322.38, tarief 21 % · NL, Hoog Tarief',
      acties: [{ code: 'btw_in_kosten_alles', label: 'Btw in de kosten zetten (alle regels)', regel: 0, taxrate_id: VRIJ_ID }],
    },
  ],
}

describe('BoekvoorstelPanel — niet btw-plichtig (22-09)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('verbergt de btw-keuzelijst mét chip en herrekent alle regels via de check-actie', async () => {
    const gebruiker = userEvent.setup()
    const putBodies: unknown[] = []
    installFetchMock({ btwPlichtig: false, putBodies, checksResponse: CHECK_ROOD })
    render(<BoekvoorstelPanel administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} status="te_controleren" onGeboekt={() => {}} onHersteld={() => {}} />)
    await waitFor(() => expect(screen.getByTestId('regel-btw-niet-plichtig-chip')).toBeInTheDocument())
    expect(screen.getByTestId('regel-btw-niet-plichtig-chip')).toHaveTextContent('administratie niet btw-plichtig — btw zit in de kosten')
    expect(screen.queryByLabelText('Btw-code', { exact: false })).not.toBeInTheDocument()

    const knop = await screen.findByRole('button', { name: 'Btw in de kosten zetten (alle regels)' })
    await gebruiker.click(knop)
    expect(screen.getByLabelText('Netto bedrag')).toHaveValue('1.857,51')
    expect(screen.getByLabelText('Btw bedrag')).toHaveValue('0,00')
    await waitFor(() => expect(putBodies.length).toBeGreaterThan(0))
    const laatste = putBodies[putBodies.length - 1] as { regels: { taxrate_id: string | null; netto_bedrag: string; btw_bedrag: string; btw_in_kosten?: boolean }[] }
    expect(laatste.regels[0].taxrate_id).toBe(VRIJ_ID)
    expect(laatste.regels[0].netto_bedrag).toBe('1857.51')
    expect(laatste.regels[0].btw_bedrag).toBe('0.00')
    expect(laatste.regels[0].btw_in_kosten).toBe(true)
  })

  it('btw-plichtig = de gewone keuzelijst, geen chip', async () => {
    installFetchMock({ btwPlichtig: true, putBodies: [] })
    render(<BoekvoorstelPanel administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} status="te_controleren" onGeboekt={() => {}} onHersteld={() => {}} />)
    await waitFor(() => expect(screen.getAllByLabelText('Btw-code', { exact: false })[0]).toBeInTheDocument())
    expect(screen.queryByTestId('regel-btw-niet-plichtig-chip')).not.toBeInTheDocument()
  })
})
