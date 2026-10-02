import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BevindingDto } from './reconciliatieApi'
import { FactuurOpvragenActie, isIcInkoopOntbreekt } from './IcActies'

// Run D 02-10 blok D (Peter 02-10): "Factuur opvragen bij ‹BV›" op een ic_inkoop_ontbreekt-bevinding — de server bouwt
// een mailconcept (nooit automatisch verzonden), de rij toont 'm in een dialoog mét mailto + kopiëren.

function bevinding(overrides: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-ic-1',
    run_id: 'run-1',
    blok: 'intercompany',
    soort: 'afwijking',
    administratie_id: 'adm-stb',
    administratie_naam: 'Universal Steigerbouw B.V.',
    vingerafdruk: 'vaf',
    tekst: 'AFWIJKING  factuur=2080143084 Universal Nederland B.V. → Universal Steigerbouw B.V. soort=ic_inkoop_ontbreekt …',
    titel: 'Onderlinge factuur ontbreekt bij ontvanger · Universal Nederland B.V. → Universal Steigerbouw B.V. · 2080143084',
    wat: '…',
    doe: '…',
    details: [],
    sinds: '2026-10-03T04:30:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: {
      afwijking_soort: 'ic_inkoop_ontbreekt',
      verkoper_naam: 'Universal Nederland B.V.',
      ontvanger_naam: 'Universal Steigerbouw B.V.',
      nummer: '2080143084',
      datum: '2026-08-19',
      bedrag_verkoop: '21420.63',
    },
    doel_pad: null,
    ...overrides,
  } as BevindingDto
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const CONCEPT = {
  bevinding_id: 'bev-ic-1',
  administratie_id: 'adm-stb',
  verkoper_naam: 'Universal Nederland B.V.',
  ontvanger_naam: 'Universal Steigerbouw B.V.',
  nummer: '2080143084',
  datum: '2026-08-19',
  bedrag: '21420.63',
  aan: null,
  aan_tekst: '‹vul het adres van de boekhouding van Universal Nederland B.V. in›',
  onderwerp: 'Factuur 2080143084 aan Universal Steigerbouw B.V. — graag de PDF/UBL naar onze boekhoudmail',
  tekst: 'Beste administratie van Universal Nederland B.V.,\n\nIn jullie verkoopboek staat factuur 2080143084 …',
  mailto: 'mailto:?subject=Factuur%202080143084&body=Beste',
  intake_adres: 'facturen@ak-nijenhuis.nl',
}

describe('IcActies (run D 02-10 blok D — Factuur opvragen bij ‹BV›)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('herkent alleen ic_inkoop_ontbreekt in blok intercompany mét administratie', () => {
    expect(isIcInkoopOntbreekt(bevinding())).toBe(true)
    expect(isIcInkoopOntbreekt(bevinding({ blok: 'documenten' }))).toBe(false)
    expect(isIcInkoopOntbreekt(bevinding({ administratie_id: null }))).toBe(false)
    expect(isIcInkoopOntbreekt(bevinding({ detail: { afwijking_soort: 'ic_verkoop_ontbreekt' } }))).toBe(false)
    expect(isIcInkoopOntbreekt(bevinding({ soort: 'geaccepteerd' }))).toBe(false)
  })

  it('één klik → POST mét administratie; het concept verschijnt in een dialoog mét aan-plaatshouder, onderwerp, tekst en mailto', async () => {
    const aanroepen: { url: string; body: unknown }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse(CONCEPT))
      }),
    )
    const meldingen: string[] = []
    render(<FactuurOpvragenActie bevinding={bevinding()} onGelukt={(m) => meldingen.push(m)} />)
    const knop = screen.getByRole('button', { name: /Factuur 2080143084 opvragen bij Universal Nederland B.V./ })
    expect(knop).toHaveTextContent('Factuur opvragen bij Universal Nederland B.V.')
    await userEvent.click(knop)
    await waitFor(() => expect(screen.getByTestId('ic-factuur-opvragen-dialoog')).toBeInTheDocument())
    expect(aanroepen).toHaveLength(1)
    expect(aanroepen[0].url).toContain('/reconciliatie/intercompany/bev-ic-1/factuur-opvragen')
    expect(aanroepen[0].body).toEqual({ administratie_id: 'adm-stb' })
    expect(screen.getByTestId('ic-concept-aan')).toHaveTextContent('vul het adres van de boekhouding van Universal Nederland B.V. in')
    expect(screen.getByTestId('ic-concept-onderwerp')).toHaveTextContent('Factuur 2080143084 aan Universal Steigerbouw B.V.')
    expect(screen.getByTestId('ic-concept-tekst')).toHaveTextContent('Beste administratie van Universal Nederland B.V.')
    expect(screen.getByTestId('ic-concept-mailto')).toHaveAttribute('href', CONCEPT.mailto)
    expect(meldingen[0]).toContain('nog niet verzonden')
  })

  it('409/404 van de server staat zichtbaar naast de knop, nooit stil', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse({ detail: 'Alleen op een bevinding ic_inkoop_ontbreekt is een factuur op te vragen' }, 409))))
    render(<FactuurOpvragenActie bevinding={bevinding()} onGelukt={() => undefined} />)
    await userEvent.click(screen.getByRole('button', { name: /opvragen bij/ }))
    await waitFor(() => expect(screen.getByText(/Alleen op een bevinding ic_inkoop_ontbreekt/)).toBeInTheDocument())
    expect(screen.queryByTestId('ic-factuur-opvragen-dialoog')).not.toBeInTheDocument()
  })
})
