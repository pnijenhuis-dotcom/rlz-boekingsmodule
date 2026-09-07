import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { AutomatiseringenBlok } from './AutomatiseringenBlok'
import { ReconciliatieScreen } from './ReconciliatieScreen'
import type { AutomatiseringenDto, AutomatiseringTellerDto, BevindingDto, BevindingenLijstDto } from './reconciliatieApi'

// Blok "Automatiseringen (laatste 24 u)" (herstelrun 07-09 blok C, "geen stille no-op"): per automatisering
// stand + verwacht / gedaan / overgeslagen mét reden; uitgeschakeld = één regel "uit"; een ontbrekende harde
// voorwaarde en "zeven dagen stil" zijn zichtbaar als LET-OP — de bijbehorende bevinding in de lijst draagt
// de handeling "Naar de instelling →". De tellers komen mee in laatste_run.samenvatting (geen nieuw endpoint).

function teller(sleutel: string, label: string, extra: Partial<AutomatiseringTellerDto> = {}): AutomatiseringTellerDto {
  return {
    sleutel,
    label,
    stand: 'aan',
    stand_detail: null,
    bron: 'audit',
    dag: { verwacht: 0, gedaan: 0, overgeslagen: {} },
    week: { verwacht: 0, gedaan: 0, overgeslagen: {} },
    harde_voorwaarden: [],
    stil: false,
    ...extra,
  }
}

const AUTOMATISERINGEN: AutomatiseringenDto = {
  venster_uren: 24,
  stil_dagen: 7,
  berekend_op: '2026-09-07T04:30:00Z',
  tellers: [
    teller('autoboeken_inkoop', 'Autoboeken inkoop', {
      stand_detail: '3 leverancier(s)/koppeling(en) aan in 2 van 12 administraties',
      dag: { verwacht: 5, gedaan: 3, overgeslagen: { geen_eigenaar: 0, harde_checks: 1, urenmatch: 1 } },
      week: { verwacht: 20, gedaan: 14, overgeslagen: { geen_eigenaar: 0, harde_checks: 4, urenmatch: 2 } },
    }),
    teller('autoboeken_omzet', 'Autoboeken omzet', {
      stand: 'uit',
      stand_detail: '0 van 12 administraties',
    }),
    teller('bank_autoboeken', 'Bank-autoboeken/afletteren', {
      stand: 'deels',
      stand_detail: '4 van 12 administraties',
      dag: { verwacht: 26, gedaan: 25, overgeslagen: { volumerem: 1 } },
      week: { verwacht: 90, gedaan: 89, overgeslagen: { volumerem: 1 } },
      harde_voorwaarden: [{ categorie: 'volumerem', aantal: 1, administratie_id: 'aaaaaaaa-0000-0000-0000-000000000001', voorbeeld: 'volumerem: limiet 25' }],
    }),
    teller('terugkerend', 'Terugkerende facturen (herberekening)', {
      stand: 'altijd',
      dag: { verwacht: 12, gedaan: 0, overgeslagen: { fout: 0 } },
      week: { verwacht: 84, gedaan: 0, overgeslagen: { fout: 0 } },
      stil: true,
    }),
  ],
}

describe('AutomatiseringenBlok', () => {
  it('toont per automatisering stand, verwacht/gedaan/overgeslagen mét reden; uit = één regel; let-op zichtbaar', () => {
    render(<AutomatiseringenBlok data={AUTOMATISERINGEN} />)
    const blok = screen.getByTestId('automatiseringen-blok')
    expect(blok).toHaveTextContent('Automatiseringen (laatste 24 u)')
    expect(screen.getByTestId('automatiseringen-let-op')).toHaveTextContent('2 let-op')
    expect(blok).toHaveAttribute('open') // let-op → standaard uitgeklapt

    const inkoop = screen.getByTestId('automatisering-autoboeken_inkoop')
    const cellen = within(inkoop).getAllByRole('cell')
    expect(cellen[1]).toHaveTextContent('aan')
    expect(cellen[2]).toHaveTextContent('5')
    expect(cellen[3]).toHaveTextContent('3')
    // overgeslagen mét reden; de vaste categorie "geen eigenaar" blijft zichtbaar als 0 (kernprincipe 7)
    expect(cellen[4]).toHaveTextContent('2 (geen eigenaar/toewijzing: 0, harde checks blokkeren: 1, urenmatch niet groen: 1)')
    expect(cellen[5]).toHaveTextContent('14 / 20')

    // uitgeschakeld = één regel "uit", geen tellers
    const omzet = screen.getByTestId('automatisering-autoboeken_omzet')
    expect(omzet).toHaveTextContent('uit (0 van 12 administraties)')
    expect(omzet).toHaveTextContent('uitgeschakeld — geen bevinding')
    expect(within(omzet).getAllByRole('cell')).toHaveLength(3)

    // harde voorwaarde → chip "wacht op voorwaarde"; deels aan → detail zichtbaar
    const bank = screen.getByTestId('automatisering-bank_autoboeken')
    expect(within(bank).getByTestId('chip-harde-voorwaarde')).toHaveTextContent('wacht op voorwaarde')
    expect(bank).toHaveTextContent('deels aan (4 van 12 administraties)')
    expect(bank).toHaveTextContent('1 (volumerem bereikt: 1)')

    // zeven dagen stil → chip "stil"
    expect(screen.getByTestId('automatisering-terugkerend')).toHaveTextContent('stil')
  })

  it('zonder tellers (oude run of oude server) rendert het blok niets', () => {
    const { container } = render(<AutomatiseringenBlok data={null} />)
    expect(container).toBeEmptyDOMElement()
    render(<AutomatiseringenBlok data={{ ...AUTOMATISERINGEN, tellers: [] }} />)
    expect(screen.queryByTestId('automatiseringen-blok')).toBeNull()
  })

  it('zonder let-op is het blok ingeklapt maar wél aanwezig', () => {
    const rustig = { ...AUTOMATISERINGEN, tellers: [AUTOMATISERINGEN.tellers[0], AUTOMATISERINGEN.tellers[1]] }
    render(<AutomatiseringenBlok data={rustig} />)
    expect(screen.getByTestId('automatiseringen-blok')).not.toHaveAttribute('open')
    expect(screen.queryByTestId('automatiseringen-let-op')).toBeNull()
  })
})

