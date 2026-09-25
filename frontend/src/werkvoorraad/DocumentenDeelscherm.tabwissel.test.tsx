import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { WerkvoorraadScreen } from './WerkvoorraadScreen'

/** Blok 7 feedbackrun A 25-09 (FV-18 "scherm loopt vast bij wisselen tabblad" — gemeten in het harnas, zie
 * docs/rapporten/2026-09-25-feedbackrun-A-factuurverwerking.md): regressietest op de drie onderbouwde oorzaken.
 * (1) een tabwissel is client-side en start géén server-request — ook niet via de bulk-balk die per wissel mount;
 * (2) lopende requests worden AFGEBROKEN bij een administratiewissel/unmount (de abort komt bij fetch aan) en een trage
 *     oudere lijst-request overschrijft nooit een nieuwere;
 * (3) de 3-s-poll stapelt niet (één lijst-request tegelijk) en een ongewijzigd antwoord raakt de state niet. */

const ADMIN_A = 'aaaaaaaa-0000-0000-0000-000000000001'
const ADMIN_B = 'aaaaaaaa-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function document(i: number, status: string) {
  return {
    id: `bbbbbbbb-0000-0000-0000-${String(i).padStart(12, '0')}`,
    bestandsnaam: `factuur-${i}.pdf`,
    soort: 'inkoopfactuur',
    status,
    bron: 'upload',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-09-09T10:00:00Z',
    laatst_gewijzigd_op: '2026-09-09T10:00:00Z',
    automatisch_geboekt: false,
    leverancier: `Leverancier ${i}`,
    totaalbedrag: '10.00',
    factuurdatum: '2026-09-01',
    afwijzing: null,
  }
}

interface Uitgesteld {
  url: string
  init: RequestInit | undefined
  resolve: (r: Response) => void
  afgebroken: boolean
}

/** Fetch-mock: de lijst-request is UITGESTELD (deferred) als `uitstellen` aanstaat, alle andere routes antwoorden direct.
 * `init.signal` wordt gehonoreerd: abort → AbortError én `afgebroken` op de deferred. */
