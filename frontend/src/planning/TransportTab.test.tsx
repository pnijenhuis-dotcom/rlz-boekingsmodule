import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TransportTab } from './TransportTab'
import type { TransportDto } from './transportApi'

/* Transport-tab als DAG-AGENDA (feedback 31-08, mockup planning-werkopdracht-transport.html
 * TAB 2): kaarten per dagkolom mét adres/klant en statuskleur-tekst, bevestig-popup
 * (voertuigtoezegging → POST /bevestigen), signaalkaart "nog te plannen" en het werkbakje
 * (zoek → chip → klik-klik plant een gereserveerd transport). Fetch gemockt op /materiaal. */

const T_GERESERVEERD: TransportDto = {
  id: 't1',
  project_id: 'p1',
  project_naam: '144 Breda',
  leverancier_id: 'l1',
  leverancier_naam: 'Universal Verhuur',
  bestelling_id: null,
  bestelling_nummer: null,
  soort: 'levering',
  datum: '2026-08-25',
  tijdstip: '07:00:00',
  status: 'gereserveerd',
  status_bron: 'kantoor',
  status_reden: null,
  regels: [],
  samenvatting: 'Levering steiger 100.00 m²',
  m2: '100.00',
  omschrijving: null,
  voertuig: null,
  transportplanner: null,
  opdrachtgever: 'Moeskops',
  project_adres: 'Hoge Steenweg 12, Breda',
}

const T_DEFINITIEF: TransportDto = {
  ...T_GERESERVEERD,
  id: 't2',
  soort: 'retour',
  datum: '2026-08-24',
  status: 'definitief',
  samenvatting: 'Retour netten 400 m¹',
  voertuig: 'voorwagen',
  transportplanner: 'De Jong',
}

const WEEK = {
  jaar: 2026,
  weeknummer: 35,
  maandag: '2026-08-24',
  zondag: '2026-08-30',
  projecten: [
    {
      project_id: 'p1',
      project_naam: '144 Breda',
      opdrachtgever: 'Moeskops',
      is_actief: true,
      week_transporten: 2,
      ploeg_label: 'ploeg di (1 man)',
      per_datum: { '2026-08-25': [T_GERESERVEERD], '2026-08-24': [T_DEFINITIEF] },
    },
    { project_id: 'p2', project_naam: '25016 Groesbeek', opdrachtgever: 'Janssen', is_actief: true, week_transporten: 0, ploeg_label: null, per_datum: {} },
  ],
  wachtrisico: [{ project_id: 'p1', project_naam: '144 Breda', datum: '2026-08-25', aantal_personen: 1, transport_id: 't1', leverancier_naam: 'Universal Verhuur', samenvatting: 'Levering steiger 100.00 m²' }],
  aantal_transporten: 2,
  bestellingen_concept: 0,
  bestellingen_met_wijzigingen: 0,
  materiaalmatch_open: 0,
  te_plannen: [
    { bestelling_id: 'b1', bestelling_nummer: 'BST-2026-0007', project_id: 'p2', project_naam: '25016 Groesbeek', leverancier_naam: 'Universal Verhuur', datum: '2026-08-26' },
  ],
}

