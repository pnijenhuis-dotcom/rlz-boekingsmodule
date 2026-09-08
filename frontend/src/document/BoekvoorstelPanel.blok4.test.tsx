import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

/** Blok 4 (bundel 08-09) — controlescherm Spot Services 2026-608: verlegd-chip oranje en één regel (4c/4d), splitsen uit
 * het veldvoorstel laat tariefstaffels weg (4a), verdelen-hint alleen zonder factuur-projectnummer (4d), berekend-btw-
 * hint als korte grijze regel (4d). Eigen testbestand (gedeelde panel-tests niet raken). */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const GB_7006 = 'cccccccc-0000-0000-0000-000000007006'
const TAXRATE_HOOG = 'dddddddd-0000-0000-0000-000000000021'
const TAXRATE_VERLEGD = 'dddddddd-0000-0000-0000-000000000009'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'
const PROJECT_26049 = 'ffffffff-0000-0000-0000-000000026049'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function regel(overrides: Record<string, unknown>) {
  return {
    id: null,
    ledger_id: null,
    taxrate_id: null,
    project_id: null,
    netto_bedrag: '2400.00',
    btw_bedrag: '0.00',
    omschrijving: 'Inhuur montage steiger week 35',
    btw_bron: null,
    gb_bron: null,
    gb_voorstel_detail: null,
    ...overrides,
  }
}

function staffel(omschrijving: string) {
  return { omschrijving, netto_bedrag: '0.00', btw_bedrag: '0.00', hoeveelheid: '0', taxrate_id: null, tariefstaffel: true }
}

/** Het AI-veldvoorstel zoals de server 'm opslaat: 3 echte + 9 tariefstaffel-regels. */
const VELDVOORSTEL = {
  bron: 'ai',
  leverancier_naam: 'Spot Services',
  factuurnummer: '2026-608',
  totaal_excl: '4320.00',
  totaal_incl: '4320.00',
  btw_bedrag: '0.00',
  btw_verlegd_vermelding: 'BTW verlegd',
  regels: [
    { omschrijving: 'Inhuur montage steiger week 35', netto_bedrag: '2400.00', btw_bedrag: '0.00', hoeveelheid: '48', taxrate_id: null, tariefstaffel: false },
    staffel('Uurtarief montage dag'),
    staffel('Uurtarief montage avond'),
    staffel('Uurtarief montage weekend'),
    { omschrijving: 'Inhuur demontage steiger week 35', netto_bedrag: '1600.00', btw_bedrag: '0.00', hoeveelheid: '32', taxrate_id: null, tariefstaffel: false },
    staffel('Uurtarief demontage dag'),
    staffel('Uurtarief demontage avond'),
    staffel('Uurtarief demontage weekend'),
    { omschrijving: 'Transport materieel', netto_bedrag: '320.00', btw_bedrag: null, hoeveelheid: '2', taxrate_id: null, tariefstaffel: false },
    staffel('Toeslag hoogwerker per dag'),
    staffel('Toeslag nachtwerk per uur'),
    staffel('Reiskosten per km'),
  ],
  regel_zekerheid: [0.93, 0.9, 0.9, 0.9, 0.93, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.85],
  zekerheid: {},
  zekerheid_drempel: 0.8,
  controle: { regelsom: '4320.00', regelsom_basis: 'excl', regelsom_wijkt_af: false, onparseerbaar: [], lage_zekerheid: [], bsn_verwijderd: 0, onvolledig: false },
}

