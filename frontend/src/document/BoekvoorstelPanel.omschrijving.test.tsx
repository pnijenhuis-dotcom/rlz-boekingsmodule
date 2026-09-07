import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'
import { isKopOmschrijvingNotitie, kopOmschrijvingTijdlijnTekst } from './kopOmschrijvingTijdlijn'

/** Kop-omschrijving automatisch (blok 9 vervolgrun 07-09, auto-first): het veld "Omschrijving boekstuk" op het controlescherm
 * is server-side gevuld mét herkomst-chip ('uit regel' / 'uit factuur' / 'afgeleid'); bewerken laat de chip
 * verdwijnen, de PUT draagt de invoer, en ná opslaan volgt de chip de serverstand ('handmatig'). Eigen testbestand
 * náást BoekvoorstelPanel.test.tsx (gedeeld bestand, parallelle bouwrun). */

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

/** Het kop-veld via id — het label is "Omschrijving boekstuk" (de regel-kolom en het regel-veld heten "Omschrijving"). */
function kopVeld(): HTMLElement | null {
  return document.getElementById('boekvoorstel-omschrijving')
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

describe('BoekvoorstelPanel — kop-omschrijving (blok 9)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont de automatische omschrijving mét chip "uit regel"; bewerken laat de chip verdwijnen en reist mee in de PUT', async () => {
    const gebruiker = userEvent.setup()
    const putBodies: unknown[] = []
    installFetchMock(
      boekvoorstel({ omschrijving: 'Steigerhuur week 34', omschrijving_herkomst: 'regel' }),
      boekvoorstel({ omschrijving: 'Eigen tekst', omschrijving_herkomst: 'handmatig' }),
      putBodies,
    )
    renderPanel()

    await waitFor(() => expect(kopVeld()).not.toBeNull())
    const veld = kopVeld() as HTMLInputElement
    expect(veld.value).toBe('Steigerhuur week 34')
    expect(screen.getByTestId('kop-omschrijving-chip')).toHaveTextContent('uit regel')

    await gebruiker.clear(veld)
    await gebruiker.type(veld, 'Eigen tekst')
    expect(screen.queryByTestId('kop-omschrijving-chip')).toBeNull()

    // De gedebouncede opslag stuurt de invoer mee; ná het antwoord volgt de chip de serverstand: 'handmatig'.
    await waitFor(() => expect(putBodies.length).toBeGreaterThan(0), { timeout: 4000 })
    const laatste = putBodies[putBodies.length - 1] as { omschrijving: string | null }
    expect(laatste.omschrijving).toBe('Eigen tekst')
    await waitFor(() => expect(screen.getByTestId('kop-omschrijving-chip')).toHaveTextContent('handmatig'))
  })

  it('chip "uit factuur" bij een betreft-regel en "afgeleid" bij de terugval; geen chip zonder herkomst', async () => {
    installFetchMock(boekvoorstel({ omschrijving: 'Huur steigermateriaal project 26123 week 34', omschrijving_herkomst: 'factuur' }), {}, [])
    const { unmount } = renderPanel()
    expect(await screen.findByTestId('kop-omschrijving-chip')).toHaveTextContent('uit factuur')
    unmount()
    vi.unstubAllGlobals()
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })

    installFetchMock(boekvoorstel({ omschrijving: 'Boot Steigers B.V. 2026-0841', omschrijving_herkomst: 'afgeleid' }), {}, [])
    const tweede = renderPanel()
    expect(await tweede.findByTestId('kop-omschrijving-chip')).toHaveTextContent('afgeleid')
    tweede.unmount()
    vi.unstubAllGlobals()
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })

    installFetchMock(boekvoorstel({ omschrijving: null, omschrijving_herkomst: null }), {}, [])
    renderPanel()
    await waitFor(() => expect(kopVeld()).not.toBeNull())
    expect((kopVeld() as HTMLInputElement).value).toBe('')
    expect(screen.queryByTestId('kop-omschrijving-chip')).toBeNull()
  })

  it('op een geboekt document is de omschrijving alleen leesbaar', async () => {
    installFetchMock(
      boekvoorstel({ omschrijving: 'Steigerhuur week 34', omschrijving_herkomst: 'regel', rlz_boekstuknummer: 'RLZ-1' }),
      {},
      [],
    )
    renderPanel('geboekt')
    // Kop (StatischVeld) én de boekingsregel tonen de tekst; het kop-invoerveld bestaat niet in de bevroren stand.
    await waitFor(() => expect(screen.getAllByText('Steigerhuur week 34').length).toBeGreaterThanOrEqual(2))
    expect(kopVeld()).toBeNull()
  })
})

describe('kopOmschrijvingTijdlijn', () => {
  it('herkent de notitie en formuleert override én reset leesbaar', () => {
    expect(isKopOmschrijvingNotitie({ veldvoorstel: {} })).toBe(false)
    const override = { kop_omschrijving: { tekst: 'Eigen tekst', herkomst: 'handmatig', afgeleid: 'Steigerhuur week 34' } }
    expect(isKopOmschrijvingNotitie(override)).toBe(true)
    expect(kopOmschrijvingTijdlijnTekst(override)).toBe('Omschrijving handmatig gezet: "Eigen tekst" (automatisch was: "Steigerhuur week 34")')
    expect(kopOmschrijvingTijdlijnTekst({ kop_omschrijving: { tekst: null, herkomst: 'regel', afgeleid: 'Steigerhuur week 34' } })).toBe(
      'Omschrijving terug naar automatisch: "Steigerhuur week 34"',
    )
  })
})