function installFetchMock(opties: { documenten: unknown[]; uitstellen?: boolean; accorderingAan?: boolean }) {
  const deferred: Uitgesteld[] = []
  const aanroepen: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((invoer: string, init?: RequestInit) => {
      const url = String(invoer)
      aanroepen.push(url)
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(
          jsonResponse({ administraties: [{ id: ADMIN_A, naam: 'Klant A' }, { id: ADMIN_B, naam: 'Klant B' }] }),
        )
      }
      if (url.endsWith('/accordering/instellingen')) return Promise.resolve(jsonResponse({ ingeschakeld: opties.accorderingAan ?? true, lagen: [] }))
      if (url.endsWith('/accordering/vervallen-meldingen')) return Promise.resolve(jsonResponse([]))
      if (url.endsWith('/medewerkers')) return Promise.resolve(jsonResponse({ medewerkers: [] }))
      if (url.includes('/bank/rekeningen')) return Promise.resolve(jsonResponse({ rekeningen: [], laatste_sync_op: null, ooit_gesynchroniseerd: false, heeft_bankaanlevering: false }))
      if (url.includes('/vragen')) return Promise.resolve(jsonResponse({ vragen: [] }))
      if (url.includes('/uren/kantoor/stand')) return Promise.resolve(new Response(null, { status: 403 }))
      if (url.includes('/documenten') && !url.includes('/documenten/')) {
        const antwoord = () => jsonResponse({ documenten: opties.documenten, afgehandeld: null })
        if (!opties.uitstellen) return Promise.resolve(antwoord())
        return new Promise<Response>((resolve, reject) => {
          const d: Uitgesteld = { url, init, resolve, afgebroken: false }
          deferred.push(d)
          init?.signal?.addEventListener('abort', () => {
            d.afgebroken = true
            reject(new DOMException('The operation was aborted.', 'AbortError'))
          })
        })
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return {
    deferred,
    aanroepen,
    lijstAanroepen: () => aanroepen.filter((u) => u.includes('/documenten') && !u.includes('/documenten/')).length,
    administratiesAanroepen: () => aanroepen.filter((u) => u.endsWith('/auth/administraties')).length,
  }
}

function renderScherm(administratieId = ADMIN_A) {
  return render(
    <MemoryRouter initialEntries={[`/?administratie=${administratieId}`]}>
      <WerkvoorraadScreen />
    </MemoryRouter>,
  )
}

const statusKnop = (label: RegExp) => screen.getByRole('button', { name: label })

describe('DocumentenDeelscherm — tabwissel (blok 7 feedbackrun A 25-09, FV-18)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('20 × wisselen te_controleren ↔ klaar_om_te_boeken start géén enkele server-request (ook niet via de bulk-balk)', async () => {
    const gebruiker = userEvent.setup()
    const docs = Array.from({ length: 60 }, (_, i) => document(i, i % 2 === 0 ? 'te_controleren' : 'klaar_om_te_boeken'))
    const mock = installFetchMock({ documenten: docs, accorderingAan: true })
    renderScherm()
    await waitFor(() => expect(screen.getByText('Leverancier 0')).toBeInTheDocument())
    const voorLijst = mock.lijstAanroepen()
    const voorAdm = mock.administratiesAanroepen()
    const totaalVoor = mock.aanroepen.length

    for (let i = 0; i < 20; i++) {
      await gebruiker.click(statusKnop(i % 2 === 0 ? /^Klaar om te boeken/ : /^Te controleren/))
      // De wissel is verwerkt: de andere set rijen staat er (client-side filter).
      expect(screen.queryByText(i % 2 === 0 ? 'Leverancier 1' : 'Leverancier 0')).toBeInTheDocument()
      expect(screen.queryByText(i % 2 === 0 ? 'Leverancier 0' : 'Leverancier 1')).not.toBeInTheDocument()
    }
    // Vóór 25-09: de bulk-balk ("Klaar om te boeken" = accordering-bulk, andere tabs = documenten-bulk) mountte per wissel en
    // deed dan GET /auth/administraties — nu komt de lijst van het ouder; een tabwissel raakt de server niet.
    expect(mock.lijstAanroepen()).toBe(voorLijst)
    expect(mock.administratiesAanroepen()).toBe(voorAdm)
    expect(mock.aanroepen.length).toBe(totaalVoor)
  })

  it('een administratiewissel breekt de lopende lijst-request af (abort komt bij fetch aan) en de oude landt nooit in het nieuwe scherm', async () => {
    const mock = installFetchMock({ documenten: [document(1, 'te_controleren')], uitstellen: true })
    const { rerender } = render(
      <MemoryRouter initialEntries={[`/?administratie=${ADMIN_A}`]}>
        <WerkvoorraadScreen />
      </MemoryRouter>,
    )
    await waitFor(() => expect(mock.deferred.length).toBeGreaterThan(0))
    const eerste = mock.deferred[0]
    expect(eerste.init?.signal).toBeInstanceOf(AbortSignal)
    expect(eerste.afgebroken).toBe(false)

    // Unmount = weg van de lijst: de request moet AFGEBROKEN zijn, niet stil doorlopen.
    rerender(
      <MemoryRouter initialEntries={['/']}>
        <div />
      </MemoryRouter>,
    )
    await waitFor(() => expect(eerste.afgebroken).toBe(true))
    expect(eerste.init?.signal?.aborted).toBe(true)
  })

  it('een trage OUDERE lijst-request overschrijft een nieuwere lading niet (laatste wint; oudere afgebroken)', async () => {
    const gebruiker = userEvent.setup()
    const mock = installFetchMock({ documenten: [document(1, 'te_controleren')], uitstellen: true })
    renderScherm()
    await waitFor(() => expect(mock.deferred.length).toBeGreaterThan(0))
    const oud = mock.deferred[mock.deferred.length - 1]
    // Eerste lading afronden zodat de lijst (met toggle) staat.
    act(() => oud.resolve(jsonResponse({ documenten: [document(1, 'te_controleren')], afgehandeld: { verwijderd: 0, afgewezen: 0, samengevoegd: 0, afgevoerd_duplicaat: 0, geboekt: 0, gesplitst: 0, geaccordeerd: 0, totaal: 0 } })))
    await waitFor(() => expect(screen.getByText('Leverancier 1')).toBeInTheDocument())

    // Toggle "Toon afgehandelde documenten" = nieuwe lading (andere query) — de eerdere nog-lopende wordt afgebroken.
    const voor = mock.deferred.length
    await gebruiker.click(screen.getByRole('checkbox', { name: /Toon afgehandelde documenten/ }))
    await waitFor(() => expect(mock.deferred.length).toBe(voor + 1))
    const nieuw = mock.deferred[mock.deferred.length - 1]
    expect(nieuw.url).toContain('toon_afgehandeld=true')
    // Snel nóg een lading (uploadzone-callback simuleren is niet nodig): toggle terug = derde request, tweede afgebroken.
    await gebruiker.click(screen.getByRole('checkbox', { name: /Toon afgehandelde documenten/ }))
    await waitFor(() => expect(mock.deferred.length).toBe(voor + 2))
    expect(nieuw.afgebroken).toBe(true)
    const laatste = mock.deferred[mock.deferred.length - 1]
    act(() => laatste.resolve(jsonResponse({ documenten: [document(2, 'te_controleren')], afgehandeld: null })))
    await waitFor(() => expect(screen.getByText('Leverancier 2')).toBeInTheDocument())
    expect(screen.queryByText('Leverancier 1')).not.toBeInTheDocument()
  })

  it('de poll stapelt niet: één lijst-request tegelijk, vaste cadans, en een ongewijzigd antwoord rendert de lijst niet opnieuw', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const docs = [document(1, 'extractie_wachtrij'), document(2, 'te_controleren')]
    const mock = installFetchMock({ documenten: docs, uitstellen: true })
    renderScherm()
    await waitFor(() => expect(mock.deferred.length).toBeGreaterThan(0))
    // Eerste lading afronden.
    const eerste = mock.deferred[mock.deferred.length - 1]
    await act(async () => eerste.resolve(jsonResponse({ documenten: docs, afgehandeld: null })))
    await waitFor(() => expect(screen.getByText('Leverancier 2')).toBeInTheDocument())
    const naEersteLading = mock.lijstAanroepen()

    // Tik 1 (3 s): één poll-request start en blijft open (trage server).
    await vi.advanceTimersByTimeAsync(3100)
    expect(mock.lijstAanroepen()).toBe(naEersteLading + 1)
    // Tik 2 en 3 (6 s, 9 s) terwijl de eerste poll nog loopt: GEEN nieuwe request (vóór 25-09 stapelden ze).
    await vi.advanceTimersByTimeAsync(6100)
    expect(mock.lijstAanroepen()).toBe(naEersteLading + 1)

    // De poll rondt af mét een byte-gelijk antwoord → geen state-update (de rij-elementen blijven dezelfde DOM-knopen).
    const rijVoor = screen.getByText('Leverancier 2')
    const poll = mock.deferred[mock.deferred.length - 1]
    await act(async () => poll.resolve(jsonResponse({ documenten: docs, afgehandeld: null })))
    await vi.advanceTimersByTimeAsync(50)
    expect(screen.getByText('Leverancier 2')).toBe(rijVoor)

    // Volgende tik: de volgende poll mag weer (cadans 3 s, niet 3 s + latency).
    await vi.advanceTimersByTimeAsync(3100)
    expect(mock.lijstAanroepen()).toBe(naEersteLading + 2)
  })
})
