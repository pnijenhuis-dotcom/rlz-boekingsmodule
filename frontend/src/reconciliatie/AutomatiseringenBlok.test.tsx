import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { AutomatiseringenBlok, AutomatiseringenInstellingenBlok, detailTekst, samenvattingTekst } from './AutomatiseringenBlok'
import { ReconciliatieScreen } from './ReconciliatieScreen'
import type { AutomatiseringenDto, AutomatiseringTellerDto, BevindingDto, BevindingenLijstDto, ReconciliatieRunDto } from './reconciliatieApi'

// Blok "Automatiseringen" (herstelrun 07-09 blok C, "geen stille no-op"; VERHUISD 08-09 blok 5 — feedback Peter
// "wat moet ik hiermee"): staat op Instellingen › Boeken platformbreed, niet meer op het werkscherm Inzicht ›
// Reconciliatie. Standaard ingeklapt tot één regel ("N aan · M let-op"); automatisch open bij een LET-OP mét de
// handeling "Naar de instelling →" op de rij; uit-regels worden niet getoond; onbekende sleutels crashen nooit.
// De tellers komen mee in laatste_run.samenvatting (GET /reconciliatie/run/laatste — geen nieuw endpoint).

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
  it('één-regel-samenvatting zonder uit-regels; open bij let-op; per let-op-rij "Naar de instelling →"', () => {
    render(
      <MemoryRouter>
        <AutomatiseringenBlok data={AUTOMATISERINGEN} />
      </MemoryRouter>,
    )
    const blok = screen.getByTestId('automatiseringen-blok')
    expect(blok).toHaveTextContent('Automatiseringen')
    // 4 tellers, 1 uit → "3 aan"; bank (harde voorwaarde) + terugkerend (stil) → "2 let-op"
    expect(screen.getByTestId('automatiseringen-samenvatting')).toHaveTextContent('3 aan · 2 let-op')
    expect(screen.getByTestId('automatiseringen-let-op')).toHaveTextContent('2 let-op')
    expect(blok).toHaveAttribute('open') // let-op → automatisch uitgeklapt

    const inkoop = screen.getByTestId('automatisering-autoboeken_inkoop')
    const cellen = within(inkoop).getAllByRole('cell')
    expect(cellen[1]).toHaveTextContent('aan')
    expect(cellen[2]).toHaveTextContent('5')
    expect(cellen[3]).toHaveTextContent('3')
    // overgeslagen mét reden; de vaste categorie "geen eigenaar" blijft zichtbaar als 0 (kernprincipe 7)
    expect(cellen[4]).toHaveTextContent('2 (geen eigenaar/toewijzing: 0, harde checks blokkeren: 1, urenmatch niet groen: 1)')
    expect(cellen[5]).toHaveTextContent('14 / 20')
    // geen let-op → geen actie op de rij
    expect(within(inkoop).queryByTestId('automatisering-actie')).toBeNull()

    // uitgeschakeld = NIET getoond (besluit Peter 08-09)
    expect(screen.queryByTestId('automatisering-autoboeken_omzet')).toBeNull()

    // harde voorwaarde → chip + handeling naar de instelling (spiegel DOEL_PAD: volumerem → Autoboeken)
    const bank = screen.getByTestId('automatisering-bank_autoboeken')
    expect(within(bank).getByTestId('chip-harde-voorwaarde')).toHaveTextContent('wacht op voorwaarde')
    expect(bank).toHaveTextContent('deels aan (4 van 12 administraties)')
    expect(bank).toHaveTextContent('1 (volumerem bereikt: 1)')
    const bankLink = within(bank).getByRole('link', { name: 'Naar de instelling van Bank-autoboeken/afletteren' })
    expect(bankLink).toHaveAttribute('href', '/instellingen/autoboeken')
    expect(bankLink).toHaveTextContent('Naar de instelling →')

    // zeven dagen stil → chip "stil" + handeling (geen autoboek-pad → de bevinding op Inzicht › Reconciliatie)
    const terug = screen.getByTestId('automatisering-terugkerend')
    expect(terug).toHaveTextContent('stil')
    expect(within(terug).getByRole('link', { name: /Naar de instelling van/ })).toHaveAttribute('href', '/reconciliatie?soort=let_op')
  })

  it('zonder let-op is het blok ingeklapt (één regel) maar wél aanwezig', () => {
    const rustig = { ...AUTOMATISERINGEN, tellers: [AUTOMATISERINGEN.tellers[0], AUTOMATISERINGEN.tellers[1]] }
    render(
      <MemoryRouter>
        <AutomatiseringenBlok data={rustig} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('automatiseringen-blok')).not.toHaveAttribute('open')
    expect(screen.getByTestId('automatiseringen-samenvatting')).toHaveTextContent('1 aan · 0 let-op')
    expect(screen.queryByTestId('automatiseringen-let-op')).toBeNull()
  })

  it('zonder tellers (oude run of oude server) rendert het blok niets; alles uit = één hint-regel', () => {
    const { container } = render(<AutomatiseringenBlok data={null} />)
    expect(container).toBeEmptyDOMElement()
    render(<AutomatiseringenBlok data={{ ...AUTOMATISERINGEN, tellers: [] }} />)
    expect(screen.queryByTestId('automatiseringen-blok')).toBeNull()
    render(
      <MemoryRouter>
        <AutomatiseringenBlok data={{ ...AUTOMATISERINGEN, tellers: [AUTOMATISERINGEN.tellers[1]] }} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('automatiseringen-leeg')).toHaveTextContent('Alle automatiseringen staan uit.')
    expect(screen.getByTestId('automatiseringen-samenvatting')).toHaveTextContent('0 aan · 0 let-op')
  })

  it('een uit-teller MÉT let-op (noodrem UIT + gesignaleerde duplicaten, 07-09-uitzondering) wordt wél getoond en telt als let-op', () => {
    const noodremUit = teller('duplicaat_afvoer', 'Duplicaat-afvoer', {
      stand: 'uit',
      stand_detail: 'platformbrede noodrem UIT',
      dag: { verwacht: 3, gedaan: 0, overgeslagen: { volumerem: 0, noodrem: 3 } },
      week: { verwacht: 3, gedaan: 0, overgeslagen: { volumerem: 0, noodrem: 3 } },
      harde_voorwaarden: [{ categorie: 'noodrem', aantal: 3, administratie_id: 'aaaaaaaa-0000-0000-0000-000000000001', voorbeeld: 'zelfde_referentie' }],
    })
    render(
      <MemoryRouter>
        <AutomatiseringenBlok data={{ ...AUTOMATISERINGEN, tellers: [AUTOMATISERINGEN.tellers[0], noodremUit] }} />
      </MemoryRouter>,
    )
    // 1 aan (inkoop), maar de let-op op de uit-teller telt mee én de rij staat er, mét stand-detail en handeling naar Boeken
    expect(screen.getByTestId('automatiseringen-samenvatting')).toHaveTextContent('1 aan · 1 let-op')
    expect(screen.getByTestId('automatiseringen-blok')).toHaveAttribute('open')
    const rij = screen.getByTestId('automatisering-duplicaat_afvoer')
    expect(rij).toHaveTextContent('uit (platformbrede noodrem UIT)')
    expect(rij).toHaveTextContent('3 (noodrem staat uit: 3)')
    expect(within(rij).getByRole('link', { name: 'Naar de instelling van Duplicaat-afvoer' })).toHaveAttribute('href', '/instellingen/boeken')
  })

  it('is sleutel-agnostisch: onbekende automatisering, reden, stand en voorwaarde-categorie crashen nooit (blok 1 voegt bank_sync toe)', () => {
    const onbekend = teller('bank_sync', '', {
      stand: 'ergens_tussenin' as AutomatiseringTellerDto['stand'],
      dag: { verwacht: 3, gedaan: 1, overgeslagen: { nieuwe_reden_x: 2 } },
      week: { verwacht: 3, gedaan: 1, overgeslagen: { nieuwe_reden_x: 2 } },
      harde_voorwaarden: [{ categorie: 'nieuwe_voorwaarde', aantal: 2, administratie_id: null, voorbeeld: null }],
    })
    render(
      <MemoryRouter>
        <AutomatiseringenBlok data={{ ...AUTOMATISERINGEN, tellers: [onbekend] }} />
      </MemoryRouter>,
    )
    const rij = screen.getByTestId('automatisering-bank_sync')
    expect(rij).toHaveTextContent('bank_sync') // leeg label → sleutel
    expect(rij).toHaveTextContent('ergens tussenin') // onbekende stand → sleutel als label
    expect(rij).toHaveTextContent('2 (nieuwe reden x: 2)') // onbekende reden → sleutel als label
    // onbekende voorwaarde-categorie → de bevinding (mét server-deeplink) op Inzicht › Reconciliatie
    expect(within(rij).getByRole('link', { name: /Naar de instelling van/ })).toHaveAttribute('href', '/reconciliatie?soort=let_op')
    expect(samenvattingTekst([onbekend])).toBe('1 aan · 1 let-op')
  })
})

