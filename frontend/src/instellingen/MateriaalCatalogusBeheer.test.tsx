// Materiaalcatalogus — design-ronde 03-09 (mockup inzicht-kantoorbreed.html ⑦): de platte waarschuwingen per
// leverancier zijn een klikbare werklijst "Nog in te stellen" (klik = wijzig-dialoog mét focus op het veld; leeg =
// geen paneel) en de leverancier-chips krijgen een zoekveld zodra er > 15 zijn. Gemockte API, zelfde patroon als
// de andere instellingen-tests.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { bepaalWerklijst, CATALOGUS_UIT_TEKST, CHIPS_ZOEK_VANAF, heeftCatalogusToegang, MateriaalCatalogusBeheer } from './MateriaalCatalogusBeheer'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const VENDOR = 'bbbbbbbb-0000-0000-0000-000000000002'

function leverancier(over: Record<string, unknown>) {
  return {
    id: `lev-${String(over.naam ?? 'x')}`,
    naam: 'Leverancier',
    bestel_email: 'bestel@voorbeeld.nl',
    telefoon: null,
    adres: null,
    vendor_id: VENDOR,
    actief: true,
    aantal_producten: 3,
    transport_contact_naam: null,
    transport_contact_email: null,
    materiaal_contact_naam: null,
    materiaal_contact_email: null,
    ...over,
  }
}

const VIER = [
  leverancier({ naam: 'Alpha Steigers', bestel_email: null, vendor_id: null }),
  leverancier({ naam: 'Bravo Verhuur', vendor_id: null }),
  leverancier({ naam: 'Charlie Compleet' }),
  leverancier({ naam: 'Delta Inactief', actief: false, bestel_email: null, vendor_id: null }),
]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetch(leveranciers: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      if (url.startsWith(`/materiaal/${ADM}/leveranciers?`)) return Promise.resolve(json(leveranciers))
      if (url === `/administraties/${ADM}/crediteuren`) return Promise.resolve(json({ crediteuren: [{ id: VENDOR, naam: 'Alpha Steigers B.V. (RLZ)' }] }))
      if (url.startsWith(`/materiaal/${ADM}/producten?`)) return Promise.resolve(json({ items: [], totaal: 0, pagina: 1, per_pagina: 25 }))
      if (/\/materiaal\/.*\/leveranciers\/.*\/catalogus/.test(url)) return Promise.resolve(json([]))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderScherm() {
  return render(<MateriaalCatalogusBeheer administraties={[{ id: ADM, naam: 'Universal Steigerbouw B.V.' } as never]} />)
}

describe('MateriaalCatalogusBeheer — werklijst + chip-zoek (03-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('bepaalWerklijst: één regel per probleem, alleen actieve leveranciers, complete leverancier levert niets', () => {
    const regels = bepaalWerklijst(VIER as never)
    expect(regels.map((r) => `${r.lev.naam} — ${r.tekst}`)).toEqual([
      'Alpha Steigers — geen bestel-mailadres',
      'Alpha Steigers — geen crediteur-koppeling (factuurcontrole uit)',
      'Bravo Verhuur — geen crediteur-koppeling (factuurcontrole uit)',
    ])
  })

  it('toont de werklijst "Nog in te stellen" mét teller; klik opent de wijzig-dialoog van díe leverancier met focus op het veld', async () => {
    const gebruiker = userEvent.setup()
    installFetch(VIER)
    renderScherm()
    const werklijst = await screen.findByTestId('materiaal-werklijst')
    expect(within(werklijst).getByRole('heading', { name: 'Nog in te stellen' })).toBeInTheDocument()
    expect(within(werklijst).getByText('3')).toBeInTheDocument()
    expect(within(werklijst).getAllByRole('button')).toHaveLength(3)
    expect(within(werklijst).queryByText(/Delta Inactief/)).not.toBeInTheDocument()
    expect(within(werklijst).queryByText(/Charlie/)).not.toBeInTheDocument()

    await gebruiker.click(within(werklijst).getByRole('button', { name: 'Bravo Verhuur — geen crediteur-koppeling (factuurcontrole uit)' }))
    const dialoog = await screen.findByRole('dialog', { name: 'Leverancier wijzigen' })
    expect(within(dialoog).getByLabelText('Naam')).toHaveValue('Bravo Verhuur')
    await waitFor(() => expect(within(dialoog).getByLabelText(/RLZ-crediteur/)).toHaveFocus())
    // De crediteur-optie uit de administratie staat klaar in de keuzelijst.
    expect(within(dialoog).getByRole('option', { name: 'Alpha Steigers B.V. (RLZ)' })).toBeInTheDocument()
    await gebruiker.click(within(dialoog).getByRole('button', { name: 'Annuleren' }))

    await gebruiker.click(within(werklijst).getByRole('button', { name: 'Alpha Steigers — geen bestel-mailadres' }))
    const dialoog2 = await screen.findByRole('dialog', { name: 'Leverancier wijzigen' })
    expect(within(dialoog2).getByLabelText('Naam')).toHaveValue('Alpha Steigers')
    await waitFor(() => expect(within(dialoog2).getByLabelText(/Bestel-mailadres/)).toHaveFocus())
  })

  it('geen problemen = geen paneel; onder de grens geen chip-zoekveld', async () => {
    installFetch([leverancier({ naam: 'Charlie Compleet' }), leverancier({ naam: 'Echo Compleet' })])
    renderScherm()
    await screen.findByText('Charlie Compleet · 3')
    expect(screen.queryByTestId('materiaal-werklijst')).not.toBeInTheDocument()
    expect(screen.queryByRole('searchbox', { name: 'Zoek leverancier' })).not.toBeInTheDocument()
  })

  it(`chip-zoekveld verschijnt boven ${CHIPS_ZOEK_VANAF} leveranciers en filtert de chips op naam (client-side)`, async () => {
    const gebruiker = userEvent.setup()
    const veel = Array.from({ length: CHIPS_ZOEK_VANAF + 1 }, (_, i) => leverancier({ naam: `Leverancier ${String(i + 1).padStart(2, '0')}` }))
    installFetch(veel)
    renderScherm()
    await screen.findByText('Leverancier 01 · 3')
    const zoek = screen.getByRole('searchbox', { name: 'Zoek leverancier' })
    expect(screen.getAllByText(/^Leverancier \d\d · 3$/)).toHaveLength(CHIPS_ZOEK_VANAF + 1)
    await gebruiker.type(zoek, 'leverancier 1')
    // "Leverancier 10" t/m "Leverancier 16" = 7 chips.
    expect(screen.getAllByText(/^Leverancier \d\d · 3$/)).toHaveLength(7)
    await gebruiker.clear(zoek)
    await gebruiker.type(zoek, 'bestaat niet')
    expect(screen.queryByText(/^Leverancier \d\d · 3$/)).not.toBeInTheDocument()
    expect(screen.getByText(/geen leverancier met/)).toBeInTheDocument()
  })
})

