import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DoorbelastingMappingDto, DoorbelastingRunDto, SpiegelTaakDto } from '../api/types'
import { DoorbelastenSectie } from './DoorbelastenSectie'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const RUN_ID = 'cccccccc-0000-0000-0000-000000000003'
const MAPPING_GEBOEKT = 'dddddddd-0000-0000-0000-000000000004'
const MAPPING_SPIEGEL = 'dddddddd-0000-0000-0000-000000000005'
const BOEKING_GEBOEKT = 'eeeeeeee-0000-0000-0000-000000000006'
const BOEKING_SPIEGEL = 'eeeeeeee-0000-0000-0000-000000000007'
const REGEL_ID = 'ffffffff-0000-0000-0000-000000000008'
const BRON_REGEL_ID = 'ffffffff-0000-0000-0000-000000000009'
const DOEL_ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000010'
const LEDGER_ID = '99999999-0000-0000-0000-000000000011'
const PROVISIE_LEDGER_ID = '99999999-0000-0000-0000-000000000012'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function run(overrides: Partial<DoorbelastingRunDto> = {}): DoorbelastingRunDto {
  return {
    id: RUN_ID,
    document_id: DOCUMENT_ID,
    status: 'concept',
    laatste_fout: null,
    regels: [],
    previews: [],
    checks: { geblokkeerd: true, resultaten: [] },
    ...overrides,
  }
}

function mappingSpiegel(overrides: Partial<DoorbelastingMappingDto> = {}): DoorbelastingMappingDto {
  return {
    id: MAPPING_SPIEGEL,
    doelentiteit_naam: 'Rubicon Investments B.V.',
    doel_customer_guid: '2f432363-127b-40e4-b331-ea8c03d4653d',
    doel_administratie_id: DOEL_ADMINISTRATIE_ID,
    intercompany: false,
    provisie_kosten_ledger_id: PROVISIE_LEDGER_ID,
    laatste_kosten_ledger_id: null,
    actief: true,
    ...overrides,
  }
}

function spiegelTaak(): SpiegelTaakDto {
  return {
    boeking_id: BOEKING_SPIEGEL,
    document_id: DOCUMENT_ID,
    mapping_id: MAPPING_SPIEGEL,
    doelentiteit_naam: 'Rubicon Investments B.V.',
    netto_totaal: '205.55',
    provisie_bedrag: '10.28',
    verkoop_referentie: 'VF-2026-0101',
    aangemaakt_op: '2026-08-13T09:00:00Z',
  }
}

interface MockOpties {
  ingeschakeld?: boolean
  /** null = geen run (GET geeft 404); undefined = default lege concept-run */
  run?: DoorbelastingRunDto | null
  taken?: SpiegelTaakDto[]
  mappings?: DoorbelastingMappingDto[]
  doelGbsAanroepen?: { url: string; body: unknown }[]
  spiegelBoekenAanroepen?: string[]
  stornoAanroepen?: { url: string; body: unknown }[]
  volgorde?: string[]
  /** registreert POST's op de run-route — de sectie mag die nooit doen (leesroute = GET) */
  postAanroepen?: string[]
}

