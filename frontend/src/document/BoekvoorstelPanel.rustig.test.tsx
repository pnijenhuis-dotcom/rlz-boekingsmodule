import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'
import { HERKOMST_OPSLAGSLEUTEL_PREFIX } from './herkomstZichtbaarheid'

/** Punt 2 "Rustig scherm: groen = niets tonen" (Peter 02-10, casus Universal Steigerbouw f00117f4 RLZ-2080142625:
 * "Die velden onder crediteuren (AI 85% · herkend op btw-nummer NL · …) hoef ik allemaal niet te zien … verbergen" en
 * "dito met alle groene signalen onder kopgegevens. als het klopt niet tonen"). Standaardweergave: nul herkomst-chips in
 * crediteur / kopgegevens / boekingsregels; één linkbtn "Herkomst tonen" per blok klapt ze uit; een AFWIJKING blijft
 * altijd staan; de periode-chip alleen als de periode NIET uit de factuur komt. Eigen testbestand (parallelle bouwrun). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-00000f00117f'
const GB_7005 = 'cccccccc-0000-0000-0000-000000007005'
const GB_4400 = 'cccccccc-0000-0000-0000-000000004400'
const TAXRATE_HOOG = 'dddddddd-0000-0000-0000-000000000021'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'
const PROJECT_A = 'ffffffff-0000-0000-0000-000000026140'
const PROJECT_B = 'ffffffff-0000-0000-0000-000000025147'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function regel(overrides: Record<string, unknown>) {
  return {
    id: null,
    ledger_id: GB_7005,
    taxrate_id: TAXRATE_HOOG,
    project_id: PROJECT_A,
    netto_bedrag: '375.58',
    btw_bedrag: '78.87',
    omschrijving: 'Brandstof diesel Floor',
    btw_bron: 'factuur',
    gb_bron: 'geheugen',
    gb_voorstel_detail: '3× bevestigd',
    project_bron: 'factuur',
    project_bron_detail: 'Factuur vermeldt "26140"',
    ...overrides,
  }
}

const GEHEUGEN_GROEN = {
  gb: { waarde: GB_7005, confidence: 1, telling: 5, oranje: false, reden: null, app_bevestigd: true },
  btw: { waarde: TAXRATE_HOOG, confidence: 1, telling: 5, oranje: false, reden: null, app_bevestigd: true },
  project: { waarde: PROJECT_A, confidence: 1, telling: 5, oranje: false, reden: null, app_bevestigd: true },
}

function installFetchMock(regels: unknown[], geheugenVoorstel: unknown, boekvoorstelExtra: Record<string, unknown> = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') return Promise.resolve(jsonResponse(geheugenVoorstel))
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(
          jsonResponse({
            rekeningen: [
              { ledger_id: GB_7005, code: '7005', naam: 'Inhuur steiger', soort: 2 },
              { ledger_id: GB_4400, code: '4400', naam: 'Brandstof', soort: 2 },
            ],
          }),
        )
      }
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [{ id: TAXRATE_HOOG, naam: 'NL, Hoog Tarief', percentage: 0.21 }] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Universal Nederland B.V.' }] }))
      if (url.endsWith('/projecten')) {
        return Promise.resolve(
          jsonResponse({ projecten: [{ id: PROJECT_A, naam: '26140 Koningstraat (Confide)' }, { id: PROJECT_B, naam: '25147 Ons Dorp' }] }),
        )
      }
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: true }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            vendor_id: VENDOR_ID,
            referentie: 'RLZ-2080142625',
            factuurdatum: '2026-06-30',
            totaalbedrag: '908.89',
            rlz_boekstuknummer: null,
            // Als op f00117f4: de A10-prefill-autosave heeft de regels al opgeslagen (geen menselijke opslag) — de
            // AI-zekerheidschips blijven staan, de regels komen uit de DTO.
            opgeslagen: true,
            prefill_automatisch: true,
            regels,
            regels_samenvoegen: false,
            samenvoegen_toegestaan: true,
            samengevoegde_regel: null,
            omschrijving: 'Brandstof diesel Floor',
            omschrijving_herkomst: 'regel',
            periode: { jaar: 2026, week_van: 27, week_tot: 27, herkomst: 'factuur', tekst: 'week 27' },
            leverancier_land: 'NL',
            leverancier_land_bron: 'uit btw-nummer crediteur',
            ...boekvoorstelExtra,
          }),
        )
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') return Promise.resolve(jsonResponse({}))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

/** De scan zoals op f00117f4: crediteur herkend op btw-nummer, kopvelden 98 %, nummers uit de factuur. */
const AI_VOORSTEL = {
  bron: 'ai',
  leverancier_naam: 'Universal Nederland B.V.',
  factuurnummer: 'RLZ-2080142625',
  factuurdatum: '2026-06-30',
  vervaldatum: null,
  valuta: 'EUR',
  totaal_excl: '751.15',
  totaal_incl: '908.89',
  btw_bedrag: '157.74',
  regelaantal: 2,
  regels: [
    { omschrijving: 'Brandstof diesel Floor', netto_bedrag: '375.58', btw_bedrag: '78.87', hoeveelheid: null, taxrate_id: null },
    { omschrijving: 'Brandstof diesel Ogur', netto_bedrag: '375.57', btw_bedrag: '78.87', hoeveelheid: null, taxrate_id: null },
  ],
  zekerheid: { leverancier_naam: 0.85, factuurnummer: 0.98, factuurdatum: 0.98, totaal_incl: 0.98 },
  regel_zekerheid: [0.95, 0.95],
  zekerheid_drempel: 0.8,
  vendor_suggestie: { vendor_id: VENDOR_ID, match: 'btw_nummer' },
  btw_nummer: 'NL826228525B01',
  btw_nummer_geverifieerd: true,
  kvk_nummer: '72404272',
  controle: { regelsom: '908.89', regelsom_wijkt_af: false, onparseerbaar: [], lage_zekerheid: [], bsn_verwijderd: 0, onvolledig: false },
}

