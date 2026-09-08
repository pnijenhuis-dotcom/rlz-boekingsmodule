import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'
import { alsUblVoorstel, isUblVoorstel } from './aiVoorstel'
import { exemplarenChipLabel } from '../werkvoorraad/DocumentenDeelscherm'

/** Blok 3 herstelrun "Basis eerst" 08-09 (casus BDO 6088744): een UBL-veldvoorstel is deterministisch — de
 * crediteur-kaart en "+ Nieuwe crediteur in RLZ" worden uit de XML gevuld (naam · KvK · btw · IBAN · adres, chip
 * "uit UBL"); een PDF waarvan de extractie nog loopt zegt dat in de dialoog i.p.v. stil lege velden te tonen.
 * Blok 4c: chip-label "N exemplaren samengevoegd/afgevoerd". Eigen testbestand (gedeelde panel-tests niet raken). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const TAXRATE_HOOG = 'dddddddd-0000-0000-0000-000000000021'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Het UBL-veldvoorstel zoals `documenten/ubl.py::UblVeldvoorstel.als_dict` 'm sinds 08-09 in de tijdlijn zet. */
const UBL_VOORSTEL = {
  bron: 'ubl',
  factuurnummer: '6099001',
  factuurdatum: '2026-07-02',
  vervaldatum: '2026-07-16',
  valuta: 'EUR',
  totaal_excl: '5500.00',
  totaal_incl: '6655.00',
  totaal_btw: '1155.00',
  leverancier_naam: 'Voorbeeld Accountancy, Tax & Legal B.V.',
  leverancier_adres: 'Kantoorlaan 12, 5611 AB Eindhoven, NL',
  kvk_nummer: '87654321',
  btw_nummer: 'NL123456782B01',
  btw_nummer_geverifieerd: false,
  iban: 'NL91ABNA0417164300',
  regelaantal: 1,
  ubl_regels: [
    { volgnummer: 1, omschrijving: 'Samenstellen jaarrekening', netto_bedrag: '5500.00', btw_percentage: '21', btw_bedrag: '1155.00', taxrate_id: TAXRATE_HOOG, btw_bron: 'factuur' },
  ],
  vendor_suggestie: null,
  vendor_waarschuwing: null,
}

const BOEKVOORSTEL = {
  document_id: DOCUMENT_ID,
  vendor_id: null,
  referentie: '6099001',
  factuurdatum: '2026-07-02',
  vervaldatum: '2026-07-16',
  totaalbedrag: '6655.00',
  rlz_boekstuknummer: null,
  opgeslagen: true,
  regels: [
    { id: null, ledger_id: null, taxrate_id: TAXRATE_HOOG, project_id: null, netto_bedrag: '5500.00', btw_bedrag: '1155.00', omschrijving: 'Samenstellen jaarrekening', btw_bron: 'factuur', gb_bron: null, gb_voorstel_detail: null },
  ],
  regels_samenvoegen: false,
  samenvoegen_toegestaan: true,
  samengevoegde_regel: null,
}