function installFetchMock(opties: MockOpties = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/doorbelasting-instelling')) {
        return Promise.resolve(jsonResponse({ ingeschakeld: opties.ingeschakeld ?? true }))
      }
      if (url.endsWith(`/documenten/${DOCUMENT_ID}/run`) && init?.method === 'POST') {
        // de POST bestaat alleen nog als expliciete gebruikersactie (reviewscherm) — de
        // sectie zelf mag 'm nooit aanroepen (fix 2026-08-13, zie de aparte test hieronder)
        opties.postAanroepen?.push(url)
        return Promise.resolve(jsonResponse(opties.run ?? run()))
      }
      if (url.endsWith(`/documenten/${DOCUMENT_ID}/run`)) {
        // read-only leesroute (GET): 404 = geen run
        return Promise.resolve(
          opties.run === null
            ? jsonResponse({ detail: 'Geen doorbelasting-run voor dit document' }, 404)
            : jsonResponse(opties.run ?? run()),
        )
      }
      if (url.endsWith('/spiegel-taken')) {
        return Promise.resolve(jsonResponse(opties.taken ?? []))
      }
      if (url.endsWith(`/doorbelasting/${ADMINISTRATIE_ID}/mappings`)) {
        return Promise.resolve(jsonResponse(opties.mappings ?? []))
      }
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(
          jsonResponse({
            rekeningen: [
              { ledger_id: LEDGER_ID, code: '4110', naam: 'Bouwmaterialen', soort: 2 },
              { ledger_id: PROVISIE_LEDGER_ID, code: '4808', naam: 'Provisie groepsmaatschappijen', soort: 2 },
            ],
          }),
        )
      }
      if (url.endsWith('/doel-gbs') && init?.method === 'PUT') {
        opties.volgorde?.push('doel-gbs')
        opties.doelGbsAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      if (url.endsWith('/spiegel-boeken') && init?.method === 'POST') {
        opties.volgorde?.push('spiegel-boeken')
        opties.spiegelBoekenAanroepen?.push(url)
        return Promise.resolve(jsonResponse({ per_doelentiteit: { [MAPPING_SPIEGEL]: 'geboekt' } }))
      }
      if (url.endsWith('/storno') && init?.method === 'POST') {
        opties.stornoAanroepen?.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(jsonResponse({ per_doelentiteit: { [MAPPING_GEBOEKT]: 'gestorneerd' } }))
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
}

function renderSectie(status = 'geboekt', soort = 'inkoopfactuur') {
  return render(
    <MemoryRouter>
      <DoorbelastenSectie
        administratieId={ADMINISTRATIE_ID}
        documentId={DOCUMENT_ID}
        status={status}
        soort={soort}
      />
    </MemoryRouter>,
  )
}

describe('DoorbelastenSectie', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('verschijnt niet op een niet-geboekt document en raakt de API dan niet aan', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    renderSectie('te_controleren')
    expect(screen.queryByText('Doorbelasting')).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('verschijnt niet op een geboekt kassarapport (alleen inkoopfacturen)', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    renderSectie('geboekt', 'kassarapport')
    expect(screen.queryByText('Doorbelasting')).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('verschijnt niet als de doorbelasting-toggle uit staat', async () => {
    installFetchMock({ ingeschakeld: false })
    renderSectie()
    // De toggle-GET moet eerst afgerond zijn vóór we "geen sectie" kunnen concluderen.
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    expect(screen.queryByText('Doorbelasting')).not.toBeInTheDocument()
  })

  it('toont bij een lege concept-run de actie "Doorbelasten…" naar het reviewscherm', async () => {
    installFetchMock()
    renderSectie()
    const knop = await screen.findByRole('link', { name: 'Doorbelasten…' })
    expect(knop).toHaveAttribute('href', `/doorbelasting/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`)
    expect(screen.getByText('nog niet doorbelast')).toBeInTheDocument()
  })

  it('leest via GET en maakt bij het openen nooit een run aan (POST alleen als gebruikersactie)', async () => {
    const postAanroepen: string[] = []
    installFetchMock({ run: null, postAanroepen })
    renderSectie()
    // geen run (404) → intro + knop, en er is géén POST gedaan door het louter openen
    const knop = await screen.findByRole('link', { name: 'Doorbelasten…' })
    expect(knop).toHaveAttribute('href', `/doorbelasting/${ADMINISTRATIE_ID}/${DOCUMENT_ID}`)
    expect(postAanroepen).toHaveLength(0)
  })

  it('toont per doelentiteit een statuschip (geboekt ✓ / spiegel open / half geboekt) + laatste_fout', async () => {
    installFetchMock({
      run: run({
        laatste_fout: { melding: 'RLZ gaf 502' },
        previews: [
          {
            mapping_id: MAPPING_GEBOEKT,
            doelentiteit_naam: 'Kempen Chalets B.V.',
            onboarded: true,
            netto_totaal: '762.00',
            provisie_bedrag: '38.10',
            btw_bedrag: '168.02',
            boeking_status: 'geboekt',
            boeking_id: BOEKING_GEBOEKT,
          },
          {
            mapping_id: MAPPING_SPIEGEL,
            doelentiteit_naam: 'Rubicon Investments B.V.',
            onboarded: false,
            netto_totaal: '205.55',
            provisie_bedrag: '10.28',
            btw_bedrag: '45.32',
            boeking_status: 'half_geboekt',
            boeking_id: null,
          },
        ],
      }),
    })
    renderSectie()

    expect(await screen.findByText('geboekt ✓')).toBeInTheDocument()
    expect(screen.getByText('half geboekt')).toBeInTheDocument()
    expect(screen.getByText('deels doorbelast')).toBeInTheDocument()
    expect(screen.getByText(/De laatste boekpoging gaf een fout/)).toBeInTheDocument()
    // Geboekte deelboeking mét boeking_id → storno-knop; half_geboekt zonder id → geen tweede knop.
    expect(screen.getAllByRole('button', { name: 'Storneren…' })).toHaveLength(1)
  })

  it('storneert een geboekte deelboeking via de modal met verplichte reden', async () => {
    const stornoAanroepen: { url: string; body: unknown }[] = []
    installFetchMock({
      stornoAanroepen,
      run: run({
        previews: [
          {
            mapping_id: MAPPING_GEBOEKT,
            doelentiteit_naam: 'Kempen Chalets B.V.',
            onboarded: true,
            netto_totaal: '762.00',
            provisie_bedrag: '38.10',
            btw_bedrag: '168.02',
            boeking_status: 'geboekt',
            boeking_id: BOEKING_GEBOEKT,
          },
        ],
      }),
    })
    renderSectie()
    const gebruiker = userEvent.setup()

    await gebruiker.click(await screen.findByRole('button', { name: 'Storneren…' }))
    const stornoKnop = screen.getByRole('button', { name: 'Storneren' })
    // Reden verplicht (≥5 tekens): zonder reden blijft de knop uit.
    expect(stornoKnop).toBeDisabled()
    await gebruiker.type(screen.getByLabelText(/Reden van stornering/), 'dubbel doorbelast')
    await gebruiker.click(screen.getByRole('button', { name: 'Storneren' }))

    await waitFor(() => expect(stornoAanroepen).toHaveLength(1))
    expect(stornoAanroepen[0].url).toContain(`/boekingen/${BOEKING_GEBOEKT}/storno`)
    expect(stornoAanroepen[0].body).toEqual({ reden: 'dubbel doorbelast' })
  })

  it('spiegel-taak: eerst doel-gbs PUT, dan spiegel-boeken POST (gaten-scan-flow)', async () => {
    const doelGbsAanroepen: { url: string; body: unknown }[] = []
    const spiegelBoekenAanroepen: string[] = []
    const volgorde: string[] = []
    installFetchMock({
      doelGbsAanroepen,
      spiegelBoekenAanroepen,
      volgorde,
      taken: [spiegelTaak()],
      mappings: [mappingSpiegel()],
      run: run({
        regels: [
          {
            id: REGEL_ID,
            bron_regel_id: BRON_REGEL_ID,
            mapping_id: MAPPING_SPIEGEL,
            percentage: '100.00',
            netto_deel: '205.55',
            // Doel-GB al gekozen (bv. bij de verdeling): de knop is dan direct bruikbaar.
            doel_kosten_ledger_id: LEDGER_ID,
          },
        ],
        previews: [
          {
            mapping_id: MAPPING_SPIEGEL,
            doelentiteit_naam: 'Rubicon Investments B.V.',
            onboarded: true,
            netto_totaal: '205.55',
            provisie_bedrag: '10.28',
            btw_bedrag: '45.32',
            boeking_status: 'spiegel_open',
            boeking_id: null,
          },
        ],
      }),
    })
    renderSectie()
    const gebruiker = userEvent.setup()

    expect(await screen.findByText('spiegel open — taak')).toBeInTheDocument()
    await gebruiker.click(await screen.findByRole('button', { name: 'Spiegel alsnog boeken ✓' }))

    await waitFor(() => expect(spiegelBoekenAanroepen).toHaveLength(1))
    // Volgorde is de kern van de gaten-scan-fix: GB's éérst vastleggen, dan pas boeken.
    expect(volgorde).toEqual(['doel-gbs', 'spiegel-boeken'])
    expect(doelGbsAanroepen[0].url).toContain(`/boekingen/${BOEKING_SPIEGEL}/doel-gbs`)
    expect(doelGbsAanroepen[0].body).toEqual({ regel_gbs: { [REGEL_ID]: LEDGER_ID } })
    expect(spiegelBoekenAanroepen[0]).toContain(`/boekingen/${BOEKING_SPIEGEL}/spiegel-boeken`)
  })
})
