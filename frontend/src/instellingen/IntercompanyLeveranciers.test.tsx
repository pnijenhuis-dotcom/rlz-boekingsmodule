// Nachtrun 08/09-09 blok 1: blok "Intercompany — accordering overslaan" op de Klant-accordering-tab van de
// administratie-detailpagina — crediteur-combobox, lijst met verwijder-kruisje (alleen handmatige rijen),
// mapping-rijen alleen-lezen met herkomst "doorbelasting", historie uit het audit-spoor.

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IntercompanyLeveranciers } from './IntercompanyLeveranciers'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const ADM = 'adm-1'
const UN = 'vendor-un'
const FLOOR = 'vendor-floor'
const KEMPEN = 'vendor-kempen'

const LEEG = { leveranciers: [], historie: [] }
const MET_RIJEN = {
  leveranciers: [
    { vendor_id: KEMPEN, naam: 'Kempen Facilities B.V.', bron: 'doorbelasting_mapping', actief: true, gewijzigd_op: null, verwijderbaar: false },
    { vendor_id: UN, naam: 'Universal Nederland B.V.', bron: 'handmatig', actief: true, gewijzigd_op: '2026-09-08T22:00:00Z', verwijderbaar: true },
  ],
  historie: [
    { tijdstip: '2026-09-08T22:00:00Z', actor_naam: 'P. Nijenhuis', actie: 'gemarkeerd', vendor_id: UN, naam: 'Universal Nederland B.V.', reden: 'besluit 08-09 intercompany Universal', bron: 'handmatig' },
  ],
}

function stubFetch(start: unknown) {
  const aanroepen: { pad: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      aanroepen.push({ pad: url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
      if (url === `/administraties/${ADM}/crediteuren`)
        return Promise.resolve(
          jsonResponse({
            crediteuren: [
              { id: UN, naam: 'Universal Nederland B.V.' },
              { id: FLOOR, naam: 'Floor B.V.' },
              { id: KEMPEN, naam: 'Kempen Facilities B.V.' },
              { id: 'naamloos', naam: null },
            ],
          }),
        )
      if (url === `/administraties/${ADM}/intercompany-leveranciers` && method === 'GET') return Promise.resolve(jsonResponse(start))
      if (url === `/administraties/${ADM}/intercompany-leveranciers/${UN}` && method === 'PUT') return Promise.resolve(jsonResponse(MET_RIJEN))
      if (url === `/administraties/${ADM}/intercompany-leveranciers/${UN}` && method === 'DELETE')
        return Promise.resolve(jsonResponse({ leveranciers: [MET_RIJEN.leveranciers[0]], historie: [{ ...MET_RIJEN.historie[0], actie: 'verwijderd', reden: null }, ...MET_RIJEN.historie] }))
      if (url === `/administraties/${ADM}/intercompany-leveranciers/${KEMPEN}` && method === 'DELETE')
        return Promise.resolve(jsonResponse({ detail: 'Deze leverancier komt uit de doorbelasting-mapping — de vlag volgt die mapping (tab Doorbelasting)' }, 409))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aanroepen
}

describe('IntercompanyLeveranciers', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('lege stand → uitleg; kiezen via de crediteur-combobox + reden → PUT en de lijst toont de nieuwe rij', async () => {
    const aanroepen = stubFetch(LEEG)
    const gebruiker = userEvent.setup()
    render(<IntercompanyLeveranciers administratieId={ADM} naam="Universal Steigerbouw B.V." />)
    await screen.findByText(/Nog geen intercompany-leveranciers/)

    const knop = screen.getByRole('button', { name: 'Markeren als intercompany' })
    expect(knop).toBeDisabled()
    const veld = screen.getByRole('combobox', { name: /Intercompany-leverancier toevoegen/ })
    await gebruiker.click(veld)
    await gebruiker.type(veld, 'Universal')
    await gebruiker.click(await screen.findByRole('option', { name: 'Universal Nederland B.V.' }))
    // een crediteur zonder naam staat niet in de kiezer
    await gebruiker.type(screen.getByPlaceholderText(/besluit 08-09/), 'besluit 08-09 intercompany Universal')
    expect(knop).toBeEnabled()
    await gebruiker.click(knop)

    await screen.findByText('Universal Nederland B.V.')
    const put = aanroepen.find((a) => a.method === 'PUT')
    expect(put).toMatchObject({ pad: `/administraties/${ADM}/intercompany-leveranciers/${UN}`, body: { reden: 'besluit 08-09 intercompany Universal' } })
    // herkomst-chips: handmatig verwijderbaar, doorbelasting alleen-lezen
    expect(screen.getByRole('button', { name: 'Verwijder Universal Nederland B.V. als intercompany-leverancier' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Verwijder Kempen Facilities/ })).not.toBeInTheDocument()
    expect(screen.getByText('doorbelasting')).toBeInTheDocument()
    expect(screen.getByText('handmatig')).toBeInTheDocument()
    // historie uit het audit-spoor
    await gebruiker.click(screen.getByRole('button', { name: 'Historie (1)' }))
    expect(screen.getByText(/P\. Nijenhuis: Universal Nederland B\.V\. gemarkeerd als intercompany — besluit 08-09/)).toBeInTheDocument()
  })

  it('verwijder-kruisje → DELETE en de rij verdwijnt; een al gemarkeerde crediteur staat niet meer in de kiezer', async () => {
    const aanroepen = stubFetch(MET_RIJEN)
    const gebruiker = userEvent.setup()
    render(<IntercompanyLeveranciers administratieId={ADM} naam="Universal Steigerbouw B.V." />)
    await screen.findByText('Universal Nederland B.V.')

    const veld = screen.getByRole('combobox', { name: /Intercompany-leverancier toevoegen/ })
    await gebruiker.click(veld)
    await gebruiker.type(veld, 'B.V.')
    await screen.findByRole('option', { name: 'Floor B.V.' })
    expect(screen.queryByRole('option', { name: 'Universal Nederland B.V.' })).not.toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Kempen Facilities B.V.' })).not.toBeInTheDocument()
    await gebruiker.keyboard('{Escape}')

    await gebruiker.click(screen.getByRole('button', { name: 'Verwijder Universal Nederland B.V. als intercompany-leverancier' }))
    await waitFor(() => expect(screen.queryByText('Universal Nederland B.V.')).not.toBeInTheDocument())
    expect(aanroepen.find((a) => a.method === 'DELETE')?.pad).toBe(`/administraties/${ADM}/intercompany-leveranciers/${UN}`)
    const lijst = screen.getByRole('list')
    expect(within(lijst).getByText('Kempen Facilities B.V.')).toBeInTheDocument()
  })
})