function installFetchMock(opties: { boekvoorstel?: Record<string, unknown>; crediteurAanroepen?: unknown[] } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') return Promise.resolve(new Response(null, { status: 404 }))
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [] }))
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [{ id: TAXRATE_HOOG, naam: 'NL, Hoog Tarief', percentage: 0.21 }] }))
      if (url.endsWith('/crediteuren') && init?.method === 'POST') {
        opties.crediteurAanroepen?.push(JSON.parse(String(init.body)))
        return Promise.resolve(jsonResponse({ id: 'eeeeeeee-0000-0000-0000-000000000042', naam: 'Voorbeeld Accountancy, Tax & Legal B.V.' }, 201))
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: 'eeeeeeee-0000-0000-0000-000000000099', naam: 'Technische Unie' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse({ ...BOEKVOORSTEL, ...(opties.boekvoorstel ?? {}) }))
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') return Promise.resolve(jsonResponse({}))
      if (url.endsWith('/boekvoorstel/checks') && init?.method === 'POST') return Promise.resolve(new Response(null, { status: 404 }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('BoekvoorstelPanel — UBL deterministisch (blok 3 08-09)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('alsUblVoorstel herkent bron ubl én het legacy-voorstel zonder bron (ubl_regels); AI/template niet', () => {
    expect(isUblVoorstel(UBL_VOORSTEL)).toBe(true)
    expect(isUblVoorstel({ factuurnummer: '1', ubl_regels: [] })).toBe(true)
    expect(isUblVoorstel({ bron: 'ai', factuurnummer: '1' })).toBe(false)
    expect(isUblVoorstel(null)).toBe(false)
    const ubl = alsUblVoorstel(UBL_VOORSTEL)
    expect(ubl?.kvk_nummer).toBe('87654321')
    expect(ubl?.iban).toBe('NL91ABNA0417164300')
    expect(ubl?.leverancier_adres).toBe('Kantoorlaan 12, 5611 AB Eindhoven, NL')
  })

  it('zonder crediteur-match toont de kaart de UBL-naam, de nummers "uit UBL" en vult "+ Nieuwe crediteur" uit de XML', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: unknown[] = []
    installFetchMock({ crediteurAanroepen: aanroepen })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="te_controleren"
        veldvoorstel={UBL_VOORSTEL}
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByText(/UBL: „Voorbeeld Accountancy, Tax & Legal B.V.”/)).toBeInTheDocument())
    expect(screen.queryByText(/AI las:/)).not.toBeInTheDocument()
    expect(screen.getByText('btw NL123456782B01')).toBeInTheDocument()
    expect(screen.getByText('KvK 87654321')).toBeInTheDocument()
    expect(screen.getByText('uit UBL')).toBeInTheDocument()

    await gebruiker.click(screen.getByRole('button', { name: '+ Nieuwe crediteur in RLZ' }))
    const dialoog = await screen.findByRole('dialog')
    expect(within(dialoog).getByLabelText('Naam')).toHaveValue('Voorbeeld Accountancy, Tax & Legal B.V.')
    expect(within(dialoog).getByLabelText(/KvK-nummer/)).toHaveValue('87654321')
    expect(within(dialoog).getByLabelText(/Btw-nummer/)).toHaveValue('NL123456782B01')
    expect(within(dialoog).getByLabelText(/IBAN/)).toHaveValue('NL91ABNA0417164300')
    expect(within(dialoog).getByTestId('nieuwe-crediteur-adres')).toHaveTextContent('Kantoorlaan 12, 5611 AB Eindhoven, NL')
    expect(within(dialoog).getAllByText('uit UBL').length).toBe(3)
    expect(within(dialoog).queryByTestId('nieuwe-crediteur-verwerking-loopt')).not.toBeInTheDocument()

    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Aanmaken in RLZ ✓' }))
    await waitFor(() =>
      expect(aanroepen).toEqual([
        {
          naam: 'Voorbeeld Accountancy, Tax & Legal B.V.',
          kvk_nummer: '87654321',
          btw_nummer: 'NL123456782B01',
          iban: 'NL91ABNA0417164300',
          document_id: DOCUMENT_ID,
        },
      ]),
    )
  })

  it('PDF waarvan de extractie nog loopt: de dialoog zegt "verwerking loopt — velden volgen" i.p.v. stil leeg', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ boekvoorstel: { referentie: null, factuurdatum: null, vervaldatum: null, totaalbedrag: null, opgeslagen: false, regels: [] } })
    render(
      <BoekvoorstelPanel
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status="extractie_wachtrij"
        veldvoorstel={null}
        onGeboekt={() => {}}
        onHersteld={() => {}}
      />,
    )
    await gebruiker.click(await screen.findByRole('button', { name: '+ Nieuwe crediteur in RLZ' }))
    const dialoog = await screen.findByRole('dialog')
    expect(within(dialoog).getByTestId('nieuwe-crediteur-verwerking-loopt')).toHaveTextContent(/Verwerking loopt — de velden uit de factuur volgen/)
    expect(within(dialoog).getByLabelText('Naam')).toHaveValue('')
    expect(within(dialoog).queryByText('uit UBL')).not.toBeInTheDocument()
  })
})

describe('exemplarenChipLabel (blok 4c 08-09)', () => {
  it('benoemt samengevoegd, afgevoerd of beide — enkelvoud bij één exemplaar', () => {
    expect(exemplarenChipLabel(2, 0)).toBe('2 exemplaren samengevoegd')
    expect(exemplarenChipLabel(1, 1)).toBe('1 exemplaar afgevoerd')
    expect(exemplarenChipLabel(3, 2)).toBe('3 exemplaren samengevoegd/afgevoerd')
  })
})
