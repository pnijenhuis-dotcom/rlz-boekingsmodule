import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel, parsePeriodeInvoer, parseWeken, periodeLabel } from './BoekvoorstelPanel'

/** Factuurperiode op weekniveau (blok 11 vervolgrun 07-09 — datalaag): het kopveld "Periode (weken)" is server-side
 * gevuld mét herkomst-chip ("wk 34–35 · 2026 · uit factuur" / "afgeleid van factuurdatum"); corrigeren via het inline-veld
 * laat de chip verdwijnen, de PUT draagt {jaar, week_van, week_tot}, en ná opslaan volgt de chip de serverstand
 * ('mens' = "handmatig"). Eigen testbestand náást BoekvoorstelPanel.test.tsx (gedeeld bestand, parallelle bouwrun). */

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
  netto_bedrag: '100.00',
  btw_bedrag: '21.00',
  omschrijving: 'Steigerhuur week 34',
}

function boekvoorstel(extra: Record<string, unknown>) {
  return {
    document_id: DOCUMENT_ID,
    vendor_id: VENDOR_ID,
    referentie: '2026-0841',
    factuurdatum: '2026-09-01',
    totaalbedrag: '121.00',
    rlz_boekstuknummer: null,
    opgeslagen: true,
    regels: [REGEL],
    regels_samenvoegen: false,
    samenvoegen_toegestaan: true,
    samengevoegde_regel: null,
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
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Boot Steigers B.V.' }] }))
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

function wekenVeld(): HTMLInputElement | null {
  return document.getElementById('boekvoorstel-periode-weken') as HTMLInputElement | null
}
function jaarVeld(): HTMLInputElement | null {
  return document.getElementById('boekvoorstel-periode-jaar') as HTMLInputElement | null
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

const UIT_FACTUUR = { jaar: 2026, week_van: 34, week_tot: 35, herkomst: 'factuur', tekst: 'week 34-35' }

describe('BoekvoorstelPanel — factuurperiode (blok 11)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont de periode uit de factuur mét chip; corrigeren laat de chip verdwijnen, reist mee in de PUT en wordt "handmatig"', async () => {
    const gebruiker = userEvent.setup()
    const putBodies: unknown[] = []
    installFetchMock(
      boekvoorstel({ periode: UIT_FACTUUR }),
      boekvoorstel({ periode: { jaar: 2026, week_van: 36, week_tot: 36, herkomst: 'mens', tekst: 'week 34-35' } }),
      putBodies,
    )
    renderPanel()

    await waitFor(() => expect(wekenVeld()).not.toBeNull())
    expect(wekenVeld()!.value).toBe('34-35')
    expect(jaarVeld()!.value).toBe('2026')
    const chip = screen.getByTestId('periode-chip')
    expect(chip).toHaveTextContent('wk 34–35 · 2026 · uit factuur')
    expect(chip.getAttribute('title')).toContain('Gelezen tekst: "week 34-35"')

    await gebruiker.clear(wekenVeld()!)
    await gebruiker.type(wekenVeld()!, '36')
    expect(screen.queryByTestId('periode-chip')).toBeNull()

    await waitFor(() => expect(putBodies.length).toBeGreaterThan(0), { timeout: 4000 })
    const laatste = putBodies[putBodies.length - 1] as { periode: unknown }
    expect(laatste.periode).toEqual({ jaar: 2026, week_van: 36, week_tot: 36 })
    await waitFor(() => expect(screen.getByTestId('periode-chip')).toHaveTextContent('wk 36 · 2026 · handmatig'))
  })

  it('toont "afgeleid van factuurdatum" bij de terugval en meldt onherkenbare invoer zonder die mee te sturen', async () => {
    const gebruiker = userEvent.setup()
    const putBodies: unknown[] = []
    const afgeleid = { jaar: 2026, week_van: 36, week_tot: 36, herkomst: 'afgeleid_van_factuurdatum', tekst: null }
    installFetchMock(boekvoorstel({ periode: afgeleid }), boekvoorstel({ periode: afgeleid }), putBodies)
    renderPanel()

    await waitFor(() => expect(wekenVeld()).not.toBeNull())
    expect(wekenVeld()!.value).toBe('36')
    expect(screen.getByTestId('periode-chip')).toHaveTextContent('wk 36 · 2026 · afgeleid van factuurdatum')

    await gebruiker.clear(wekenVeld()!)
    await gebruiker.type(wekenVeld()!, 'abc')
    expect(screen.getByText(/Onherkenbare periode/)).toBeInTheDocument()
    await waitFor(() => expect(putBodies.length).toBeGreaterThan(0), { timeout: 4000 })
    expect((putBodies[putBodies.length - 1] as { periode: unknown }).periode).toBeNull()
  })

  it('zonder periode (geen factuurdatum) zijn de velden leeg en is er geen chip', async () => {
    installFetchMock(boekvoorstel({ periode: null }), {}, [])
    renderPanel()
    await waitFor(() => expect(wekenVeld()).not.toBeNull())
    expect(wekenVeld()!.value).toBe('')
    expect(jaarVeld()!.value).toBe('')
    expect(screen.queryByTestId('periode-chip')).toBeNull()
  })

  it('op een geboekt document is de periode alleen leesbaar', async () => {
    installFetchMock(boekvoorstel({ periode: UIT_FACTUUR, rlz_boekstuknummer: 'RLZ-1' }), {}, [])
    renderPanel('geboekt')
    await waitFor(() => expect(screen.getByText('wk 34–35 · 2026 (uit factuur)')).toBeInTheDocument())
    expect(wekenVeld()).toBeNull()
  })
})

describe('periode-invoer helpers', () => {
  it('parseert weeknummer, bereik en jaar; wijst onzin af', () => {
    expect(parseWeken('34')).toEqual([34, 34])
    expect(parseWeken('34-35')).toEqual([34, 35])
    expect(parseWeken('34–35')).toEqual([34, 35])
    expect(parseWeken('34 t/m 35')).toEqual([34, 35])
    expect(parseWeken('35-34')).toEqual([34, 35])
    expect(parseWeken('0')).toBeNull()
    expect(parseWeken('54')).toBeNull()
    expect(parseWeken('week 34')).toBeNull()
    expect(parsePeriodeInvoer('34', '2026')).toEqual({ jaar: 2026, week_van: 34, week_tot: 34 })
    expect(parsePeriodeInvoer('34', '26')).toBeNull()
    expect(parsePeriodeInvoer('', '2026')).toBeNull()
    expect(periodeLabel({ jaar: 2026, week_van: 34, week_tot: 34 })).toBe('wk 34 · 2026')
    expect(periodeLabel({ jaar: 2026, week_van: 34, week_tot: 35 })).toBe('wk 34–35 · 2026')
  })
})
