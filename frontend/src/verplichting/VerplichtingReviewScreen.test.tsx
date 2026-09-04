import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VerplichtingReviewScreen } from './VerplichtingReviewScreen'
import type { VerplichtingVoorstelDto } from './verplichtingApi'

// Reviewscherm verplichting (blok B 04-09, mockup offerte-matching blok 1): veldvoorstel-patroon
// mét herkomst-chips, één primaire knop "Ter accordering" achter groene checks, en ná het akkoord
// het goedgekeurd-blok mét verbruiksstand + "Laten vervallen…" (reden verplicht, ⑥).

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOC = 'bbbbbbbb-0000-0000-0000-000000000002'
const VENDOR = 'cccccccc-0000-0000-0000-000000000003'
const PROJECT = 'dddddddd-0000-0000-0000-000000000004'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function detail(overrides: Record<string, unknown> = {}) {
  return {
    id: DOC,
    administratie_id: ADMIN,
    bestandsnaam: 'confide-offerte-26140.pdf',
    status: 'te_controleren',
    bron: 'email',
    soort: 'verplichting',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-09-04T09:00:00Z',
    laatst_gewijzigd_op: '2026-09-04T09:00:00Z',
    veldvoorstel: null,
    afwijzing: null,
    tijdlijn: [],
    ...overrides,
  }
}

function voorstel(overrides: Partial<VerplichtingVoorstelDto> = {}): VerplichtingVoorstelDto {
  return {
    document_id: DOC,
    status: 'te_controleren',
    soort_label: 'offerte',
    vendor_id: VENDOR,
    vendor_naam: 'Confide Bouw B.V.',
    project_id: PROJECT,
    project_naam: '26140 Koningstraat',
    offertenummer: '26140-OFF-01',
    datum: '2026-09-01',
    totaalbedrag_excl: '48500.00',
    geldig_tot: '2026-12-31',
    omschrijving: 'Verbouwing Koningstraat',
    opgeslagen: false,
    herkomst: {
      soort_label: 'ai',
      leverancier: 'ai',
      offertenummer: 'ai',
      totaalbedrag_excl: 'ai',
      geldig_tot: 'ai',
      project: null,
      omschrijving: 'ai',
    },
    zekerheid: { soort_label: 0.97, leverancier: 0.95, offertenummer: 0.42, totaalbedrag_excl: 0.99, geldig_tot: 0.9 },
    zekerheid_drempel: 0.8,
    vendor_suggestie: null,
    project_suggestie: null,
    goedgekeurd: null,
    verbruik: null,
    vervallen: null,
    gekoppelde_facturen: [],
    checks: [
      { naam: 'Verplichte velden', status: 'ok', melding: 'Leverancier, soort en bedrag zijn gevuld.' },
      { naam: 'Geldigheid', status: 'ok', melding: 'Geldig t/m 31-12-2026.' },
      { naam: 'Duplicaat offerte', status: 'ok', melding: 'Geen andere lopende offerte met dit nummer.' },
    ],
    ai_overgeslagen_reden: null,
    ...overrides,
  }
}

interface Opties {
  detailBody?: Record<string, unknown>
  voorstelBody?: VerplichtingVoorstelDto
  putAanroepen?: { body: unknown }[]
  aanbiedAanroepen?: string[]
  aanbiedAntwoord?: () => Response
  vervalAanroepen?: { body: unknown }[]
  checksBody?: () => Response
}