// ---- in het scherm: het blok komt uit laatste_run.samenvatting, de LET-OP-rij draagt "Naar de instelling →"

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function fakeAccessToken(rol: string): string {
  const payload = btoa(JSON.stringify({ sub: 'gebruiker-id', rol })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

const LET_OP_AUTOMATISERING: BevindingDto = {
  id: 'a1',
  run_id: 'cccccccc-0000-0000-0000-000000000003',
  blok: 'automatisering',
  soort: 'let_op',
  administratie_id: null,
  administratie_naam: null,
  vingerafdruk: 'auto:noodrem',
  tekst: 'LET-OP     automatisering duplicaat_afvoer: 3 overgeslagen wegens ontbrekende harde voorwaarde [noodrem]',
  titel: 'Automatisering wacht op voorwaarde — Duplicaat-afvoer',
  wat: 'Duplicaat-afvoer sloeg 3 stuk(s) over: noodrem staat uit.',
  doe: 'Zet de noodrem weer aan (Instellingen › Boeken) of voer de gesignaleerde duplicaten handmatig af.',
  details: [{ label: 'vingerafdruk', waarde: 'auto:noodrem' }],
  sinds: '2026-09-07T04:30:00Z',
  nieuw: true,
  acceptatie: null,
  gezien: null,
  detail: { automatisering: 'duplicaat_afvoer', reden: 'noodrem', aantal: 3, doel_pad: '/instellingen/boeken' },
  doel_pad: '/instellingen/boeken',
}

function lijst(): BevindingenLijstDto {
  return {
    rijen: [LET_OP_AUTOMATISERING],
    totaal: 1,
    pagina: 1,
    per_pagina: 25,
    administraties_in_selectie: 0,
    tellers: { afwijkingen: 0, let_op: 1, fouten: 0, geaccepteerd: 0, uitgesloten: 0, gezien: 0, administraties: 0 },
    facetten: { soort: { aandacht: 1, let_op: 1, alle: 1 }, administraties: [] },
    laatste_run: {
      run_id: 'cccccccc-0000-0000-0000-000000000003',
      status: 'klaar',
      bron: 'scheduler',
      aangevraagd_op: '2026-09-07T04:00:00Z',
      gestart_op: null,
      afgerond_op: '2026-09-07T04:31:00Z',
      exit_code: 0,
      samenvatting: {
        documenten: { status: 'ok', exit_code: 0, gecontroleerd: 12, afwijkingen: 0, geaccepteerd: 0, uitgesloten: 0, let_op: 0, fouten: 0, foutmelding: null },
        automatiseringen: AUTOMATISERINGEN,
      },
      fout_reden: null,
      mail_status: 'verzonden',
      mail_detail: null,
    },
  }
}

describe('ReconciliatieScreen — automatiseringen', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont het blok uit laatste_run.samenvatting en de LET-OP-rij met "Naar de instelling →" (geen Gezien zonder administratie)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken('boekhouding') }))
        if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [] }))
        if (url.startsWith('/reconciliatie/bevindingen?')) return Promise.resolve(jsonResponse(lijst()))
        if (url === '/reconciliatie/run/laatste') return Promise.resolve(jsonResponse(null))
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    render(
      <MemoryRouter initialEntries={['/reconciliatie']}>
        <AuthProvider>
          <ReconciliatieScreen pollMs={5} />
        </AuthProvider>
      </MemoryRouter>,
    )
    const tabel = await screen.findByTestId('reconciliatie-tabel')
    expect(screen.getByTestId('automatiseringen-blok')).toHaveTextContent('Autoboeken inkoop')
    const rij = within(tabel).getByTestId('reconciliatie-rij')
    expect(within(rij).getByText('Automatisering')).toBeInTheDocument()
    expect(within(rij).getByTestId('bevinding-titel')).toHaveTextContent('Automatisering wacht op voorwaarde — Duplicaat-afvoer')
    expect(within(rij).getByTestId('bevinding-doe')).toHaveTextContent('Instellingen › Boeken')
    const link = within(rij).getByRole('link', { name: /Naar de instelling van/ })
    expect(link).toHaveAttribute('href', '/instellingen/boeken')
    expect(link).toHaveTextContent('Naar de instelling →')
    // platformbreed (geen administratie): geen "Gezien"-knop — de handeling is de instelling herstellen
    expect(within(rij).queryByRole('button', { name: /^Gezien:/ })).toBeNull()
  })
})
