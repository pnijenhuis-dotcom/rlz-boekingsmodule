import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000000003'
const TAXRATE_ID = 'dddddddd-0000-0000-0000-000000000004'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const LEEG_BOEKVOORSTEL = {
  document_id: DOCUMENT_ID,
  vendor_id: null,
  referentie: null,
  factuurdatum: null,
  totaalbedrag: null,
  rlz_boekstuknummer: null,
  opgeslagen: false,
  regels: [],
}

function installFetchMock(overrides: { boekvoorstel?: unknown; putResponse?: unknown; boekenResponse?: [unknown, number] }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '4699', naam: 'Diverse kosten', soort: 2 }] }))
      }
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(jsonResponse({ btw_codes: [{ id: TAXRATE_ID, naam: 'NL Hoog 21%' }] }))
      }
      if (url.endsWith('/crediteuren')) {
        return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Bouwmaat Nederland B.V.' }] }))
      }
      if (url.endsWith('/projecten')) {
        return Promise.resolve(jsonResponse({ projecten: [] }))
      }
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse(overrides.boekvoorstel ?? LEEG_BOEKVOORSTEL))
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') {
        return Promise.resolve(jsonResponse(overrides.putResponse))
      }
      if (url.endsWith('/boeken') && init?.method === 'POST') {
        const [body, status] = overrides.boekenResponse ?? [{}, 200]
        return Promise.resolve(jsonResponse(body, status))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('BoekvoorstelPanel', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('vult crediteur/GB/btw-comboboxen met de sync-cache en toont groene checks na controleren', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      putResponse: {
        boekvoorstel: { ...LEEG_BOEKVOORSTEL, opgeslagen: true, vendor_id: VENDOR_ID },
        checks: {
          geblokkeerd: false,
          resultaten: [
            { naam: 'Verplichte velden', ok: true, melding: 'Alle verplichte velden zijn ingevuld' },
            { naam: 'Regeltelling vs totaal', ok: true, melding: 'Som klopt' },
            { naam: 'Duplicaatcheck', ok: true, melding: 'Geen duplicaat gevonden' },
          ],
        },
      },
    })

    render(
      <BoekvoorstelPanel administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} status="te_controleren" onGeboekt={() => {}} />,
    )

    await waitFor(() => expect(screen.getByLabelText('Crediteur', { exact: false })).toBeInTheDocument())

    await gebruiker.click(screen.getByLabelText('Crediteur', { exact: false }))
    await waitFor(() => expect(screen.getByText('Bouwmaat Nederland B.V.')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('Bouwmaat Nederland B.V.'))
    expect(screen.getByLabelText('Crediteur', { exact: false })).toHaveValue('Bouwmaat Nederland B.V.')

    const [grootboekVeld] = screen.getAllByLabelText('Grootboek', { exact: false })
    await gebruiker.click(grootboekVeld)
    await waitFor(() => expect(screen.getByText('4699 · Diverse kosten')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('4699 · Diverse kosten'))

    const [btwVeld] = screen.getAllByLabelText('Btw-code', { exact: false })
    await gebruiker.click(btwVeld)
    await waitFor(() => expect(screen.getByText('NL Hoog 21%')).toBeInTheDocument())
    await gebruiker.click(screen.getByText('NL Hoog 21%'))

    await gebruiker.click(screen.getByRole('button', { name: 'Controleren' }))

    await waitFor(() => expect(screen.getAllByText('OK')).toHaveLength(3))
    expect(screen.getByRole('button', { name: 'Boeken in RLZ ✓' })).toBeEnabled()
  })

  it('toont de blokkerende check en houdt de boekknop uit als de checks falen', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      putResponse: {
        boekvoorstel: LEEG_BOEKVOORSTEL,
        checks: {
          geblokkeerd: true,
          resultaten: [
            { naam: 'Verplichte velden', ok: false, melding: 'Ontbrekend: crediteur' },
            { naam: 'Regeltelling vs totaal', ok: false, melding: 'Geen factuurtotaal ingevuld' },
            { naam: 'Duplicaatcheck', ok: false, melding: 'Kan niet controleren' },
          ],
        },
      },
    })

    render(
      <BoekvoorstelPanel administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} status="te_controleren" onGeboekt={() => {}} />,
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'Controleren' })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Controleren' }))

    await waitFor(() => expect(screen.getAllByText('Blokkerend')).toHaveLength(3))
    expect(screen.getByRole('button', { name: 'Boeken in RLZ ✓' })).toBeDisabled()
  })

  it('toont het boekstuknummer na een geslaagde boeking', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({
      boekvoorstel: {
        ...LEEG_BOEKVOORSTEL,
        opgeslagen: true,
        vendor_id: VENDOR_ID,
        referentie: 'F-1',
        factuurdatum: '2026-07-01',
        totaalbedrag: '121.00',
        regels: [
          { ledger_id: LEDGER_ID, taxrate_id: TAXRATE_ID, project_id: null, netto_bedrag: '100.00', btw_bedrag: '21.00', omschrijving: null },
        ],
      },
      putResponse: {
        boekvoorstel: { document_id: DOCUMENT_ID, opgeslagen: true },
        checks: { geblokkeerd: false, resultaten: [{ naam: 'Verplichte velden', ok: true, melding: 'ok' }] },
      },
      boekenResponse: [
        { document_id: DOCUMENT_ID, status: 'geboekt', rlz_document_id: 'x', rlz_boekstuknummer: 'RLZ-04-00002001' },
        200,
      ],
    })

    render(
      <BoekvoorstelPanel administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} status="te_controleren" onGeboekt={() => {}} />,
    )
    await waitFor(() => expect(screen.getByRole('button', { name: 'Controleren' })).toBeInTheDocument())
    await gebruiker.click(screen.getByRole('button', { name: 'Controleren' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Boeken in RLZ ✓' })).toBeEnabled())

    await gebruiker.click(screen.getByRole('button', { name: 'Boeken in RLZ ✓' }))

    await waitFor(() => expect(screen.getByText('RLZ-04-00002001')).toBeInTheDocument())
  })

  it('een geboekt document toont het boekstuknummer en verbergt de bewerkbare velden', async () => {
    installFetchMock({
      boekvoorstel: {
        ...LEEG_BOEKVOORSTEL,
        opgeslagen: true,
        rlz_boekstuknummer: 'RLZ-04-00002001',
      },
    })

    render(<BoekvoorstelPanel administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} status="geboekt" onGeboekt={() => {}} />)

    await waitFor(() => expect(screen.getByText('RLZ-04-00002001')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Boeken in RLZ ✓' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Referentie / factuurnummer')).toBeDisabled()
  })
})