function installFetch(opties: Opties = {}) {
  const huidigVoorstel = { waarde: opties.voorstelBody ?? voorstel() }
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const methode = init?.method ?? 'GET'
      if (url.includes('/verplichtingen/documenten/') && url.endsWith('/voorstel')) {
        if (methode === 'PUT') {
          const body = init?.body ? JSON.parse(String(init.body)) : null
          opties.putAanroepen?.push({ body })
          huidigVoorstel.waarde = { ...huidigVoorstel.waarde, ...body, opgeslagen: true }
          return Promise.resolve(json(huidigVoorstel.waarde))
        }
        return Promise.resolve(json(huidigVoorstel.waarde))
      }
      if (url.endsWith('/checks') && methode === 'POST') {
        return Promise.resolve(
          opties.checksBody
            ? opties.checksBody()
            : json({ checks: huidigVoorstel.waarde.checks, geblokkeerd: false }),
        )
      }
      if (url.endsWith('/vervallen') && methode === 'POST') {
        const body = init?.body ? JSON.parse(String(init.body)) : null
        opties.vervalAanroepen?.push({ body })
        return Promise.resolve(
          json({
            ...huidigVoorstel.waarde,
            vervallen: { op: '2026-09-04T12:00:00Z', reden: (body as { reden: string }).reden, door_naam: 'P. Nijenhuis' },
          }),
        )
      }
      if (url.endsWith('/aanbieden') && methode === 'POST') {
        opties.aanbiedAanroepen?.push(url)
        return Promise.resolve(opties.aanbiedAntwoord ? opties.aanbiedAntwoord() : json({ alles_akkoord: false }))
      }
      if (url.endsWith('/bestand')) {
        return Promise.resolve(
          new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), {
            status: 200,
            headers: { 'Content-Type': 'application/pdf' },
          }),
        )
      }
      if (url.endsWith('/crediteuren')) {
        return Promise.resolve(json({ crediteuren: [{ id: VENDOR, naam: 'Confide Bouw B.V.' }] }))
      }
      if (url.endsWith('/projecten')) {
        return Promise.resolve(json({ projecten: [{ id: PROJECT, naam: '26140 Koningstraat' }] }))
      }
      if (url.endsWith('/project-instelling')) return Promise.resolve(json({ verplicht: false }))
      if (url.includes('/accordering/')) return Promise.resolve(json({ detail: 'geen ronde' }, 404))
      if (url.includes('/accordering')) return Promise.resolve(json({ laatst_herinnerd: {} }))
      if (url.endsWith(`/documenten/${DOC}`)) return Promise.resolve(json(opties.detailBody ?? detail()))
      return Promise.resolve(json({ detail: `onverwacht pad ${url}` }, 500))
    }),
  )
}