const LEVERANCIERS = [
  {
    id: 'l1',
    naam: 'Universal Verhuur',
    bestel_email: 'bestel@universal.nl',
    telefoon: null,
    adres: null,
    vendor_id: null,
    actief: true,
    aantal_producten: 2,
    transport_contact_naam: 'Roland',
    transport_contact_email: 'roland@universal.nl',
    materiaal_contact_naam: 'Theo',
    materiaal_contact_email: 'theo@universal.nl',
  },
]

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stub() {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = init?.method ?? 'GET'
    if (url.includes('/transport/t1/bevestigen')) return jsonResponse({ ...T_GERESERVEERD, status: 'bevestigd', voertuig: 'combi' })
    if (method === 'POST' && url.endsWith('/materiaal/a1/transport')) return jsonResponse({ ...T_GERESERVEERD, id: 'nieuw' }, 201)
    if (url.includes('/materiaal/a1/transport')) return jsonResponse(WEEK)
    if (url.includes('/materiaal/a1/bestellingen')) return jsonResponse({ items: [], totaal: 0, pagina: 1, per_pagina: 10 })
    if (url.includes('/materiaal/a1/leveranciers')) return jsonResponse(LEVERANCIERS)
    if (url.includes('/materiaal/a1/stand/')) return jsonResponse({ project_id: 'p1', project_naam: '144 Breda', tot_en_met: '2026-08-25', regels: [], m2_op_locatie: '0.00', totaal_items: 0, leveranciers: [] })
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

afterEach(() => {
  vi.unstubAllGlobals()
  try {
    localStorage.clear()
  } catch {
    /* geen localStorage in deze testomgeving — het bakje valt dan op in-memory state terug */
  }
})

const DAGEN = ['2026-08-24', '2026-08-25', '2026-08-26', '2026-08-27', '2026-08-28', '2026-08-29', '2026-08-30'].map((d, i) => ({ datum: d, naam: ['ma', 'di', 'wo', 'do', 'vr', 'za', 'zo'][i] }))

function renderTab() {
  return render(<TransportTab administratieId="a1" week={{ jaar: 2026, weeknummer: 35 }} dagen={DAGEN} filterTerm="" setFilterTerm={() => {}} />)
}

describe('TransportTab (dag-agenda)', () => {
  it('toont kaarten in de juiste dagkolom mét adres, klant en statuskleur-tekst', async () => {
    stub()
    const { container } = renderTab()
    await waitFor(() => expect(container.querySelectorAll('tbody td')).toHaveLength(5))
    await screen.findByText('Roland') // leveranciers geladen — het materiaal-contact staat dan op de kaart
    const cellen = container.querySelectorAll('tbody td')
    // ma 24-8 = definitief-kaart (groen-tekst mét materiaal-contact), di 25-8 = gereserveerd (rood).
    expect(within(cellen[0] as HTMLElement).getByText(/definitief · lijst bij Theo/)).toBeInTheDocument()
    expect(within(cellen[0] as HTMLElement).getByText(/planner: De Jong/)).toBeInTheDocument()
    const di = cellen[1] as HTMLElement
    expect(within(di).getByText('144 Breda · Moeskops')).toBeInTheDocument()
    expect(within(di).getByText('Hoge Steenweg 12, Breda')).toBeInTheDocument()
    // Wachtrisico-⚠ op de gereserveerde kaart zelf.
    expect(within(di).getByText(/gereserveerd — klik om te bevestigen · ⚠ ploeg staat gepland/)).toBeInTheDocument()
    expect(screen.getByText(/transporten deze week: 2 · 1 wachtrisico/)).toBeInTheDocument()
    // Leveranciers-paneel toont de twee contactpersonen.
    expect(screen.getByText(/transport-contact:/)).toBeInTheDocument()
    expect(screen.getByText('Roland')).toBeInTheDocument()
  })

  it('opent bij klik op een gereserveerde kaart de bevestig-popup en post het voertuig naar /bevestigen', async () => {
    const fn = stub()
    renderTab()
    await waitFor(() => expect(screen.getByText(/gereserveerd — klik om te bevestigen/)).toBeInTheDocument())
    await screen.findByText('Roland') // leveranciers geladen — de popup noemt het transport-contact
    fireEvent.click(screen.getByText(/gereserveerd — klik om te bevestigen/))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Transport bevestigen — 144 Breda · Moeskops/)).toBeInTheDocument()
    // Voertuig verplicht: radio-kaarten, combi default aangevinkt.
    const combi = within(dialog).getByRole('radio', { name: /Combi/i })
    expect(combi).toBeChecked()
    expect(within(dialog).getByRole('radio', { name: /Voorwagen/i })).not.toBeChecked()
    fireEvent.click(within(dialog).getByRole('button', { name: /Bevestigen → melding Roland/ }))
    await waitFor(() => {
      const call = fn.mock.calls.find(([u]) => String(u).includes('/transport/t1/bevestigen'))
      expect(call).toBeTruthy()
      expect(call?.[1]?.method).toBe('POST')
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ voertuig: 'combi' })
    })
  })

  it('rendert de te-plannen-signaalkaart in de dagkolom van de leverdatum', async () => {
    stub()
    const { container } = renderTab()
    await waitFor(() => expect(screen.getByText(/nog te plannen — BST-2026-0007 · 25016 Groesbeek · Universal Verhuur/)).toBeInTheDocument())
    const wo = container.querySelectorAll('tbody td')[2] as HTMLElement
    expect(within(wo).getByText(/nog te plannen — BST-2026-0007/)).toBeInTheDocument()
  })

  it('werkbakje: zoeken → chip → chip-klik + dag-klik plant een gereserveerd transport', async () => {
    const fn = stub()
    const { container } = renderTab()
    await waitFor(() => expect(container.querySelectorAll('tbody td')).toHaveLength(5))
    await screen.findByText('Roland') // leveranciers geladen — plannen kiest dan de enige leverancier direct
    fireEvent.change(screen.getByLabelText('Zoek project voor het werkbakje'), { target: { value: '250' } })
    fireEvent.click(await screen.findByRole('button', { name: /25016 Groesbeek · Janssen/ }))
    // Chip staat in het bakje; klik = selecteren, daarna de dagcel (do 27-8) aanklikken.
    const chip = screen.getByText('🏗 25016 Groesbeek — Janssen')
    fireEvent.click(chip)
    expect(screen.getByText(/Klik nu een dagkolom/)).toBeInTheDocument()
    fireEvent.click(container.querySelectorAll('tbody td')[3] as HTMLElement)
    await waitFor(() => {
      const call = fn.mock.calls.find(([u, i]) => (i?.method ?? 'GET') === 'POST' && String(u).endsWith('/materiaal/a1/transport'))
      expect(call).toBeTruthy()
      expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ project_id: 'p2', leverancier_id: 'l1', soort: 'levering', datum: '2026-08-27', regels: {} })
    })
    // De chip blijft in het bakje ná plannen (zelfde project op meerdere dagen).
    expect(screen.getByText('🏗 25016 Groesbeek — Janssen')).toBeInTheDocument()
  })
})
