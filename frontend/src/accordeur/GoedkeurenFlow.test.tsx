// Schermtests accordeur-PWA (mockup accordeur.html): wachtrij → review → akkoord/afwijzen,
// verplichte-reden-poort, staande-goedkeuring-voorstel en de voorwaarden-gate (blok 3).
// Sinds de snelheidslaag (2026-08-17) óók: het optimistische pad (per direct door naar de
// volgende factuur), de zichtbare fout-terugkeer en het dubbeltik-vangnet.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../auth/AuthContext'
import { GoedkeurenFlow, OVERGANGS_GUARD_MS } from './GoedkeurenFlow'
import { besluitVerzender } from './besluitQueue'
import { factuurCache } from './pdfCache'
import type { WachtrijItemDto } from './accordeurApi'

const ITEM: WachtrijItemDto = {
  document_id: 'd1',
  administratie_id: 'a1',
  administratie_naam: 'BLOW B.V.',
  leverancier_naam: 'Essent Zakelijk',
  referentie: 'E-2026-07-8841',
  factuurdatum: '2026-07-01',
  totaalbedrag: '847.00',
  aangeboden_op: '2026-07-02T09:00:00Z',
  laag_volgnummer: 1,
  boeking_omschrijving: 'Gas, water en elektra · btw 21%',
  staande_regel_kandidaat: false,
}

type FetchAntwoorden = Record<string, (init?: RequestInit) => Response | Promise<Response>>

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function stubFetch(routes: FetchAntwoorden): ReturnType<typeof vi.fn> {
  const mock = vi.fn((invoer: RequestInfo | URL, init?: RequestInit) => {
    const pad = String(invoer).split('?')[0]
    const handler = routes[pad]
    if (!handler) return Promise.resolve(new Response(null, { status: 404 }))
    return Promise.resolve(handler(init))
  })
  vi.stubGlobal('fetch', mock)
  return mock
}

function basisRoutes(items: WachtrijItemDto[]): FetchAntwoorden {
  return {
    '/auth/token/vernieuwen': () => new Response(null, { status: 401 }),
    '/accordering/wachtrij': () => jsonResponse({ items }),
    '/auth/administraties': () => jsonResponse({ administraties: [{ id: 'a1', naam: 'BLOW B.V.' }] }),
    '/administraties/a1/documenten/d1/bestand': () =>
      new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 }),
  }
}

