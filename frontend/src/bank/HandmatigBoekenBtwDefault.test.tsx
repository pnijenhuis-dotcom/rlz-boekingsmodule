// Bug-onderzoek 15-09 (Peter 14/15-09, L.H.G. Holding "Kosten mobiele telefonie"): de casus bleek een KPN-incasso die
// vanuit het bankscherm direct op 4404 geboekt werd — de btw-code bleef leeg omdat het formulier de gekozen rekening niet
// volgde. Nu: btw volgt de grootboek-default (RLZ-default > historie-default, één bron met het controlescherm) mét chip;
// kiest de mens zelf een btw-code, dan wint die; een rekening zonder default maakt een gevolgde btw weer leeg.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../ui/basis'
import { BankDetailScreen } from './BankDetailScreen'
import type { MutatieDto } from './bankApi'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-4000-8000-000000000001'
const REKENING_ID = 'cccccccc-0000-4000-8000-000000000003'
const MUTATIE_KPN = 'cccccccc-0000-4000-8000-000000000a01'
const GB_4404 = '22222222-0000-0000-0000-000000004404' // Kosten mobiele telefonie — historie-default hoog (6×)
const GB_4303 = '22222222-0000-0000-0000-000000004303' // Verzekering vervoermiddelen — geen default
const GB_4408 = '22222222-0000-0000-0000-000000004408' // Kantoorkosten — RLZ-default laag
const TAXRATE_HOOG = 'dddddddd-0000-0000-0000-000000000021'
const TAXRATE_LAAG = 'dddddddd-0000-0000-0000-000000000009'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const rekening = {
  id: REKENING_ID,
  naam: 'Rabobank zakelijk',
  iban: 'NL39 RABO 0300 0652 64',
  rekening_type: 1,
  is_kas: false,
  saldo: '18211.44',
  saldo_datum: '2026-09-11',
  open_mutaties: 1,
  heeft_aanlevering: true,
  laatste_import: { datum: '2026-09-11', bron: '1', type: 'MT940', bestandsnaam: 'x.940' },
  probe_fout: null,
}

function mutatieKpn(): MutatieDto {
  return {
    id: MUTATIE_KPN,
    boekdatum: '2026-09-11',
    bedrag: '-83.99',
    open_bedrag: '-83.99',
    tegenpartij_naam: 'KPN B.V.',
    omschrijving: 'Factuur 04-09-2026, klantnummer 20198069005, kpn.com/mobielefactuur',
    tegenrekening_iban: 'NL02ABNA0123456789',
    voorstel: {
      soort: 'handmatig',
      kleur: 'oranje',
      bron: 'geen open post of regel',
      reden: 'Geen open post of regel gevonden — handmatig beoordelen.',
      payment_item_id: null,
      open_post: null,
      regel_id: null,
      regels: [],
    },
    afletter_opdracht: null,
    regel_voorstel: null,
    deels_afgeletterd: false,
    rlz_koppelingen: [],
  }
}

