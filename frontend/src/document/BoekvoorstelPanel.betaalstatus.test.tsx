import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BETAALSTATUS_OPTIES_FALLBACK, BoekvoorstelPanel } from './BoekvoorstelPanel'

/** RLZ-betaalstatus (blok 3 bundel 08-09, B3): het kopveld "Betaalstatus (Reeleezee)" is een keuzelijst van de acht
 * RLZ-waarden, server-side gevuld mét herkomst-chip ('uit factuur (incasso)' / 'uit kanaal (declaratie)'); een andere keuze
 * laat de chip verdwijnen, de PUT draagt `betaalstatus`, en ná opslaan volgt de chip de serverstand ('mens' = handmatig).
 * Eigen testbestand náást BoekvoorstelPanel.test.tsx (gedeeld bestand, parallelle bouwrun). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000000003'
const TAXRATE_ID = 'dddddddd-0000-0000-0000-000000000004'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const REGEL = {
  id: null,
  ledger_id: LEDGER_ID,
  taxrate_id: TAXRATE_ID,
  project_id: null,
  netto_bedrag: '239.00',
  btw_bedrag: '50.19',
  omschrijving: 'Telefonie en internet september 2026',
}

function boekvoorstel(extra: Record<string, unknown>) {
  return {
    document_id: DOCUMENT_ID,
    vendor_id: VENDOR_ID,
    referentie: 'KTD-2026-09-0417',
    factuurdatum: '2026-09-05',
    totaalbedrag: '289.19',
    rlz_boekstuknummer: null,
    opgeslagen: true,
    regels: [REGEL],
    regels_samenvoegen: false,
    samenvoegen_toegestaan: true,
    samengevoegde_regel: null,
    betaalstatus_opties: BETAALSTATUS_OPTIES_FALLBACK,
    ...extra,
  }
}

function installFetchMock(getBoekvoorstel: unknown, putBoekvoorstel: unknown, putBodies: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') {
        return Promise.resolve(new Response(null, { status: 404 }))
      }
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '4699', naam: 'Diverse kosten', soort: 2 }] }))
      }
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [{ id: TAXRATE_ID, naam: 'NL Hoog 21%' }] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Kempen Telecom Diensten B.V.' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse(getBoekvoorstel))
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') {
        putBodies.push(JSON.parse(String(init.body)))
        return Promise.resolve(
          jsonResponse({ boekvoorstel: putBoekvoorstel, checks: { geblokkeerd: false, resultaten: [] } }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function betaalstatusVeld(): HTMLSelectElement | null {
  return document.getElementById('boekvoorstel-betaalstatus') as HTMLSelectElement | null
}

function renderPanel(status = 'te_controleren') {
  return render(
    <BoekvoorstelPanel
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      status={status}
      onGeboekt={() => {}}
      onHersteld={() => {}}
    />,
  )
}

const UIT_FACTUUR = {
  betaalstatus: 'Wordt automatisch geïncasseerd',
  betaalstatus_herkomst: 'factuur',
  verwachte_betaaldatum: '2026-09-25',
  betaalstatus_bron_tekst: 'het factuurbedrag wordt automatisch geincasseerd op of rond 25-09-2026',
  intake_kanaal: 'facturen',
}

describe('BoekvoorstelPanel — RLZ-betaalstatus (blok 3 bundel 08-09)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont de incasso-status uit de factuur mét chip en verwachte betaaldatum; de keuzelijst draagt de acht RLZ-waarden', async () => {
    installFetchMock(boekvoorstel(UIT_FACTUUR), boekvoorstel(UIT_FACTUUR), [])
    renderPanel()
    await waitFor(() => expect(betaalstatusVeld()).not.toBeNull())
    expect(betaalstatusVeld()!.value).toBe('Wordt automatisch geïncasseerd')
    const opties = Array.from(betaalstatusVeld()!.options).map((o) => o.value)
    expect(opties).toEqual(['', ...BETAALSTATUS_OPTIES_FALLBACK])
    const chip = screen.getByTestId('betaalstatus-chip')
    expect(chip).toHaveTextContent('uit factuur (incasso) · verwacht 2026-09-25')
    expect(chip.getAttribute('title')).toContain('Gelezen tekst: "het factuurbedrag wordt automatisch geincasseerd')
  })

  it('een andere keuze laat de chip verdwijnen, reist mee in de PUT en wordt "handmatig"', async () => {
    const gebruiker = userEvent.setup()
    const putBodies: unknown[] = []
    installFetchMock(
      boekvoorstel(UIT_FACTUUR),
      boekvoorstel({ ...UIT_FACTUUR, betaalstatus: 'Betaald met PIN', betaalstatus_herkomst: 'mens', betaalstatus_bron_tekst: null, verwachte_betaaldatum: null }),
      putBodies,
    )
    renderPanel()
    await waitFor(() => expect(betaalstatusVeld()).not.toBeNull())
    await gebruiker.selectOptions(betaalstatusVeld()!, 'Betaald met PIN')
    expect(screen.queryByTestId('betaalstatus-chip')).toBeNull()
    await waitFor(() => expect(putBodies.length).toBeGreaterThan(0), { timeout: 4000 })
    const laatste = putBodies[putBodies.length - 1] as { betaalstatus: unknown }
    expect(laatste.betaalstatus).toBe('Betaald met PIN')
    await waitFor(() => expect(screen.getByTestId('betaalstatus-chip')).toHaveTextContent('handmatig'))
  })

  it('declaratie uit het kanaal: "Betaald per bank" mét chip; leegmaken toont de rode hint en stuurt "" (terug naar automatisch)', async () => {
    const gebruiker = userEvent.setup()
    const putBodies: unknown[] = []
    const kanaal = { betaalstatus: 'Betaald per bank', betaalstatus_herkomst: 'kanaal', intake_kanaal: 'declaraties' }
    installFetchMock(boekvoorstel(kanaal), boekvoorstel(kanaal), putBodies)
    renderPanel()
    await waitFor(() => expect(betaalstatusVeld()).not.toBeNull())
    expect(betaalstatusVeld()!.value).toBe('Betaald per bank')
    expect(screen.getByTestId('betaalstatus-chip')).toHaveTextContent('uit kanaal (declaratie)')
    expect(Array.from(betaalstatusVeld()!.options)[0].textContent).toBe('Kies betaalwijze…')
    await gebruiker.selectOptions(betaalstatusVeld()!, '')
    expect(screen.getByText(/Declaratie zonder betaalstatus/)).toBeInTheDocument()
    await waitFor(() => expect(putBodies.length).toBeGreaterThan(0), { timeout: 4000 })
    expect((putBodies[putBodies.length - 1] as { betaalstatus: unknown }).betaalstatus).toBe('')
  })

  it('zonder betaalstatus (gewone factuur) staat de lijst op "Nog te betalen (standaard)" en is er geen chip', async () => {
    installFetchMock(boekvoorstel({ betaalstatus: null, betaalstatus_herkomst: null, intake_kanaal: null }), {}, [])
    renderPanel()
    await waitFor(() => expect(betaalstatusVeld()).not.toBeNull())
    expect(betaalstatusVeld()!.value).toBe('')
    expect(Array.from(betaalstatusVeld()!.options)[0].textContent).toBe('Nog te betalen (standaard)')
    expect(screen.queryByTestId('betaalstatus-chip')).toBeNull()
  })

  it('op een geboekt document is de betaalstatus alleen leesbaar', async () => {
    installFetchMock(boekvoorstel({ ...UIT_FACTUUR, rlz_boekstuknummer: 'RLZ-1' }), {}, [])
    renderPanel('geboekt')
    await waitFor(() => expect(screen.getByText('Wordt automatisch geïncasseerd (uit factuur (incasso))')).toBeInTheDocument())
    expect(betaalstatusVeld()).toBeNull()
  })
})
