import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ActivaKandidaatDto, ActivaVoorstelDto } from '../activa/activaApi'
import { ActivaVoorstelKaart } from './ActivaVoorstelKaart'

// Activum aanmaken? (Activa / MVA fase 1, akkoord Peter 21-09, mockup controlescherm-v2 ⑨): voorstel-kaart per
// boekvoorstelregel op een activarekening ≥ grens — chip "wordt activum", voorgevulde velden, fiscale signalen, knoppen
// "Aanmaken ná boeken"/"Activum aanmaken" + "Niet activeren…" mét verplichte reden; stand per koppeling; onder de grens =
// oranje regel; register dicht = knop uit. Nooit een blokkade en stil zonder kandidaten.

const ADMIN = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOC = 'bbbbbbbb-0000-0000-0000-000000000002'
const BASIS = `/administraties/${ADMIN}/documenten/${DOC}/activa-voorstel`

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function kandidaat(overrides: Partial<ActivaKandidaatDto> = {}): ActivaKandidaatDto {
  return {
    regel_volgnummer: 1,
    ledger_id: 'gb-0107',
    ledger_code: '0107',
    ledger_naam: 'Inventaris',
    omschrijving: 'Keuken Mantelzorgwoning Druten',
    aanschafwaarde: '11157.02',
    aanschafdatum: '2026-08-10',
    categorie: 'inventaris',
    categorie_label: 'Inventaris',
    termijn_maanden: 60,
    methode_naam: 'Lineair 5 jaar',
    restwaarde: '0.00',
    afschrijving_ledger_id: 'gb-0108',
    afschrijving_ledger_code: '0108',
    signalen: [{ code: 'kia_mia_mogelijk', tekst: 'KIA/MIA/Vamil mogelijk van toepassing — adviseur beslist' }],
    koppeling: null,
    ...overrides,
  }
}

function voorstel(overrides: Partial<ActivaVoorstelDto> = {}): ActivaVoorstelDto {
  return {
    administratie_id: ADMIN,
    document_id: DOC,
    document_geboekt: false,
    grens: '450.00',
    grens_bron: 'rlz',
    automatisch_ingeschakeld: false,
    register_leesbaar: true,
    register_fout: null,
    kandidaten: [kandidaat()],
    onder_grens: [],
    afschrijving_ledger_opties: [
      { ledger_id: 'gb-0108', code: '0108', naam: 'Afschrijving inventaris' },
      { ledger_id: 'gb-0118', code: '0118', naam: 'Afschrijving machines' },
    ],
    ...overrides,
  }
}

interface Aanroep {
  url: string
  body: unknown
}

function installFetch(body: ActivaVoorstelDto | Response, posts?: Aanroep[], postAntwoord?: (url: string) => ActivaVoorstelDto | Response) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && url.startsWith(BASIS)) {
        posts?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        const antwoord = postAntwoord?.(url) ?? voorstel()
        return Promise.resolve(antwoord instanceof Response ? antwoord : json(antwoord))
      }
      if (url === BASIS) return Promise.resolve(body instanceof Response ? body : json(body))
      return Promise.resolve(json({ detail: `onverwacht pad ${url}` }, 500))
    }),
  )
}

