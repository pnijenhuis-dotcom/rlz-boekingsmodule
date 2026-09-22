import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BtwPlichtigRij, herkomstTekst, kandidaatTekst, type BtwPlichtigDto } from './BtwPlichtigRij'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stand(over: Partial<BtwPlichtigDto> = {}): BtwPlichtigDto {
  return {
    administratie_id: ADMINISTRATIE_ID,
    btw_plichtig: true,
    bron: null,
    gewijzigd_op: null,
    rlz_signaal: null,
    rlz_gezien_op: null,
    geen_btw_taxrate_id: 'bbbbbbbb-0000-0000-0000-000000000010',
    geen_btw_taxrate_naam: 'NL, Geen BTW (Vrijgesteld)',
    kandidaat: false,
    kandidaat_reden: null,
    ...over,
  }
}

function installFetchMock(begin: BtwPlichtigDto, putAanroepen: unknown[] = []) {
  let huidig = begin
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (!url.endsWith('/btw-plichtig')) return Promise.resolve(new Response(null, { status: 404 }))
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { btw_plichtig: boolean }
        putAanroepen.push(body)
        huidig = { ...huidig, btw_plichtig: body.btw_plichtig, bron: 'mens', kandidaat: false, kandidaat_reden: null }
      }
      return Promise.resolve(jsonResponse(huidig))
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BtwPlichtigRij (BUG Peter 22-09, casus VGG / Lacy Lion)', () => {
  it('pure teksten: herkomst en kandidaat', () => {
    expect(herkomstTekst(stand())).toBe('nog nooit bevestigd (aanname: btw-plichtig)')
    expect(herkomstTekst(stand({ bron: 'rlz' }))).toContain('Reeleezee')
    expect(herkomstTekst(stand({ bron: 'mens' }))).toContain('kantoor')
    expect(kandidaatTekst(stand())).toBeNull()
    expect(kandidaatTekst(stand({ kandidaat: true, kandidaat_reden: 'rlz_signaal' }))).toContain('EnableTaxReporting uit')
    expect(kandidaatTekst(stand({ kandidaat: true, kandidaat_reden: 'geen_tarief_met_percentage' }))).toContain('boven 0 %')
  })

  it('toont de stand, het RLZ-signaal en de kandidaat-regel; "Niet btw-plichtig" doet een PUT en toont de geen-btw-code', async () => {
    const gebruiker = userEvent.setup()
    const puts: unknown[] = []
    installFetchMock(stand({ rlz_signaal: false, kandidaat: true, kandidaat_reden: 'rlz_signaal' }), puts)
    render(<BtwPlichtigRij administratieId={ADMINISTRATIE_ID} naam="Vastgoedgroep Nederland B.V." />)
    await waitFor(() => expect(screen.getByLabelText('Btw-plichtig voor Vastgoedgroep Nederland B.V.')).toBeChecked())
    expect(screen.getByTestId('btw-plichtig-herkomst')).toHaveTextContent('nog nooit bevestigd')
    expect(screen.getByTestId('btw-plichtig-rlz-signaal')).toHaveTextContent('Reeleezee: btw-aangifte uit')
    expect(screen.getByTestId('btw-plichtig-kandidaat')).toHaveTextContent('Kandidaat “niet btw-plichtig”')
    expect(screen.queryByTestId('btw-plichtig-geen-btw-code')).not.toBeInTheDocument()

    await gebruiker.click(screen.getByRole('button', { name: 'Niet btw-plichtig' }))
    await waitFor(() => expect(screen.getByLabelText('Btw-plichtig voor Vastgoedgroep Nederland B.V.')).not.toBeChecked())
    expect(puts).toEqual([{ btw_plichtig: false }])
    expect(screen.getByTestId('btw-plichtig-herkomst')).toHaveTextContent('bevestigd door het kantoor')
    expect(screen.getByTestId('btw-plichtig-geen-btw-code')).toHaveTextContent('NL, Geen BTW (Vrijgesteld)')
    expect(screen.queryByTestId('btw-plichtig-kandidaat')).not.toBeInTheDocument()
    expect(screen.getByText('uit — btw in de kosten')).toBeInTheDocument()
  })

  it('schakelaar aan → PUT true; gearchiveerd = uitgeschakeld', async () => {
    const gebruiker = userEvent.setup()
    const puts: unknown[] = []
    installFetchMock(stand({ btw_plichtig: false, bron: 'mens' }), puts)
    render(<BtwPlichtigRij administratieId={ADMINISTRATIE_ID} naam="X" />)
    await waitFor(() => expect(screen.getByLabelText('Btw-plichtig voor X')).not.toBeChecked())
    await gebruiker.click(screen.getByLabelText('Btw-plichtig voor X'))
    await waitFor(() => expect(puts).toEqual([{ btw_plichtig: true }]))
    expect(await screen.findByText('opgeslagen')).toBeInTheDocument()
  })

  it('laadfout is zichtbaar, geen stille lege rij', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse({ detail: 'Onbekende administratie' }, 404))))
    render(<BtwPlichtigRij administratieId={ADMINISTRATIE_ID} naam="X" />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })
})