function renderFlow(uitloggen: () => Promise<void> = () => Promise.resolve()) {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <GoedkeurenFlow wisselThema={() => {}} uitloggen={uitloggen} />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('GoedkeurenFlow', () => {
  beforeEach(() => {
    // jsdom heeft geen createObjectURL; het factuurbeeld zelf test PdfWeergave niet mee.
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:test', revokeObjectURL: () => {} }))
    // Module-singletons van de snelheidslaag schoon per test (geen lekkende verzendrij/cache).
    besluitVerzender.resetVoorTests()
    factuurCache.resetVoorTests()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont de wachtrij als kaartlijst met teller en opent het review-scherm', async () => {
    stubFetch(basisRoutes([ITEM]))
    renderFlow()

    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
    expect(screen.getByText('Essent Zakelijk')).toBeInTheDocument()
    expect(screen.getByText('€ 847,00')).toBeInTheDocument()

    await userEvent.click(screen.getByText('Essent Zakelijk'))
    expect(await screen.findByText('Gas, water en elektra · btw 21%')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Akkoord ✓' })).toBeInTheDocument()
    expect(screen.getByText('1 van 1')).toBeInTheDocument()
  })

  it('akkoord verwerkt de factuur en toont daarna de lege staat', async () => {
    const routes = basisRoutes([ITEM])
    routes['/administraties/a1/accordering/documenten/d1/akkoord'] = (init) => {
      const body = JSON.parse(String(init?.body)) as { staande_regel_aanmaken: boolean }
      expect(body.staande_regel_aanmaken).toBe(false)
      return jsonResponse({
        accordering: { id: 'x', document_id: 'd1', status: 'afgerond', aangeboden_op: '', afgerond_op: null, stappen: [] },
        alles_akkoord: true,
        geboekt: true,
        boek_fout: null,
        staande_regel_id: null,
      })
    }
    stubFetch(routes)
    renderFlow()

    await userEvent.click(await screen.findByText('Essent Zakelijk'))
    await userEvent.click(screen.getByRole('button', { name: 'Akkoord ✓' }))

    expect(await screen.findByText('Alles afgehandeld')).toBeInTheDocument()
  })

  it('afwijzen eist een reden (verplicht) en stuurt die mee', async () => {
    let afgewezenMet: string | null = null
    const routes = basisRoutes([ITEM])
    routes['/administraties/a1/accordering/documenten/d1/afwijzen'] = (init) => {
      afgewezenMet = (JSON.parse(String(init?.body)) as { reden: string }).reden
      return jsonResponse({ id: 'x', document_id: 'd1', status: 'afgewezen', aangeboden_op: '', afgerond_op: null, stappen: [] })
    }
    stubFetch(routes)
    renderFlow()

    await userEvent.click(await screen.findByText('Essent Zakelijk'))
    await userEvent.click(screen.getByRole('button', { name: 'Afwijzen' }))

    // Zonder reden: blokkeert met de verplicht-melding, géén API-call.
    await userEvent.click(screen.getByRole('button', { name: 'Afwijzen met reden' }))
    expect(
      screen.getByText('Vul eerst een reden in — zonder reden kan er niet afgewezen worden.'),
    ).toBeInTheDocument()
    expect(afgewezenMet).toBeNull()

    await userEvent.type(screen.getByLabelText('Reden van afwijzing'), 'Werk nog niet opgeleverd')
    await userEvent.click(screen.getByRole('button', { name: 'Afwijzen met reden' }))
    await waitFor(() => expect(afgewezenMet).toBe('Werk nog niet opgeleverd'))
  })

  it('stelt ná akkoord op een identieke factuur de staande goedkeuring voor (mockup-flow)', async () => {
    let staandeVlag: boolean | null = null
    const kandidaat = { ...ITEM, staande_regel_kandidaat: true }
    const routes = basisRoutes([kandidaat])
    routes['/administraties/a1/accordering/documenten/d1/akkoord'] = (init) => {
      staandeVlag = (JSON.parse(String(init?.body)) as { staande_regel_aanmaken: boolean }).staande_regel_aanmaken
      return jsonResponse({
        accordering: { id: 'x', document_id: 'd1', status: 'afgerond', aangeboden_op: '', afgerond_op: null, stappen: [] },
        alles_akkoord: true,
        geboekt: true,
        boek_fout: null,
        staande_regel_id: 'r1',
      })
    }
    stubFetch(routes)
    renderFlow()

    // Chip in de wachtrij + hint in het review-scherm.
    expect(await screen.findByText('zelfde bedrag als vorige')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Essent Zakelijk'))
    expect(await screen.findByText(/exact hetzelfde bedrag/)).toBeInTheDocument()

    // Akkoord → eerst de voorstel-sheet (nog géén API-call), dan "Ja, sta toe" → vlag mee.
    await userEvent.click(screen.getByRole('button', { name: 'Akkoord ✓' }))
    expect(staandeVlag).toBeNull()
    expect(await screen.findByText('Voortaan automatisch akkoord?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Ja, sta toe' }))
    await waitFor(() => expect(staandeVlag).toBe(true))
  })

  it('gaat na akkoord per direct door naar de volgende factuur — vóór de server antwoordt (optimistisch pad)', async () => {
    const item2: WachtrijItemDto = {
      ...ITEM,
      document_id: 'd2',
      leverancier_naam: 'Gamma Bouwstoffen',
      referentie: 'G-2026-118',
      boeking_omschrijving: 'Bouwmaterialen · btw 21%',
    }
    const routes = basisRoutes([ITEM, item2])
    routes['/administraties/a1/documenten/d2/bestand'] = () =>
      new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 })
    // De akkoord-call blijft hangen: de server antwoordt (nog) niet.
    routes['/administraties/a1/accordering/documenten/d1/akkoord'] = () => new Promise<Response>(() => {})
    stubFetch(routes)
    renderFlow()

    await userEvent.click(await screen.findByText('Essent Zakelijk'))
    expect(await screen.findByText('1 van 2')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Akkoord ✓' }))

    // Zonder server-antwoord staat de VOLGENDE factuur al open (harde ontwerpeis: klik-klik-klik).
    expect(screen.getByText('Bouwmaterialen · btw 21%')).toBeInTheDocument()
    expect(screen.getByText('2 van 2')).toBeInTheDocument()
    expect(besluitVerzender.isOnderweg('d1')).toBe(true)
  })

  it('toont op de wachtrij hoeveel besluiten nog op de achtergrond verzonden worden', async () => {
    const routes = basisRoutes([ITEM])
    routes['/administraties/a1/accordering/documenten/d1/akkoord'] = () => new Promise<Response>(() => {})
    stubFetch(routes)
    renderFlow()

    await userEvent.click(await screen.findByText('Essent Zakelijk'))
    await userEvent.click(screen.getByRole('button', { name: 'Akkoord ✓' }))

    expect(await screen.findByText('Alles afgehandeld')).toBeInTheDocument()
    expect(screen.getByText(/1 besluit wordt op de achtergrond verzonden/)).toBeInTheDocument()
  })

  it('zet een definitief mislukt akkoord ZICHTBAAR terug in de wachtrij mét melding (nooit stil verloren)', async () => {
    const routes = basisRoutes([ITEM])
    routes['/administraties/a1/accordering/documenten/d1/akkoord'] = () =>
      jsonResponse({ detail: 'Deze factuur wacht op een andere accordeur (sequentiële lagen)' }, 403)
    stubFetch(routes)
    renderFlow()

    await userEvent.click(await screen.findByText('Essent Zakelijk'))
    await userEvent.click(screen.getByRole('button', { name: 'Akkoord ✓' }))

    // De factuur komt terug in de rij, met melding + fout-chip — en telt weer mee.
    expect(
      await screen.findByText('Akkoord versturen mislukte — de factuur staat terug in je wachtrij'),
    ).toBeInTheDocument()
    expect(screen.getByText('Essent Zakelijk')).toBeInTheDocument()
    expect(screen.getByText('niet verzonden — opnieuw beoordelen')).toBeInTheDocument()
    expect(screen.getByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
    expect(besluitVerzender.isOnderweg('d1')).toBe(false)
  })

  it('afwijzen is óók optimistisch: direct door, de reden gaat op de achtergrond mee', async () => {
    let afgewezenMet: string | null = null
    const routes = basisRoutes([ITEM])
    routes['/administraties/a1/accordering/documenten/d1/afwijzen'] = (init) => {
      afgewezenMet = (JSON.parse(String(init?.body)) as { reden: string }).reden
      return new Promise<Response>(() => {})
    }
    stubFetch(routes)
    renderFlow()

    await userEvent.click(await screen.findByText('Essent Zakelijk'))
    await userEvent.click(screen.getByRole('button', { name: 'Afwijzen' }))
    await userEvent.type(screen.getByLabelText('Reden van afwijzing'), 'Werk nog niet opgeleverd')
    await userEvent.click(screen.getByRole('button', { name: 'Afwijzen met reden' }))

    // Direct de lege staat, terwijl de server nog niet geantwoord heeft.
    expect(await screen.findByText('Alles afgehandeld')).toBeInTheDocument()
    await waitFor(() => expect(afgewezenMet).toBe('Werk nog niet opgeleverd'))
  })

  it('dubbeltik-vangnet: een tweede tik direct na de overgang besluit nooit de volgende factuur blind', async () => {
    const item2: WachtrijItemDto = {
      ...ITEM,
      document_id: 'd2',
      leverancier_naam: 'Gamma Bouwstoffen',
      boeking_omschrijving: 'Bouwmaterialen · btw 21%',
    }
    const geaccordeerd: string[] = []
    const routes = basisRoutes([ITEM, item2])
    routes['/administraties/a1/documenten/d2/bestand'] = () =>
      new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 })
    const akkoordRoute = (documentId: string) => () => {
      geaccordeerd.push(documentId)
      return jsonResponse({
        accordering: { id: 'x', document_id: documentId, status: 'afgerond', aangeboden_op: '', afgerond_op: null, stappen: [] },
        alles_akkoord: true,
        geboekt: true,
        boek_fout: null,
        staande_regel_id: null,
      })
    }
    routes['/administraties/a1/accordering/documenten/d1/akkoord'] = akkoordRoute('d1')
    routes['/administraties/a1/accordering/documenten/d2/akkoord'] = akkoordRoute('d2')
    stubFetch(routes)
    renderFlow()

    await userEvent.click(await screen.findByText('Essent Zakelijk'))
    const knop = screen.getByRole('button', { name: 'Akkoord ✓' })
    await userEvent.click(knop)
    await userEvent.click(knop) // onbedoelde dubbeltik, binnen de guard-periode

    await waitFor(() => expect(geaccordeerd).toEqual(['d1']))
    expect(screen.getByText('Bouwmaterialen · btw 21%')).toBeInTheDocument() // factuur 2 staat open, onbeslist

    // Ná de guard-periode werkt de knop gewoon weer.
    await new Promise((resolve) => setTimeout(resolve, OVERGANGS_GUARD_MS + 50))
    await userEvent.click(screen.getByRole('button', { name: 'Akkoord ✓' }))
    await waitFor(() => expect(geaccordeerd).toEqual(['d1', 'd2']))
  })

  it('heeft een uitlog-knop in de header die de sessie beëindigt (kliktest 2026-08-12)', async () => {
    stubFetch(basisRoutes([ITEM]))
    const uitloggen = vi.fn(() => Promise.resolve())
    renderFlow(uitloggen)

    await screen.findByText('1 factuur wacht op je akkoord')
    await userEvent.click(screen.getByRole('button', { name: 'Uitloggen' }))
    expect(uitloggen).toHaveBeenCalledTimes(1)
  })

  it('meldt een mislukt uitloggen zichtbaar i.p.v. stil te falen', async () => {
    stubFetch(basisRoutes([ITEM]))
    renderFlow(() => Promise.reject(new Error('backend plat')))

    await screen.findByText('1 factuur wacht op je akkoord')
    await userEvent.click(screen.getByRole('button', { name: 'Uitloggen' }))
    expect(
      await screen.findByText('Uitloggen mislukte — server niet bereikbaar, probeer het opnieuw'),
    ).toBeInTheDocument()
  })

  it('toont het voorwaarden-scherm zolang de server de wachtrij weigert (blok 3, fail-closed)', async () => {
    let akkoordGegeven = false
    const routes = basisRoutes([ITEM])
    routes['/accordering/wachtrij'] = () =>
      akkoordGegeven
        ? jsonResponse({ items: [ITEM] })
        : jsonResponse({ detail: 'voorwaarden_akkoord_vereist' }, 403)
    routes['/auth/accordeur/voorwaarden'] = () =>
      jsonResponse({
        tekst_versie: '2026-08-11-concept-v1',
        tekst: '1. Gebruiksvoorwaarden. Je gebruikt deze app uitsluitend om facturen van [klantnaam] te beoordelen.',
        akkoord_gegeven: false,
        administratie_namen: ['BLOW B.V.'],
      })
    routes['/auth/accordeur/voorwaarden-akkoord'] = () => {
      akkoordGegeven = true
      return new Response(null, { status: 204 })
    }
    stubFetch(routes)
    renderFlow()

    expect(await screen.findByText('Voordat je begint')).toBeInTheDocument()
    // Placeholder is ingevuld met de administratienaam (tekst laadt asynchroon).
    expect(await screen.findByText(/facturen van BLOW B\.V\. te beoordelen/)).toBeInTheDocument()

    const knop = await screen.findByRole('button', { name: 'Akkoord en beginnen' })
    expect(knop).toBeDisabled() // zonder vinkje geen akkoord
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(knop)

    expect(await screen.findByText('1 factuur wacht op je akkoord')).toBeInTheDocument()
  })

  it('biedt op het voorwaarden-scherm een uitlog-knop — wie niet accepteert houdt geen levende sessie (fix 2026-08-12)', async () => {
    const routes = basisRoutes([ITEM])
    routes['/accordering/wachtrij'] = () => jsonResponse({ detail: 'voorwaarden_akkoord_vereist' }, 403)
    routes['/auth/accordeur/voorwaarden'] = () =>
      jsonResponse({
        tekst_versie: '2026-08-11-concept-v1',
        tekst: '1. Gebruiksvoorwaarden.',
        akkoord_gegeven: false,
        administratie_namen: ['BLOW B.V.'],
      })
    stubFetch(routes)
    const uitloggen = vi.fn(() => Promise.resolve())
    renderFlow(uitloggen)

    expect(await screen.findByText('Voordat je begint')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Uitloggen' }))
    expect(uitloggen).toHaveBeenCalledTimes(1)
  })

  it('meldt een mislukt uitloggen óók op het voorwaarden-scherm zichtbaar (zelfde toast als de header)', async () => {
    const routes = basisRoutes([ITEM])
    routes['/accordering/wachtrij'] = () => jsonResponse({ detail: 'voorwaarden_akkoord_vereist' }, 403)
    routes['/auth/accordeur/voorwaarden'] = () =>
      jsonResponse({
        tekst_versie: '2026-08-11-concept-v1',
        tekst: '1. Gebruiksvoorwaarden.',
        akkoord_gegeven: false,
        administratie_namen: ['BLOW B.V.'],
      })
    stubFetch(routes)
    renderFlow(() => Promise.reject(new Error('backend plat')))

    expect(await screen.findByText('Voordat je begint')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Uitloggen' }))
    expect(
      await screen.findByText('Uitloggen mislukte — server niet bereikbaar, probeer het opnieuw'),
    ).toBeInTheDocument()
  })
})