function toon(props: Partial<Parameters<typeof ActivaVoorstelKaart>[0]> = {}) {
  return render(<ActivaVoorstelKaart administratieId={ADMIN} documentId={DOC} status="te_controleren" soort="inkoopfactuur" {...props} />)
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ActivaVoorstelKaart', () => {
  it('toont per kandidaat de voorgevulde velden, de chip "wordt activum", het fiscale signaal en de voorgevulde afschrijvingsrekening', async () => {
    installFetch(voorstel())
    toon()
    const kaart = await screen.findByTestId('activa-kandidaat-1')
    expect(screen.getByTestId('activa-chip-aantal')).toHaveTextContent('1 regel wordt activum')
    expect(within(kaart).getByTestId('activa-chip-wordt-activum')).toHaveTextContent('wordt activum')
    expect(kaart).toHaveTextContent('Keuken Mantelzorgwoning Druten')
    expect(kaart).toHaveTextContent(/rekening\s*0107\s*Inventaris/)
    expect(kaart).toHaveTextContent(/aanschafwaarde\s*€\s?11\.157,02/)
    expect(kaart).toHaveTextContent(/categorie\s*Inventaris/)
    expect(kaart).toHaveTextContent(/Lineair 5 jaar \(60 mnd\)/)
    expect(within(kaart).getByTestId('activa-signalen')).toHaveTextContent('KIA/MIA/Vamil mogelijk van toepassing')
    expect(within(kaart).getByRole('combobox', { name: 'Afschrijvingsrekening' })).toHaveValue('0108 · Afschrijving inventaris')
    // Document nog niet geboekt → de primaire knop zegt dat het activum ná boeken komt.
    expect(within(kaart).getByRole('button', { name: 'Aanmaken ná boeken' })).toBeEnabled()
    expect(within(kaart).getByRole('button', { name: 'Niet activeren…' })).toBeInTheDocument()
    expect(within(kaart).queryByTestId('activa-chip-controleer')).toBeNull()
  })

  it('"Aanmaken ná boeken" POST de gekozen afschrijvingsrekening en toont daarna de stand gepland mét "Toch niet"', async () => {
    const gebruiker = userEvent.setup()
    const posts: Aanroep[] = []
    installFetch(voorstel(), posts, () =>
      voorstel({
        kandidaten: [
          kandidaat({
            koppeling: { id: 'k1', status: 'gepland', herkomst: 'mens', rlz_fixed_asset_id: null, rlz_receipt_number: null, reden: null, door: 'P. Nijenhuis', gewijzigd_op: '2026-09-21T10:00:00Z' },
          }),
        ],
      }),
    )
    toon()
    await gebruiker.click(await screen.findByRole('button', { name: 'Aanmaken ná boeken' }))
    await waitFor(() => expect(screen.getByTestId('activa-chip-gepland')).toHaveTextContent('gepland — ná boeken'))
    expect(posts).toEqual([{ url: `${BASIS}/1/aanmaken`, body: { afschrijving_ledger_id: 'gb-0108' } }])
    expect(screen.getByRole('button', { name: 'Toch niet' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Aanmaken ná boeken' })).toBeNull()
  })

  it('geboekt document → label "Activum aanmaken"', async () => {
    installFetch(voorstel({ document_geboekt: true }))
    toon({ status: 'geboekt' })
    expect(await screen.findByRole('button', { name: 'Activum aanmaken' })).toBeEnabled()
  })

  it('"Niet activeren…" vraagt een verplichte reden; zonder reden kan niet bevestigd worden, mét reden gaat de reden mee', async () => {
    const gebruiker = userEvent.setup()
    const posts: Aanroep[] = []
    installFetch(voorstel(), posts, () =>
      voorstel({
        kandidaten: [
          kandidaat({
            koppeling: { id: 'k1', status: 'overgeslagen', herkomst: 'mens', rlz_fixed_asset_id: null, rlz_receipt_number: null, reden: 'huur, geen eigendom', door: 'P. Nijenhuis', gewijzigd_op: null },
          }),
        ],
      }),
    )
    toon()
    await gebruiker.click(await screen.findByRole('button', { name: 'Niet activeren…' }))
    const dialoog = await screen.findByTestId('activa-niet-activeren-dialoog')
    const bevestig = within(dialoog).getByRole('button', { name: 'Niet activeren' })
    expect(bevestig).toBeDisabled()
    await gebruiker.type(within(dialoog).getByLabelText('Reden (verplicht)'), 'huur, geen eigendom')
    expect(bevestig).toBeEnabled()
    await gebruiker.click(bevestig)
    await waitFor(() => expect(screen.getByTestId('activa-chip-overgeslagen')).toHaveTextContent('niet geactiveerd'))
    expect(posts).toEqual([{ url: `${BASIS}/1/overslaan`, body: { reden: 'huur, geen eigendom' } }])
    expect(screen.getByText(/reden: huur, geen eigendom/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Toch aanmaken' })).toBeInTheDocument()
    expect(screen.queryByTestId('activa-niet-activeren-dialoog')).toBeNull()
  })

  it('standen: aangemaakt = groene status-chip mét RLZ-nummer; mislukt = rode reden + "Opnieuw aanmaken"; beoordelen = oranje ná storno', async () => {
    installFetch(
      voorstel({
        kandidaten: [
          kandidaat({
            regel_volgnummer: 1,
            koppeling: { id: 'k1', status: 'aangemaakt', herkomst: 'automatisch', rlz_fixed_asset_id: 'fa-1', rlz_receipt_number: '21', reden: null, door: null, gewijzigd_op: null },
          }),
          kandidaat({
            regel_volgnummer: 2,
            omschrijving: 'Laptop',
            koppeling: { id: 'k2', status: 'mislukt', herkomst: 'mens', rlz_fixed_asset_id: null, rlz_receipt_number: null, reden: 'geen afschrijvingsrekening — kies op de kaart of stel in onder Instellingen › Activa', door: null, gewijzigd_op: null },
          }),
          kandidaat({
            regel_volgnummer: 3,
            omschrijving: 'Bestelbus',
            koppeling: { id: 'k3', status: 'beoordelen', herkomst: 'mens', rlz_fixed_asset_id: 'fa-3', rlz_receipt_number: '22', reden: null, door: null, gewijzigd_op: null },
          }),
        ],
      }),
    )
    toon({ status: 'geboekt' })
    const k1 = await screen.findByTestId('activa-kandidaat-1')
    expect(within(k1).getByTestId('activa-chip-aangemaakt')).toHaveTextContent('aangemaakt in RLZ · nr 21')
    expect(within(k1).queryByRole('button')).toBeNull()
    expect(within(k1).queryByRole('combobox')).toBeNull()
    const k2 = screen.getByTestId('activa-kandidaat-2')
    expect(within(k2).getByTestId('activa-mislukt')).toHaveTextContent(/aanmaken mislukt — geen afschrijvingsrekening/)
    expect(within(k2).getByRole('button', { name: 'Opnieuw aanmaken' })).toBeEnabled()
    const k3 = screen.getByTestId('activa-kandidaat-3')
    expect(within(k3).getByTestId('activa-chip-beoordelen')).toHaveTextContent(/factuur gestorneerd — beoordeel het activum in RLZ/)
    expect(screen.getByTestId('activa-chip-aantal')).toHaveTextContent('3 regels worden activum')
  })

  it('categorie onbekend → chip "controleer"; onder de grens → oranje regel zonder kaart', async () => {
    installFetch(
      voorstel({
        kandidaten: [kandidaat({ categorie: 'onbekend', categorie_label: 'Onbekend — controleer', ledger_naam: 'Overige vaste activa' })],
        onder_grens: [{ regel_volgnummer: 2, ledger_code: '0107', ledger_naam: 'Inventaris', netto: '120.00', tekst: '' }],
      }),
    )
    toon()
    expect(await screen.findByTestId('activa-chip-controleer')).toHaveTextContent('controleer')
    expect(screen.getByTestId('activa-onder-grens')).toHaveTextContent(
      /0107 Inventaris €\s?120,00 staat op een activarekening onder de grens €\s?450,00 — kleine aanschaf direct ten laste van het resultaat\?/,
    )
    expect(screen.queryByTestId('activa-kandidaat-2')).toBeNull()
  })

  it('register niet leesbaar (403 op FixedAssets) → oranje regel en de aanmaak-knop uitgeschakeld mét die tekst', async () => {
    installFetch(voorstel({ register_leesbaar: false, register_fout: 'HTTP 403 op FixedAssets' }))
    toon()
    expect(await screen.findByTestId('activa-register-dicht')).toHaveTextContent(/activaregister in RLZ niet leesbaar — recht ontbreekt op de webservice-login/)
    const knop = screen.getByRole('button', { name: 'Aanmaken ná boeken' })
    expect(knop).toBeDisabled()
    expect(knop).toHaveAttribute('title', expect.stringMatching(/recht ontbreekt/))
    // Niet activeren blijft mogelijk: dat besluit raakt RLZ niet.
    expect(screen.getByRole('button', { name: 'Niet activeren…' })).toBeEnabled()
  })

  it('een fout bij een handeling blijft op de kaart staan (role=alert), het scherm blokkeert niet', async () => {
    const gebruiker = userEvent.setup()
    installFetch(voorstel(), [], () => json({ detail: 'al_aangemaakt' }, 409))
    toon()
    await gebruiker.click(await screen.findByRole('button', { name: 'Aanmaken ná boeken' }))
    expect(await screen.findByTestId('activa-fout')).toHaveTextContent('al_aangemaakt')
    expect(screen.getByRole('button', { name: 'Aanmaken ná boeken' })).toBeEnabled()
  })

  it('stil: geen kandidaten en niets onder de grens, geen inkoopfactuur, of een leesfout → niets gerenderd', async () => {
    installFetch(voorstel({ kandidaten: [], onder_grens: [] }))
    const { container, unmount } = toon()
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    expect(container).toBeEmptyDOMElement()
    unmount()

    vi.mocked(fetch).mockClear()
    const { container: c2, unmount: u2 } = toon({ soort: 'kassarapport' })
    expect(vi.mocked(fetch)).not.toHaveBeenCalled()
    expect(c2).toBeEmptyDOMElement()
    u2()

    installFetch(json({ detail: 'kapot' }, 500))
    const { container: c3 } = toon()
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    expect(c3).toBeEmptyDOMElement()
  })

  it('herleest ná een opgeslagen boekvoorstel (boekvoorstelVersie) — regels en bedragen kunnen gewijzigd zijn', async () => {
    installFetch(voorstel())
    const { rerender } = toon({ boekvoorstelVersie: 0 })
    await screen.findByTestId('activa-kandidaat-1')
    const eerst = vi.mocked(fetch).mock.calls.length
    rerender(<ActivaVoorstelKaart administratieId={ADMIN} documentId={DOC} status="te_controleren" soort="inkoopfactuur" boekvoorstelVersie={1} />)
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(eerst))
  })
})