describe('MateriaalCatalogusBeheer — toegang bij Odoo (Odoo-afrondingsrun 04-09 blok B)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('heeftCatalogusToegang: uren-opt-in ÓF Odoo-backend ÓF Odoo-leesbron — spiegel van de backend-poort', () => {
    expect(heeftCatalogusToegang({})).toBe(false)
    expect(heeftCatalogusToegang({ uren_meerwerk_ingeschakeld: false, boekhoud_backend: 'rlz', odoo_alleen_lezen: false })).toBe(false)
    expect(heeftCatalogusToegang({ uren_meerwerk_ingeschakeld: true })).toBe(true)
    expect(heeftCatalogusToegang({ boekhoud_backend: 'odoo' })).toBe(true)
    expect(heeftCatalogusToegang({ boekhoud_backend: 'rlz', odoo_alleen_lezen: true })).toBe(true)
  })

  it('lege administratielijst = lege stand mét uitleg, geen catalogus-fetch', () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 404 })))
    vi.stubGlobal('fetch', fetchMock)
    render(<MateriaalCatalogusBeheer administraties={[]} />)
    expect(screen.getByTestId('materiaal-geen-administratie')).toHaveTextContent(/Uren & meerwerk aan heeft óf een Odoo-koppeling/)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('409 van de server = de nieuwe leesbare reden (Uren & meerwerk óf Odoo-koppeling), niet meer "hoort bij de steigerbouw-tak"', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.startsWith(`/materiaal/${ADM}/leveranciers?`)) return Promise.resolve(json({ detail: 'Materiaalcatalogus vereist Uren & meerwerk óf een Odoo-koppeling voor deze administratie' }, 409))
        if (url === `/administraties/${ADM}/crediteuren`) return Promise.resolve(json({ crediteuren: [] }))
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    renderScherm()
    expect(await screen.findByText(CATALOGUS_UIT_TEKST)).toBeInTheDocument()
    expect(screen.queryByText(/steigerbouw-tak/)).not.toBeInTheDocument()
  })
})
