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
    '/accordering/vragen': () => jsonResponse({ items: [] }),
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

  it('doorbelasting = één regel "Wordt doorbelast aan X en Y", tikbaar uitklappen toont de alleen-lezen verdeling (26-08 B4)', async () => {
    const metDoorbelasting: WachtrijItemDto = {
      ...ITEM,
      doorbelasting: [
        { doelentiteit_naam: 'Oirschot Recreatie B.V.', percentage: '60.00', netto_totaal: '420.00', provisie_bedrag: '21.00' },
        { doelentiteit_naam: 'Veldhoven Recreatie B.V.', percentage: '40.00', netto_totaal: '280.00', provisie_bedrag: '14.00' },
      ],
    }
    stubFetch(basisRoutes([metDoorbelasting]))
    renderFlow()
    // kaartchip in de wachtrij
    expect(await screen.findByText('Wordt doorbelast')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Essent Zakelijk'))
    const blok = await screen.findByLabelText('Doorbelasting')
    expect(blok).toHaveTextContent('Wordt doorbelast aan Oirschot Recreatie B.V. en Veldhoven Recreatie B.V.')
    // ingeklapt: geen verdeling, geen uitlegzin
    expect(blok).not.toHaveTextContent('60%')
    expect(blok).not.toHaveTextContent('Wijs de factuur af')
    await userEvent.click(screen.getByRole('button', { name: /Wordt doorbelast aan/ }))
    expect(blok).toHaveTextContent('60% · € 420,00 excl.')
    expect(blok).toHaveTextContent('40% · € 280,00 excl.')
    expect(blok).toHaveTextContent('Provisie kantoor · Oirschot Recreatie B.V.€ 21,00')
    expect(blok).toHaveTextContent('Verdeling is alleen-lezen')
    // geen eigen besluitknoppen in het blok: fout = de bestaande afwijsknop met reden
    expect(blok.querySelectorAll('button')).toHaveLength(1)
    expect(screen.getByRole('button', { name: /Afwijzen/ })).toBeInTheDocument()
  })

  it('PDF-weergave toont een expliciete laadstate en bij falen een retry-knop — nooit stil wit (26-08 B2)', async () => {
    const routes = basisRoutes([ITEM])
    let bestandAanroepen = 0
    let serverOk = false
    routes['/administraties/a1/documenten/d1/bestand'] = () => {
      bestandAanroepen += 1
      return serverOk
        ? new Response(new Blob(['%PDF-1.4'], { type: 'application/pdf' }), { status: 200 })
        : new Response(null, { status: 500 })
    }
    stubFetch(routes)
    renderFlow()
    // wachtrij: de eerste factuur wordt verborgen voorgeladen — de laadstate is er dan al
    // (nooit stil wit), maar rendert NIET (display:none → breedte 0 was de oorzaak van het witte vlak)
    expect(await screen.findByText('Essent Zakelijk')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Essent Zakelijk'))
    expect(await screen.findByText('Het factuurbeeld kon niet geladen worden.')).toBeInTheDocument()
    expect(bestandAanroepen).toBe(1)
    // retry: cache vergeten → verse fetch; de oude fout verdwijnt (pdf.js zelf rendert niet in jsdom)
    serverOk = true
    await userEvent.click(screen.getByRole('button', { name: 'Opnieuw laden' }))
    await waitFor(() => expect(bestandAanroepen).toBe(2))
    await waitFor(() => expect(screen.queryByText('Het factuurbeeld kon niet geladen worden.')).not.toBeInTheDocument())
  })

  it('vraag van het kantoor op het document: chip op de kaart, thread op het document, antwoorden wisselt de beurt (26-08 B5)', async () => {
    const vraag = {
      id: 'v1',
      administratie_id: 'a1',
      administratie_naam: 'BLOW B.V.',
      document_id: 'd1',
      document_status: 'ter_accordering',
      leverancier_naam: 'Essent Zakelijk',
      totaalbedrag: '847.00',
      vraag_tekst: 'Is het meerwerk door u opgedragen?',
      gesteld_op: '2026-08-26T16:42:00Z',
      ik_ben_aan_de_beurt: true,
      berichten: [],
    }
    const routes = basisRoutes([{ ...ITEM, vraag }])
    routes['/accordering/vragen'] = () => jsonResponse({ items: [vraag] })
    const antwoorden: unknown[] = []
    routes['/administraties/a1/accordering/vragen/v1/berichten'] = (init) => {
      antwoorden.push(JSON.parse(String(init?.body)))
      return jsonResponse(
        {
          ...vraag,
          ik_ben_aan_de_beurt: false,
          berichten: [{ id: 'b1', auteur_id: 'acc', van_mij: true, tekst: 'Ja, door mij.', geplaatst_op: '2026-08-26T17:00:00Z' }],
        },
        201,
      )
    }
    stubFetch(routes)
    renderFlow()
    expect(await screen.findByText('💬 Vraag van kantoor')).toBeInTheDocument()
    // de vraag hoort bij een te accorderen document → NIET nog eens onder "Vragen aan u"
    expect(screen.queryByText(/Vragen aan u/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByText('Essent Zakelijk'))
    const thread = await screen.findByLabelText('Vraag van het kantoor')
    expect(thread).toHaveTextContent('Is het meerwerk door u opgedragen?')
    expect(thread).toHaveTextContent('U bent aan de beurt')
    expect(screen.getByText(/blokkeert alleen het/)).toBeInTheDocument()
    // akkoord blijft gewoon mogelijk
    expect(screen.getByRole('button', { name: 'Akkoord ✓' })).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Uw antwoord'), 'Ja, door mij.')
    await userEvent.click(screen.getByRole('button', { name: 'Verstuur' }))
    await waitFor(() => expect(antwoorden).toEqual([{ tekst: 'Ja, door mij.' }]))
    expect(thread).toHaveTextContent('Wacht op kantoor')
    expect(thread).toHaveTextContent('Ja, door mij.')
    expect(screen.queryByLabelText('Uw antwoord')).not.toBeInTheDocument()
    // afgehandeld = nooit een knop voor de accordeur
    expect(screen.queryByRole('button', { name: /fgehandeld/ })).not.toBeInTheDocument()
  })

  it('"Vragen aan u": losse vraag over een geboekte factuur, thread-scherm, ?vraag=-deep-link (26-08 B5)', async () => {
    const vraag = {
      id: 'v2',
      administratie_id: 'a1',
      administratie_naam: 'Kempen Facilities B.V.',
      document_id: 'd9',
      document_status: 'geboekt',
      leverancier_naam: 'Van Diemen Transport',
      totaalbedrag: '780.45',
      vraag_tekst: 'Deze factuur noemt werkadres Molenhof — klopt dat?',
      gesteld_op: '2026-08-25T11:20:00Z',
      ik_ben_aan_de_beurt: true,
      berichten: [
        { id: 'b1', auteur_id: 'acc', van_mij: true, tekst: 'Even nagevraagd.', geplaatst_op: '2026-08-25T13:05:00Z' },
        { id: 'b2', auteur_id: 'k', van_mij: false, tekst: 'Dank!', geplaatst_op: '2026-08-25T13:11:00Z' },
      ],
    }
    const routes = basisRoutes([ITEM])
    routes['/accordering/vragen'] = () => jsonResponse({ items: [vraag] })
    stubFetch(routes)
    renderFlow()
    expect(await screen.findByText('Vragen aan u · 1')).toBeInTheDocument()
    expect(screen.getByText('Te accorderen · 1')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Van Diemen Transport'))
    const thread = await screen.findByLabelText('Vraag van het kantoor')
    expect(thread).toHaveTextContent('Even nagevraagd.')
    expect(thread).toHaveTextContent('Dank!')
    expect(thread).toHaveTextContent('Alleen de vraagsteller op kantoor kan de vraag afgehandeld verklaren')
    expect(screen.getByRole('button', { name: 'bekijk factuur' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Akkoord ✓' })).not.toBeInTheDocument()
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