function renderPanel() {
  return render(
    <BoekvoorstelPanel
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      status="te_controleren"
      veldvoorstel={AI_VOORSTEL}
      onGeboekt={() => {}}
      onHersteld={() => {}}
    />,
  )
}

const TWEE_REGELS = [regel({}), regel({ omschrijving: 'Brandstof diesel Ogur', netto_bedrag: '375.57' })]

describe('BoekvoorstelPanel — rustig scherm: groen = niets tonen (punt 2, Peter 02-10)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
    window.sessionStorage.clear()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    window.sessionStorage.clear()
  })

  it('alles klopt (crediteur op btw-nummer, AI 98 %, geheugen 100 % groen, periode uit factuur): nul chips in de standaardweergave', async () => {
    installFetchMock(TWEE_REGELS, GEHEUGEN_GROEN)
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Grootboek', { exact: false })[0]).toHaveValue('7005 · Inhuur steiger'))
    await waitFor(() => expect(screen.getAllByLabelText(/^Project/).at(-1)).toHaveValue('26140 Koningstraat (Confide)'))
    // Geen herkomst-chip in de drie blokken: AI %, "herkend op btw-nummer", land, KvK/btw, "uit regel", periode, geheugen,
    // "uit geheugen", "uit factuur (21%)".
    expect(screen.queryByText(/^AI \d+%/)).toBeNull()
    expect(screen.queryByText(/herkend op/)).toBeNull()
    expect(screen.queryByTestId('leverancier-land-chip')).toBeNull()
    expect(screen.queryByText(/KvK 72404272/)).toBeNull()
    expect(screen.queryByText(/btw NL826228525B01/)).toBeNull()
    expect(screen.queryByTestId('kop-omschrijving-chip')).toBeNull()
    expect(screen.queryByTestId('periode-chip')).toBeNull()
    expect(screen.queryByText(/Geheugen 100%/)).toBeNull()
    expect(screen.queryByTestId('regel-gb-chip')).toBeNull()
    expect(screen.queryByTestId('regel-project-factuur-chip')).toBeNull()
    expect(screen.queryByText(/uit factuur/)).toBeNull()
    expect(document.querySelectorAll('.crediteur-kaart .chip.ok, .crediteur-kaart .chip.handmatig')).toHaveLength(0)
    // Drie knoppen "Herkomst tonen": crediteur, kopgegevens, boekingsregels.
    expect(screen.getAllByRole('button', { name: 'Herkomst tonen' })).toHaveLength(3)
    expect(screen.getByTestId('herkomst-tonen-crediteur')).toHaveAttribute('aria-pressed', 'false')
  })

  it('"Herkomst tonen" klapt per blok exact de chips van vóór 02-10 uit; "Herkomst verbergen" klapt ze weer in', async () => {
    installFetchMock(TWEE_REGELS, GEHEUGEN_GROEN)
    const gebruiker = userEvent.setup()
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Grootboek', { exact: false })[0]).toHaveValue('7005 · Inhuur steiger'))

    await gebruiker.click(screen.getByTestId('herkomst-tonen-crediteur'))
    const kaart = screen.getByTestId('crediteur-kaart')
    expect(within(kaart).getByText(/AI 85% · herkend op btw-nummer/)).toHaveClass('chip', 'ok')
    expect(within(kaart).getByTestId('leverancier-land-chip')).toHaveTextContent('NL · uit btw-nummer crediteur')
    expect(within(kaart).getByText('btw NL826228525B01')).toBeInTheDocument()
    expect(within(kaart).getByText('KvK 72404272')).toBeInTheDocument()
    expect(within(kaart).getByText('uit factuur')).toBeInTheDocument()
    expect(screen.getByTestId('herkomst-tonen-crediteur')).toHaveTextContent('Herkomst verbergen')
    // De andere blokken blijven rustig.
    expect(screen.queryByTestId('kop-omschrijving-chip')).toBeNull()
    expect(screen.queryByTestId('regel-gb-chip')).toBeNull()

    await gebruiker.click(screen.getByTestId('herkomst-tonen-kopgegevens'))
    expect(screen.getByTestId('kop-omschrijving-chip')).toHaveTextContent('uit regel')
    expect(screen.getByTestId('periode-chip')).toHaveTextContent('wk 27 · 2026 · uit factuur')
    expect(screen.getAllByText(/^AI 98%/).length).toBeGreaterThanOrEqual(3)

    await gebruiker.click(screen.getByTestId('herkomst-tonen-regels'))
    expect(screen.getAllByTestId('regel-gb-chip')[0]).toHaveTextContent('uit geheugen')
    expect(screen.getAllByTestId('regel-project-factuur-chip')[0]).toHaveTextContent('uit factuur')
    expect(screen.getAllByText('uit factuur (21%)').length).toBe(2)
    expect(screen.getAllByText('Geheugen 100%').length).toBeGreaterThan(0)

    await gebruiker.click(screen.getByTestId('herkomst-tonen-regels'))
    expect(screen.queryByTestId('regel-gb-chip')).toBeNull()
    expect(screen.queryByText('Geheugen 100%')).toBeNull()
    // Stand per browsersessie: crediteur en kopgegevens open, regels dicht.
    expect(window.sessionStorage.getItem(`${HERKOMST_OPSLAGSLEUTEL_PREFIX}crediteur`)).toBe('1')
    expect(window.sessionStorage.getItem(`${HERKOMST_OPSLAGSLEUTEL_PREFIX}kopgegevens`)).toBe('1')
    expect(window.sessionStorage.getItem(`${HERKOMST_OPSLAGSLEUTEL_PREFIX}regels`)).toBeNull()
  })

  it('een afwijking blijft altijd zichtbaar: geheugen wisselend (oranje), factuur noemt een ander project, periode = aanname', async () => {
    installFetchMock(
      [
        regel({ gb_bron: 'geheugen_conflict', gb_voorstel_detail: 'jongste keuze' }),
        regel({ omschrijving: 'Brandstof diesel Ogur', project_id: null, project_bron: 'factuur_conflict', project_bron_detail: 'Factuur noemt "25147"' }),
      ],
      {
        ...GEHEUGEN_GROEN,
        btw: { waarde: TAXRATE_HOOG, confidence: 0.55, telling: 4, oranje: true, reden: 'gesplitste stem', app_bevestigd: true },
        // Geen project in het geheugen: anders vult de client-prefill het lege veld en is er geen conflict-chip meer.
        project: { waarde: null, confidence: 0, telling: 0, oranje: true, reden: 'geen observaties', app_bevestigd: false },
      },
      { periode: { jaar: 2026, week_van: 27, week_tot: 27, herkomst: 'afgeleid_van_factuurdatum', tekst: null } },
    )
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Grootboek', { exact: false })[0]).toHaveValue('7005 · Inhuur steiger'))
    await waitFor(() => expect(screen.getAllByLabelText(/^Project/).length).toBeGreaterThan(0))
    // Zonder één klik op "Herkomst tonen":
    expect(screen.getByTestId('regel-gb-chip')).toHaveTextContent('geheugen wisselend — controleer')
    expect(screen.getByTestId('regel-gb-chip')).toHaveClass('afwijking')
    expect(screen.getByTestId('regel-project-factuur-chip')).toHaveTextContent('factuur noemt een ander project — kies zelf')
    expect(screen.getByTestId('periode-chip')).toHaveTextContent('week van de factuurdatum (aanname)')
    await waitFor(() => expect(screen.getAllByText(/Geheugen 55%/).length).toBeGreaterThan(0))
    expect(screen.getAllByText(/Geheugen 55%/)[0]).toHaveClass('afwijking')
    // … maar het groene geheugen op het grootboek en de groene "uit factuur (21%)" niet.
    expect(screen.queryByText('Geheugen 100%')).toBeNull()
    expect(screen.queryByText('uit factuur (21%)')).toBeNull()
    expect(screen.getAllByRole('button', { name: 'Herkomst tonen' })).toHaveLength(3)
  })

  it('een opgeslagen stand "Herkomst tonen" uit de browsersessie opent het blok direct uitgeklapt', async () => {
    window.sessionStorage.setItem(`${HERKOMST_OPSLAGSLEUTEL_PREFIX}regels`, '1')
    installFetchMock(TWEE_REGELS, GEHEUGEN_GROEN)
    renderPanel()
    await waitFor(() => expect(screen.getAllByLabelText('Grootboek', { exact: false })[0]).toHaveValue('7005 · Inhuur steiger'))
    expect(screen.getByTestId('herkomst-tonen-regels')).toHaveTextContent('Herkomst verbergen')
    expect(screen.getAllByTestId('regel-gb-chip')[0]).toHaveTextContent('uit geheugen')
    expect(screen.getByTestId('herkomst-tonen-crediteur')).toHaveTextContent('Herkomst tonen')
    expect(screen.queryByText(/herkend op/)).toBeNull()
  })
})
