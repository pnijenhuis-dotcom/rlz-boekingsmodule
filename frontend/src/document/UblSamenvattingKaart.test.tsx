import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { UblSamenvattingKaart } from './UblSamenvattingKaart'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const XML = '<?xml version="1.0"?>\n<doc:Invoice>\n  <cbc:ID>RLZ-2080142898</cbc:ID>\n</doc:Invoice>'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function mockKaart(body: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) =>
      Promise.resolve(url.endsWith('/ubl-samenvatting') ? jsonResponse(body, status) : new Response(null, { status: 404 })),
    ),
  )
}

const LEESBAAR = {
  leesbaar: true,
  reden: null,
  bestandsnaam: 'Universal Nederland B.V - RLZ-2080142898 - 2026-07-20.xml',
  is_creditnota: false,
  leverancier: 'Universal Nederland B.V.',
  afnemer: 'Universal Steigerbouw B.V.',
  factuurnummer: 'RLZ-2080142898',
  factuurdatum: '2026-07-20',
  vervaldatum: '2026-08-19',
  valuta: 'EUR',
  totaal_excl: '775.26',
  totaal_btw: '162.80',
  totaal_incl: '938.06',
  kvk_nummer: '91000001',
  btw_nummer: 'NL100000001B01',
  iban: 'NL95KETN1000000010',
  leverancier_adres: 'Steigerweg 1, 1234 AB Eindhoven, NL',
  betalingskenmerk: null,
  note: 'Werk: 26084 - Opdrachtgever A (W03611)',
  project_tekst: '26084 - Opdrachtgever A (W03611)',
  regelaantal: 1,
  regels: [{ volgnummer: 1, omschrijving: 'Huur steigermateriaal juli', aantal: '1', eenheid: 'EA', netto_bedrag: '775.26', btw_percentage: '21', btw_bedrag: '162.80', soort: null }],
  onvolledig: null,
}

describe('UblSamenvattingKaart (FV-01, 25-09) — nooit ruwe XML als standaardweergave', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de leesbare kaart (kop, totalen, identiteit, regels) en de XML pas ná "XML-bron tonen"', async () => {
    mockKaart(LEESBAAR)
    render(<UblSamenvattingKaart administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} xmlTekst={XML} bestandsnaam="x.xml" />)

    await screen.findByText('Universal Nederland B.V.')
    expect(screen.getByText('Universal Steigerbouw B.V.')).toBeInTheDocument()
    expect(screen.getByText('RLZ-2080142898')).toBeInTheDocument()
    expect(screen.getByText('20-07-2026')).toBeInTheDocument()
    expect(screen.getByText('€ 938,06 incl.')).toBeInTheDocument()
    expect(screen.getByText(/KvK 91000001 · btw NL100000001B01 · IBAN NL95KETN1000000010/)).toBeInTheDocument()
    expect(screen.getByText('Huur steigermateriaal juli')).toBeInTheDocument()
    expect(screen.getByText('project uit factuur')).toBeInTheDocument()
    // De ruwe XML staat NIET standaard in beeld.
    expect(screen.queryByTestId('xml-bron')).not.toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: 'XML-bron tonen' })
    expect(toggle).toHaveClass('linkbtn')
    await userEvent.click(toggle)
    expect(screen.getByTestId('xml-bron')).toHaveTextContent('RLZ-2080142898')
    await userEvent.click(screen.getByRole('button', { name: 'XML-bron verbergen' }))
    expect(screen.queryByTestId('xml-bron')).not.toBeInTheDocument()
  })

  it('niet-leesbare XML = chip "XML niet leesbaar: ‹reden›" + bron op verzoek, geen kale fout', async () => {
    mockKaart({ leesbaar: false, reden: 'gecomprimeerd bestand (gzip) — lever de XML zelf aan', regels: [] })
    render(<UblSamenvattingKaart administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} xmlTekst={XML} bestandsnaam="export.xml" />)

    const chip = await screen.findByTestId('xml-niet-leesbaar-chip')
    expect(chip).toHaveTextContent('XML niet leesbaar: gecomprimeerd bestand (gzip) — lever de XML zelf aan')
    expect(screen.getByText(/export\.xml/)).toBeInTheDocument()
    expect(screen.queryByTestId('xml-bron')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'XML-bron tonen' })).toBeInTheDocument()
  })

  it('onvolledige UBL (geen regels) toont de kaart mét chip "XML niet leesbaar: UBL onvolledig …"', async () => {
    mockKaart({ ...LEESBAAR, regelaantal: 0, regels: [], onvolledig: 'UBL onvolledig — ontbreekt: factuurregels (InvoiceLine)' })
    render(<UblSamenvattingKaart administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} xmlTekst={XML} bestandsnaam="x.xml" />)

    await screen.findByText('Universal Nederland B.V.')
    expect(screen.getByTestId('xml-niet-leesbaar-chip')).toHaveTextContent('factuurregels (InvoiceLine)')
    expect(screen.getByText('Geen factuurregels in de UBL.')).toBeInTheDocument()
  })

  it('routefout = zichtbare melding, XML-bron blijft bereikbaar', async () => {
    mockKaart({ detail: 'x is geen XML-document' }, 422)
    render(<UblSamenvattingKaart administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} xmlTekst={XML} bestandsnaam="x.xml" />)

    await screen.findByRole('button', { name: 'XML-bron tonen' })
    expect(screen.getByText(/geen XML-document|kon niet worden geladen/)).toBeInTheDocument()
  })
})