function toonScherm() {
  return render(
    <MemoryRouter initialEntries={[`/verplichting/${ADMIN}/${DOC}`]}>
      <Routes>
        <Route path="/verplichting/:administratieId/:documentId" element={<VerplichtingReviewScreen />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('VerplichtingReviewScreen — controle kantoor', () => {
  it('laadt het voorstel met herkomst-chips per veld (lage AI-zekerheid = oranje)', async () => {
    installFetch()
    toonScherm()

    expect(await screen.findByDisplayValue('26140-OFF-01')).toBeInTheDocument()
    expect(screen.getByDisplayValue('48500.00')).toBeInTheDocument()
    // Zekerheid boven de drempel (0,99) = groene chip; het offertenummer (0,42) = oranje.
    const aiChips = screen.getAllByTitle(/Gelezen door de AI-extractie/i)
    expect(aiChips.length).toBeGreaterThan(0)
    const oranje = aiChips.filter((c) => c.textContent?.includes('42%'))
    expect(oranje).toHaveLength(1)
    expect(oranje[0].className).toContain('afwijking')
    const groen = aiChips.filter((c) => c.textContent?.includes('99%'))
    expect(groen).toHaveLength(1)
    expect(groen[0].className).toContain('ok')
    // Een verplichting wordt niet geboekt — dat staat er expliciet.
    expect(screen.getByText(/Verplichting — geen boeking/i)).toBeInTheDocument()
    expect(screen.getByTestId('verplichting-pdf')).toBeInTheDocument()
  })

  it('slaat een wijziging op via PUT en herdraait daarna de checks', async () => {
    const putAanroepen: { body: unknown }[] = []
    installFetch({ putAanroepen })
    toonScherm()

    const nummer = await screen.findByDisplayValue('26140-OFF-01')
    await userEvent.clear(nummer)
    await userEvent.type(nummer, '26140-OFF-02')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan' }))

    await waitFor(() => expect(putAanroepen).toHaveLength(1))
    expect(putAanroepen[0].body).toMatchObject({ offertenummer: '26140-OFF-02', totaalbedrag_excl: '48500.00' })
  })

  it('biedt ter accordering aan zodra de checks groen zijn en bewaart onopgeslagen werk eerst', async () => {
    const aanbiedAanroepen: string[] = []
    const putAanroepen: { body: unknown }[] = []
    installFetch({ aanbiedAanroepen, putAanroepen })
    toonScherm()

    const omschrijving = await screen.findByDisplayValue('Verbouwing Koningstraat')
    await userEvent.type(omschrijving, ' fase 2')
    await userEvent.click(screen.getByRole('button', { name: /Ter accordering/ }))

    await waitFor(() => expect(aanbiedAanroepen).toHaveLength(1))
    // Onopgeslagen wijziging is eerst bewaard — nooit een akkoord vragen op een oud voorstel.
    expect(putAanroepen).toHaveLength(1)
    expect(aanbiedAanroepen[0]).toContain(`/accordering/documenten/${DOC}/aanbieden`)
  })

  it('blokkeert "Ter accordering" zolang een harde check rood staat', async () => {
    installFetch({
      voorstelBody: voorstel({
        checks: [{ naam: 'Verplichte velden', status: 'blokkerend', melding: 'Bedrag ontbreekt.' }],
      }),
    })
    toonScherm()

    const knop = await screen.findByRole('button', { name: /Ter accordering/ })
    expect(knop).toBeDisabled()
    expect(screen.getByText('Bedrag ontbreekt.')).toBeInTheDocument()
  })

  it('toont ná het akkoord het goedgekeurd-blok met verbruiksstand en gekoppelde facturen', async () => {
    installFetch({
      detailBody: detail({ status: 'geaccordeerd' }),
      voorstelBody: voorstel({
        status: 'geaccordeerd',
        opgeslagen: true,
        goedgekeurd: { bedrag_excl: '48500.00', op: '2026-09-04T10:00:00Z', door_naam: 'J. de Groot' },
        verbruik: { verbruikt_excl: '27150.00', totaal_excl: '48500.00', percentage: 56, over_excl: null },
        gekoppelde_facturen: [
          {
            document_id: 'eeee0000-0000-0000-0000-000000000005',
            referentie: 'F-2026-118',
            factuurdatum: '2026-09-02',
            bedrag_excl: '12400.00',
            status: 'geboekt',
            verrekend: true,
          },
        ],
      }),
    })
    toonScherm()

    const blok = await screen.findByTestId('goedgekeurd-blok')
    expect(within(blok).getByText(/J. de Groot/)).toBeInTheDocument()
    expect(within(blok).getByTestId('verbruiks-balk')).toHaveTextContent('56%')
    expect(within(blok).getByTestId('gekoppelde-facturen')).toHaveTextContent('F-2026-118')
    expect(within(blok).getByText('verrekend')).toBeInTheDocument()
    // Geaccordeerd = eindstand: geen aanbied-knop meer.
    expect(screen.queryByRole('button', { name: /Ter accordering/ })).not.toBeInTheDocument()
  })

  it('laat een geaccordeerde verplichting vervallen met een VERPLICHTE reden', async () => {
    const vervalAanroepen: { body: unknown }[] = []
    installFetch({
      detailBody: detail({ status: 'geaccordeerd' }),
      voorstelBody: voorstel({
        status: 'geaccordeerd',
        goedgekeurd: { bedrag_excl: '48500.00', op: '2026-09-04T10:00:00Z', door_naam: 'J. de Groot' },
        verbruik: { verbruikt_excl: '0.00', totaal_excl: '48500.00', percentage: 0, over_excl: null },
      }),
      vervalAanroepen,
    })
    toonScherm()

    await userEvent.click(await screen.findByRole('button', { name: 'Meer acties' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Laten vervallen…' }))

    const dialoog = await screen.findByTestId('verval-dialoog')
    // Zonder reden kan het niet weg.
    expect(within(dialoog).getByRole('button', { name: 'Laten vervallen' })).toBeDisabled()
    await userEvent.type(within(dialoog).getByLabelText('Reden'), 'opdracht niet doorgegaan')
    await userEvent.click(within(dialoog).getByRole('button', { name: 'Laten vervallen' }))

    await waitFor(() => expect(vervalAanroepen).toHaveLength(1))
    expect(vervalAanroepen[0].body).toEqual({ reden: 'opdracht niet doorgegaan' })
    expect(await screen.findByTestId('vervallen-regel')).toHaveTextContent('opdracht niet doorgegaan')
  })
})