// ---- Instellingen › Boeken: het blok laadt zelf de laatste run ----------------------------------------

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function fakeAccessToken(rol: string): string {
  const payload = btoa(JSON.stringify({ sub: 'gebruiker-id', rol })).replace(/\+/g, '-').replace(/\//g, '_')
  return `kop.${payload}.handtekening`
}

function run(extra: Partial<ReconciliatieRunDto> = {}): ReconciliatieRunDto {
  return {
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
    ...extra,
  }
}

function renderInstellingenBlok(laatste: ReconciliatieRunDto | null | Response) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken('beheerder') }))
      if (url === '/reconciliatie/run/laatste') return Promise.resolve(laatste instanceof Response ? laatste : jsonResponse(laatste))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return render(
    <MemoryRouter initialEntries={['/instellingen/boeken']}>
      <AuthProvider>
        <AutomatiseringenInstellingenBlok />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('AutomatiseringenBlok — teller autoboek_leren mét detail (blok A bundel 10-09, additief)', () => {
  it('toont lerend/actief/uitgezonderd/vandaag geactiveerd uit `detail`; onbekende sleutels en niet-getallen worden overgeslagen; null = niets', () => {
    const data: AutomatiseringenDto = {
      ...AUTOMATISERINGEN,
      tellers: [
        teller('autoboek_leren', 'Autoboeken per administratie (leren en boeken)', {
          stand: 'deels',
          stand_detail: 'aan 2 van 12 administraties',
          dag: { verwacht: 3, gedaan: 3, overgeslagen: {} },
          detail: { lerend: 4, actief: 2, uitgezonderd: 1, geactiveerd_24u: 1, per_administratie: [{ naam: 'x' }], onbekend: 'tekst' },
        }),
        teller('autoboeken_inkoop', 'Autoboeken inkoop', { detail: null }),
      ],
    }
    render(
      <MemoryRouter>
        <AutomatiseringenBlok data={data} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('automatisering-detail-autoboek_leren')).toHaveTextContent('lerend 4 · actief 2 · uitgezonderd 1 · vandaag geactiveerd 1')
    expect(screen.queryByTestId('automatisering-detail-autoboeken_inkoop')).not.toBeInTheDocument()
    expect(detailTekst(null)).toBeNull()
    expect(detailTekst({ onbekend: 3 })).toBeNull()
  })
})

describe('AutomatiseringenInstellingenBlok (Instellingen › Boeken platformbreed)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('laadt de laatste run via GET /reconciliatie/run/laatste en toont het blok', async () => {
    renderInstellingenBlok(run())
    expect(await screen.findByTestId('automatiseringen-blok')).toHaveTextContent('Autoboeken inkoop')
    expect(screen.getByTestId('automatiseringen-samenvatting')).toHaveTextContent('3 aan · 2 let-op')
    expect(vi.mocked(fetch).mock.calls.some(([url]) => url === '/reconciliatie/run/laatste')).toBe(true)
  })

  it('nog geen run → hint mét link naar Inzicht › Reconciliatie; run bezig → "tellers volgen"', async () => {
    const r1 = renderInstellingenBlok(null)
    expect(await screen.findByTestId('automatiseringen-geen-run')).toHaveTextContent('nog geen afgeronde reconciliatie-run')
    expect(screen.getByRole('link', { name: 'Inzicht › Reconciliatie' })).toHaveAttribute('href', '/reconciliatie')
    r1.unmount()
    vi.unstubAllGlobals()
    renderInstellingenBlok(run({ status: 'bezig', samenvatting: null, afgerond_op: null }))
    expect(await screen.findByTestId('automatiseringen-geen-run')).toHaveTextContent('reconciliatie bezig — tellers volgen')
  })

  it('een fout bij het laden blokkeert de pagina niet (één hint-regel)', async () => {
    renderInstellingenBlok(new Response(JSON.stringify({ detail: 'kapot' }), { status: 500, headers: { 'Content-Type': 'application/json' } }))
    expect(await screen.findByTestId('automatiseringen-fout')).toHaveTextContent('Automatiseringen: stand niet geladen')
  })
})

// ---- Inzicht › Reconciliatie: het tellersblok staat er NIET meer; de LET-OP-bevinding mét handeling blijft ----

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
    laatste_run: run(),
  }
}

describe('ReconciliatieScreen — automatiseringen (blok 5, 08-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont het tellersblok NIET meer, wél de LET-OP-rij met "Naar de instelling →" (geen Gezien zonder administratie)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/auth/token/vernieuwen') return Promise.resolve(jsonResponse({ access_token: fakeAccessToken('boekhouding') }))
        if (url === '/auth/administraties') return Promise.resolve(jsonResponse({ administraties: [] }))
        if (url.startsWith('/reconciliatie/bevindingen?')) return Promise.resolve(jsonResponse(lijst()))
        if (url === '/reconciliatie/run/laatste') return Promise.resolve(jsonResponse(run()))
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
    // De run mét tellers is geladen (standregel) — maar het tellersblok staat op Instellingen › Boeken, niet hier.
    expect(await screen.findByTestId('reconciliatie-stand')).toHaveTextContent('exit 0')
    expect(screen.queryByTestId('automatiseringen-blok')).toBeNull()
    expect(screen.queryByText('Autoboeken inkoop')).toBeNull()
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
