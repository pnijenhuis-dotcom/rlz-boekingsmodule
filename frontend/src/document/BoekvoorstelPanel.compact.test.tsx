import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'
import { minimaleTabelbreedte } from './boekingsregelsKolommen'

/** Punt 7 run A (02-10, Peter: "de regel-tabel scrolt horizontaal zodat OMSCHRIJVING en het ×-knopje buiten beeld vallen
 * op 1455 px"): is de `.tabel-scroll`-container smaller dan de som van de kolomminima, dan schakelt de tabel om naar de
 * compacte regelweergave (klasse `compact`, géén inline min-width, label per veld uit `data-label`); boven de som staat de
 * tabel exact zoals vóór 02-10. jsdom heeft geen layout — de containerbreedte wordt hier gezet en de ResizeObserver
 * nagespeeld, zodat de omschakeling een getoetst feit is en geen oogschatting. */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000000003'
const TAXRATE_ID = 'dddddddd-0000-0000-0000-000000000004'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const BOEKVOORSTEL_TWEE_REGELS = {
  document_id: DOCUMENT_ID,
  vendor_id: VENDOR_ID,
  referentie: 'RLZ-2080142625',
  factuurdatum: '2026-06-30',
  totaalbedrag: '908.89',
  rlz_boekstuknummer: null,
  opgeslagen: true,
  regels: [
    { ledger_id: LEDGER_ID, taxrate_id: TAXRATE_ID, project_id: null, netto_bedrag: '620.78', btw_bedrag: '130.37', omschrijving: 'Brandstof diesel Floor' },
    { ledger_id: LEDGER_ID, taxrate_id: TAXRATE_ID, project_id: null, netto_bedrag: '130.36', btw_bedrag: '27.38', omschrijving: 'Brandstof diesel Ogur' },
  ],
  regels_samenvoegen: false,
  samenvoegen_toegestaan: true,
  samengevoegde_regel: null,
}

function installFetchMock(projectVerplicht: boolean) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '4699', naam: 'Diverse kosten', soort: 2 }] }))
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [{ id: TAXRATE_ID, naam: 'NL Hoog 21%', percentage: '0.2100' }] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Universal Nederland B.V.' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [{ id: 'ffffffff-0000-0000-0000-000000000006', naam: '26049 Hoofddorp' }] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: projectVerplicht }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) return Promise.resolve(jsonResponse(BOEKVOORSTEL_TWEE_REGELS))
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') return Promise.resolve(jsonResponse(BOEKVOORSTEL_TWEE_REGELS))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

/** Nagespeelde ResizeObserver: onthoudt de callback per waarnemer zodat de test een maatverandering kan afvuren. */
class NepResizeObserver {
  static instanties: NepResizeObserver[] = []
  waargenomen: Element[] = []
  callback: ResizeObserverCallback
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
    NepResizeObserver.instanties.push(this)
  }
  observe(el: Element) {
    this.waargenomen.push(el)
  }
  unobserve() {}
  disconnect() {
    this.waargenomen = []
  }
}

function zetBreedte(el: HTMLElement, breedte: number) {
  Object.defineProperty(el, 'clientWidth', { value: breedte, configurable: true })
}

function vuurResize() {
  act(() => {
    for (const ro of NepResizeObserver.instanties) {
      if (ro.waargenomen.length) ro.callback([], ro as unknown as ResizeObserver)
    }
  })
}

function renderPaneel() {
  render(
    <BoekvoorstelPanel
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      status="te_controleren"
      onGeboekt={() => {}}
      onHersteld={() => {}}
    />,
  )
}

describe('BoekvoorstelPanel — compacte regelweergave (punt 7 run A, 02-10)', () => {
  beforeEach(() => {
    NepResizeObserver.instanties = []
    vi.stubGlobal('ResizeObserver', NepResizeObserver)
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('container 590 px (gemeten formulier-pane op 1455 px) zonder projectplicht → compact: geen inline min-width, label per veld, omschrijving en ×-knop aanwezig', async () => {
    installFetchMock(false)
    renderPaneel()
    const tabel = await screen.findByTestId('boekingsregels-tabel')
    const scroll = screen.getByTestId('boekingsregels-scroll')
    expect(scroll.classList.contains('tabel-scroll')).toBe(true)
    // Vóór de meting (jsdom: clientWidth 0 = nog niet gelayout) staat de brede tabel mét haar min-width.
    expect(tabel.classList.contains('compact')).toBe(false)
    expect(tabel.style.minWidth).toBe(`${minimaleTabelbreedte(false)}px`)
    await waitFor(() => expect(NepResizeObserver.instanties.some((ro) => ro.waargenomen.includes(scroll))).toBe(true))

    zetBreedte(scroll, 590)
    vuurResize()
    await waitFor(() => expect(tabel.classList.contains('compact')).toBe(true))
    expect(tabel.style.minWidth).toBe('')
    const rij = tabel.querySelectorAll('tbody tr')[1]
    const labels = Array.from(rij.querySelectorAll('td.regel-cel')).map((td) => td.getAttribute('data-label'))
    expect(labels).toEqual(['Grootboek', 'Btw-code', 'Netto', 'Btw-bedrag'])
    expect(rij.querySelector('td.omschrijving')).not.toBeNull()
    expect(rij.querySelector('td.verwijder button[aria-label="Regel verwijderen"]')).not.toBeNull()
    expect(tabel.querySelector('th.bedragmodus button')).toHaveTextContent('Netto')
  })

  it('mét projectplicht op 488 px (gemeten op 1280 px) óók compact mét Project-label; terug naar 1200 px = de brede tabel mét min-width', async () => {
    installFetchMock(true)
    renderPaneel()
    const tabel = await screen.findByTestId('boekingsregels-tabel')
    await waitFor(() => expect(tabel.classList.contains('met-project')).toBe(true))
    const scroll = screen.getByTestId('boekingsregels-scroll')
    await waitFor(() => expect(NepResizeObserver.instanties.some((ro) => ro.waargenomen.includes(scroll))).toBe(true))

    zetBreedte(scroll, 488)
    vuurResize()
    await waitFor(() => expect(tabel.classList.contains('compact')).toBe(true))
    const rij = tabel.querySelectorAll('tbody tr')[1]
    const labels = Array.from(rij.querySelectorAll('td.regel-cel')).map((td) => td.getAttribute('data-label'))
    expect(labels).toEqual(['Grootboek', 'Btw-code', 'Project', 'Netto', 'Btw-bedrag'])

    zetBreedte(scroll, 1200)
    vuurResize()
    await waitFor(() => expect(tabel.classList.contains('compact')).toBe(false))
    expect(tabel.style.minWidth).toBe(`${minimaleTabelbreedte(true)}px`)
    expect(tabel.querySelectorAll('colgroup > col')).toHaveLength(7)
  })

  it('zonder ResizeObserver (oude browser) blijft de brede tabel mét .tabel-scroll als vangnet staan', async () => {
    vi.stubGlobal('ResizeObserver', undefined)
    installFetchMock(false)
    renderPaneel()
    const tabel = await screen.findByTestId('boekingsregels-tabel')
    expect(tabel.classList.contains('compact')).toBe(false)
    expect(tabel.style.minWidth).toBe(`${minimaleTabelbreedte(false)}px`)
    expect(screen.getByTestId('boekingsregels-scroll').classList.contains('tabel-scroll')).toBe(true)
  })
})