function installFetchMock(boekenAanroepen: { body: unknown }[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/auth/administraties')) return Promise.resolve(jsonResponse({ administraties: [{ id: ADMINISTRATIE_ID, naam: 'L.H.G. Holding B.V.' }] }))
      if (url.endsWith('/bank/rekeningen')) {
        return Promise.resolve(jsonResponse({ rekeningen: [rekening], laatste_sync_op: '2026-09-11T06:00:00Z', ooit_gesynchroniseerd: true, heeft_bankaanlevering: true }))
      }
      if (url.endsWith('/bank/sync-achtergrond') && method === 'POST') {
        return Promise.resolve(jsonResponse({ run_id: null, status: 'overgeslagen', overgeslagen: true, laatste_sync_op: null, resultaat: null, fout_reden: null }, 202))
      }
      if (url.includes('/direct-boeken') && method === 'POST') {
        boekenAanroepen.push({ body: JSON.parse(String(init?.body)) as unknown })
        return Promise.resolve(jsonResponse({ boeking_id: 'x', rlz_boekstuknummer: 'RLZ-07-00002805', al_eerder_geboekt: false, vaste_regel_aangemaakt: false }, 201))
      }
      if (url.includes('/mutaties') && method === 'GET') return Promise.resolve(jsonResponse({ mutaties: [mutatieKpn()] }))
      if (url.includes('/afletter-opdrachten')) return Promise.resolve(jsonResponse({ opdrachten: [], aantal_oud: 0, toon_oud: false, oud_na_dagen: 30 }))
      if (url.endsWith('/bank/aanbetalingen')) return Promise.resolve(jsonResponse({ aanbetalingen: [] }))
      if (url.endsWith('/splitsingen')) return Promise.resolve(jsonResponse({ splitsingen: [] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [] }))
      if (url.includes('/grootboek')) {
        return Promise.resolve(
          jsonResponse({
            rekeningen: [
              { ledger_id: GB_4303, code: '4303', naam: 'Verzekering vervoermiddelen', soort: 2, standaard_taxrate_id: null },
              { ledger_id: GB_4404, code: '4404', naam: 'Kosten mobiele telefonie', soort: 2, standaard_taxrate_id: null, historie_taxrate_id: TAXRATE_HOOG, historie_taxrate_n: 6 },
              { ledger_id: GB_4408, code: '4408', naam: 'Kantoorkosten', soort: 2, standaard_taxrate_id: TAXRATE_LAAG },
            ],
          }),
        )
      }
      if (url.includes('/btw-codes')) {
        return Promise.resolve(jsonResponse({ btw_codes: [{ id: TAXRATE_HOOG, naam: 'NL, Hoog Tarief', percentage: '0.21' }, { id: TAXRATE_LAAG, naam: 'NL, Laag Tarief', percentage: '0.09' }] }))
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderScherm() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[`/bank/${ADMINISTRATIE_ID}`]}>
        <Routes>
          <Route path="/bank/:administratieId" element={<BankDetailScreen />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  )
}

async function kiesCombobox(label: RegExp, zoek: string, optieTekst: RegExp) {
  const input = screen.getByRole('combobox', { name: label })
  await userEvent.clear(input)
  await userEvent.click(input)
  await userEvent.type(input, zoek)
  await userEvent.click(await screen.findByRole('option', { name: optieTekst }))
}

async function openFormulier(): Promise<HTMLElement> {
  const rij = (await screen.findByText(/kpn.com\/mobielefactuur/)).closest('tr') as HTMLElement
  await userEvent.click(within(rij).getByRole('button', { name: 'Boeken…' }))
  return within(rij).getByTestId('handmatig-boeken-form')
}

describe('Bank › direct boeken — btw volgt de grootboek-default (15-09, casus LHG/KPN)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('rekening mét historie-default: btw wordt gevuld mét oranje chip "meestal op deze rekening (6×)" en de boeking splitst btw uit het inclusief-bedrag', async () => {
    const aanroepen: { body: unknown }[] = []
    installFetchMock(aanroepen)
    renderScherm()
    const form = await openFormulier()
    await kiesCombobox(/Grootboekrekening/, '4404', /Kosten mobiele telefonie/)
    const chip = within(form).getByTestId('handmatig-btw-chip')
    expect(chip).toHaveTextContent('meestal op deze rekening (6×)')
    expect(chip.className).toContain('afwijking')
    expect(screen.getByRole('combobox', { name: /Btw-code/ })).toHaveValue('21% · NL, Hoog Tarief')
    await userEvent.click(within(form).getByRole('button', { name: /Boeken in RLZ/ }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    const body = aanroepen[0].body as { regels: { netto_bedrag: string; btw_bedrag: string | null; taxrate_id: string | null }[] }
    // −83,99 incl → netto −69,41 + btw −14,58 (exact de RLZ-boeking RLZ-07-00002805 van 14-09).
    expect(body.regels[0]).toMatchObject({ netto_bedrag: '-69.41', btw_bedrag: '-14.58', taxrate_id: TAXRATE_HOOG })
  })

  it('RLZ-default wint (grijze chip "standaard grootboek"); rekening zonder default maakt een gevolgde btw weer leeg', async () => {
    installFetchMock([])
    renderScherm()
    const form = await openFormulier()
    await kiesCombobox(/Grootboekrekening/, '4408', /Kantoorkosten/)
    expect(within(form).getByTestId('handmatig-btw-chip')).toHaveTextContent('standaard grootboek')
    expect(screen.getByRole('combobox', { name: /Btw-code/ })).toHaveValue('9% · NL, Laag Tarief')
    await kiesCombobox(/Grootboekrekening/, '4303', /Verzekering vervoermiddelen/)
    expect(within(form).queryByTestId('handmatig-btw-chip')).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /Btw-code/ })).toHaveValue('')
  })

  it('kiest de mens zelf een btw-code, dan wint die — ook bij een latere rekening-wissel, zonder chip', async () => {
    const aanroepen: { body: unknown }[] = []
    installFetchMock(aanroepen)
    renderScherm()
    const form = await openFormulier()
    await kiesCombobox(/Btw-code/, 'Laag', /Laag Tarief/)
    await kiesCombobox(/Grootboekrekening/, '4404', /Kosten mobiele telefonie/)
    expect(within(form).queryByTestId('handmatig-btw-chip')).not.toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: /Btw-code/ })).toHaveValue('9% · NL, Laag Tarief')
    await userEvent.click(within(form).getByRole('button', { name: /Boeken in RLZ/ }))
    await waitFor(() => expect(aanroepen).toHaveLength(1))
    expect((aanroepen[0].body as { regels: { taxrate_id: string }[] }).regels[0].taxrate_id).toBe(TAXRATE_LAAG)
  })
})
