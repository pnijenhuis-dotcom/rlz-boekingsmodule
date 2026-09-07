import { cleanup, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'
import { VerplichtingenPaneel, WeekstatenPaneel } from './ProjectDetailVerrijking'
import type { ProjectVerplichtingDto, WeekstatenStandDto } from './projectenApi'

// Projectdetail-verrijking (C5 07-09): verplichtingen mét verbruiksbalk (VerbruiksBalk-patroon: teal/groen/rood)
// + de weekstaten-/planningstand per week mét handelingslinks. Presentatie only.

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'

const OVERSCHREDEN: ProjectVerplichtingDto = {
  document_id: 'doc-1',
  offertenummer: 'OFF-1',
  soort_label: 'offerte',
  leverancier_naam: 'Confide Bouw B.V.',
  omschrijving: 'Steigerwerk',
  goedgekeurd_excl: '5000.00',
  verbruikt_excl: '6000.00',
  percentage: 120,
  over_excl: '1000.00',
  geldig_tot: '2026-12-31',
  status: 'overschreden',
  open_facturen_aantal: 2,
  open_facturen_excl: '800.00',
}
const VERVALLEN: ProjectVerplichtingDto = { ...OVERSCHREDEN, document_id: 'doc-2', offertenummer: 'OFF-2', verbruikt_excl: '0.00', percentage: 0, over_excl: null, status: 'vervallen', open_facturen_aantal: 0, open_facturen_excl: '0.00' }

const STAND: WeekstatenStandDto = {
  van_toepassing: true,
  ontbrekend_totaal: 1,
  te_keuren_totaal: 1,
  oudste_ontbrekende_jaar: 2026,
  oudste_ontbrekende_week: 35,
  weken: [
    { jaar: 2026, weeknummer: 36, maandag: '2026-08-31', gepland_personen: 2, gepland_dagen: '7.5', concept: 1, ingediend: 0, goedgekeurd: 0, corrigeren: 0, ontbrekend: 0, afgemeld: 0 },
    { jaar: 2026, weeknummer: 35, maandag: '2026-08-24', gepland_personen: 1, gepland_dagen: '5', concept: 0, ingediend: 0, goedgekeurd: 0, corrigeren: 0, ontbrekend: 1, afgemeld: 0 },
    { jaar: 2026, weeknummer: 34, maandag: '2026-08-17', gepland_personen: 1, gepland_dagen: '5', concept: 0, ingediend: 1, goedgekeurd: 0, corrigeren: 0, ontbrekend: 0, afgemeld: 0 },
    { jaar: 2026, weeknummer: 33, maandag: '2026-08-10', gepland_personen: 1, gepland_dagen: '5', concept: 0, ingediend: 0, goedgekeurd: 1, corrigeren: 0, ontbrekend: 0, afgemeld: 0 },
    { jaar: 2026, weeknummer: 32, maandag: '2026-08-03', gepland_personen: 1, gepland_dagen: '5', concept: 0, ingediend: 0, goedgekeurd: 0, corrigeren: 0, ontbrekend: 0, afgemeld: 1 },
    { jaar: 2026, weeknummer: 31, maandag: '2026-07-27', gepland_personen: 0, gepland_dagen: '0', concept: 0, ingediend: 0, goedgekeurd: 0, corrigeren: 0, ontbrekend: 0, afgemeld: 0 },
  ],
}

function renderIn(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe('VerplichtingenPaneel', () => {
  afterEach(cleanup)

  it('toont per verplichting de verbruiksbalk (rood bij overschrijding), de open-facturen-regel en de deep-link', () => {
    renderIn(<VerplichtingenPaneel administratieId={ADMIN} verplichtingen={[OVERSCHREDEN, VERVALLEN]} />)
    expect(screen.getByTestId('verplichtingen-paneel')).toHaveTextContent('1 overschreden')
    const rijen = screen.getAllByTestId('verplichting-rij')
    expect(rijen).toHaveLength(2)
    expect(within(rijen[0]).getByText('OFF-1')).toBeInTheDocument()
    expect(within(rijen[0]).getByText(/offerte · Steigerwerk/)).toBeInTheDocument()
    expect(within(rijen[0]).getByText('Confide Bouw B.V.')).toBeInTheDocument()
    const balk = within(rijen[0]).getByTestId('verbruiks-balk-doc-1')
    expect(balk).toHaveClass('te-veel')
    expect(balk).toHaveTextContent('€ 6.000,00 / € 5.000,00')
    expect(balk).toHaveTextContent('€ 1.000,00 over')
    expect(within(rijen[0]).getByTestId('verbruiks-balk-doc-1-open')).toHaveTextContent('2 open facturen')
    expect(within(rijen[0]).getByText('overschreden')).toBeInTheDocument()
    expect(within(rijen[0]).getByRole('link', { name: 'Open verplichting OFF-1' })).toHaveAttribute('href', `/verplichting/${ADMIN}/doc-1`)
    // Vervallen = historie: eigen status, geen "over".
    expect(within(rijen[1]).getByText('vervallen')).toBeInTheDocument()
    expect(within(rijen[1]).getByTestId('verbruiks-balk-doc-2')).not.toHaveClass('te-veel')
  })

  it('lege stand = uitleg + link naar Inzicht › Verplichtingen', () => {
    renderIn(<VerplichtingenPaneel administratieId={ADMIN} verplichtingen={[]} />)
    expect(screen.getByTestId('verplichtingen-leeg')).toHaveTextContent(/Geen goedgekeurde offerte/)
    expect(screen.getByRole('link', { name: /Alle verplichtingen/ })).toHaveAttribute('href', '/verplichtingen')
  })
})

describe('WeekstatenPaneel', () => {
  afterEach(cleanup)

  it('toont de stand per week mét ontbrekend/te keuren/gekeurd/afgemeld en de handelingslinks', () => {
    renderIn(<WeekstatenPaneel administratieId={ADMIN} stand={STAND} />)
    expect(screen.getByTestId('weekstaten-ontbrekend')).toHaveTextContent('wk 35 ontbreekt')
    expect(screen.getByTestId('weekstaten-te-keuren')).toHaveTextContent('1 te keuren')
    expect(screen.getByRole('link', { name: /Herinneren of afmelden/ })).toHaveAttribute('href', `/meerwerk/planning-signalen?administratie_id=${ADMIN}`)
    expect(screen.getByRole('link', { name: /^Keuren/ })).toHaveAttribute('href', `/meerwerk?administratie=${ADMIN}`)
    const rijen = screen.getAllByTestId('weekstand-rij')
    expect(rijen).toHaveLength(6)
    expect(within(rijen[0]).getByText(/2 personen · 7,5 dagen/)).toBeInTheDocument()
    expect(within(rijen[0]).getByText('1 concept')).toBeInTheDocument()
    expect(within(rijen[1]).getByText('1 ontbreekt')).toBeInTheDocument()
    expect(within(rijen[2]).getByText('1 te keuren')).toBeInTheDocument()
    expect(within(rijen[3]).getByText('1 gekeurd')).toBeInTheDocument()
    expect(within(rijen[4]).getByText('1 afgemeld')).toBeInTheDocument()
    expect(within(rijen[1]).getByRole('link', { name: 'Planning week 35' })).toHaveAttribute('href', `/planning?administratie=${ADMIN}&week=2026-W35`)
  })

  it('rendert niets zonder uren-opt-in (niet van toepassing)', () => {
    renderIn(<WeekstatenPaneel administratieId={ADMIN} stand={{ ...STAND, van_toepassing: false, weken: [] }} />)
    expect(screen.queryByTestId('weekstaten-paneel')).toBeNull()
    renderIn(<WeekstatenPaneel administratieId={ADMIN} stand={null} />)
    expect(screen.queryByTestId('weekstaten-paneel')).toBeNull()
  })
})