function installFetchMock(boekvoorstel: Record<string, unknown>, opties: { projectVerplicht?: boolean } = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') return Promise.resolve(new Response(null, { status: 404 }))
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: GB_7006, code: '7006', naam: 'Inhuur montage', soort: 2 }] }))
      if (url.endsWith('/btw-codes')) {
        return Promise.resolve(
          jsonResponse({
            btw_codes: [
              { id: TAXRATE_HOOG, naam: 'NL, Hoog Tarief', percentage: 0.21 },
              { id: TAXRATE_VERLEGD, naam: 'NL, BTW verlegd (hoog)', percentage: 0 },
            ],
          }),
        )
      }
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Spot Services' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [{ id: PROJECT_26049, naam: '26049 Hoofddorp (Dura Vermeer)' }] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: opties.projectVerplicht ?? false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            vendor_id: VENDOR_ID,
            referentie: '2026-608',
            factuurdatum: '2026-09-01',
            totaalbedrag: '4320.00',
            rlz_boekstuknummer: null,
            opgeslagen: false,
            regels_samenvoegen: false,
            samenvoegen_toegestaan: true,
            samengevoegde_regel: null,
            btw_verlegd_vermelding: 'BTW verlegd',
            ...boekvoorstel,
          }),
        )
      }
      if (url.endsWith('/boekvoorstel') && init?.method === 'PUT') return Promise.resolve(jsonResponse({}))
      if (url.endsWith('/boekvoorstel/checks') && init?.method === 'POST') return Promise.resolve(new Response(null, { status: 404 }))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderPanel(extra: Partial<Parameters<typeof BoekvoorstelPanel>[0]> = {}) {
  return render(
    <BoekvoorstelPanel
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      status="te_controleren"
      veldvoorstel={VELDVOORSTEL}
      onGeboekt={() => {}}
      onHersteld={() => {}}
      {...extra}
    />,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('BoekvoorstelPanel — blok 4 Spot Services', () => {
  it('4c: btw_bron factuur_verlegd = oranje chip "uit factuur: btw verlegd" op één regel (regel-herkomst), hint-chip weg', async () => {
    installFetchMock({
      regels: [
        regel({ taxrate_id: TAXRATE_VERLEGD, btw_bron: 'factuur_verlegd' }),
        regel({ taxrate_id: TAXRATE_VERLEGD, btw_bron: 'factuur_verlegd', omschrijving: 'Inhuur demontage steiger week 35', netto_bedrag: '1600.00' }),
      ],
    })
    renderPanel()
    const chips = await screen.findAllByTestId('regel-btw-standaard-chip')
    expect(chips).toHaveLength(2)
    for (const chip of chips) {
      expect(chip).toHaveTextContent('uit factuur: btw verlegd')
      expect(chip.className).toContain('afwijking')
      expect(chip.getAttribute('data-bron')).toBe('factuur_verlegd')
      expect(chip.parentElement?.className).toBe('regel-herkomst')
    }
    expect(screen.queryByText(/kies de verlegd-code/)).not.toBeInTheDocument()
    // Geen "berekend uit tarief"-hint: verlegd-tarief = 0 % en btw 0 sluiten aan.
    expect(screen.queryByTestId('regel-btw-berekend-hint')).not.toBeInTheDocument()
  })

  it('4a: splitsen ná een samengevoegde opslag prefillt uit het veldvoorstel zónder de 9 tariefstaffels', async () => {
    const samengevoegd = regel({ omschrijving: 'Factuur 2026-608 — samengevoegd (3 regels)', netto_bedrag: '4320.00', id: 'r-1' })
    installFetchMock({ opgeslagen: true, regels_samenvoegen: true, regels: [samengevoegd], samengevoegde_regel: samengevoegd })
    renderPanel()
    const vink = await screen.findByLabelText('Splitsen per regel')
    expect(screen.getByText(/9 tariefregels zonder bedrag weggelaten/)).toBeInTheDocument()
    await userEvent.click(vink)
    await waitFor(() => expect(screen.getAllByLabelText('Netto bedrag')).toHaveLength(3))
    const omschrijvingen = screen.getAllByLabelText('Omschrijving').map((el) => (el as HTMLTextAreaElement | HTMLInputElement).value)
    expect(omschrijvingen).toEqual(['Inhuur montage steiger week 35', 'Inhuur demontage steiger week 35', 'Transport materieel'])
  })

  it('4d: draagt de factuur een projectnummer, dan géén "Verdelen over projecten…" maar "kies per regel een project"', async () => {
    installFetchMock(
      {
        regels: [
          regel({ project_id: PROJECT_26049, project_bron: 'factuur' }),
          regel({ omschrijving: 'Transport materieel', netto_bedrag: '320.00' }),
        ],
      },
      { projectVerplicht: true },
    )
    renderPanel({ onVerdelenGevraagd: () => {} })
    const hint = await screen.findByTestId('project-leeg-actie')
    expect(hint).toHaveTextContent('1 regel zonder project — kies per regel een project (de factuur noemt een projectnummer)')
    expect(within(hint).queryByRole('button', { name: 'Verdelen over projecten…' })).not.toBeInTheDocument()
  })

  it('4d: zonder factuur-projectnummer blijft de verdelen-actie staan', async () => {
    installFetchMock({ regels: [regel({}), regel({ omschrijving: 'Transport materieel', netto_bedrag: '320.00' })] }, { projectVerplicht: true })
    renderPanel({ onVerdelenGevraagd: () => {} })
    const hint = await screen.findByTestId('project-leeg-actie')
    expect(within(hint).getByRole('button', { name: 'Verdelen over projecten…' })).toBeInTheDocument()
  })

  it('4d: btw wijkt af van het tarief = één korte grijze regel mét tooltip, geen chip-blok', async () => {
    installFetchMock({ regels: [regel({ taxrate_id: TAXRATE_HOOG, netto_bedrag: '100.00', btw_bedrag: '0.00' })] })
    renderPanel()
    const hint = await screen.findByTestId('regel-btw-berekend-hint')
    expect(hint).toHaveTextContent('tarief geeft € 21,00 — factuur leidend')
    expect(hint.className).toContain('regel-herkomst')
    expect(hint.getAttribute('title')).toContain('De btw van de factuur is leidend')
    expect(hint.querySelector('.chip')).toBeNull()
  })
})
