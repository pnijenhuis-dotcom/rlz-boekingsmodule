import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DoorbelastingRunDto } from '../api/types'
import { DoorbelastenNaBoeken, type KlaargezetteDoorbelasting } from './DoorbelastenNaBoeken'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOC = 'bbbbbbbb-0000-0000-0000-000000000002'
const RUN = 'cccccccc-0000-0000-0000-000000000003'
const MAPPING = 'dddddddd-0000-0000-0000-000000000004'
const REGEL = 'eeeeeeee-0000-0000-0000-000000000005'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function run(overrides: Partial<DoorbelastingRunDto> = {}): DoorbelastingRunDto {
  return {
    id: RUN,
    document_id: DOC,
    status: 'klaargezet',
    laatste_fout: null,
    regels: [],
    previews: [],
    checks: { geblokkeerd: true, resultaten: [{ naam: 'Verdeling per regel = 100%', ok: false, melding: 'Geen verdeelregels' }] },
    ...overrides,
  }
}

const RUN_MET_VERDELING = run({
  regels: [{ id: 'r1', bron_regel_id: REGEL, mapping_id: MAPPING, percentage: '100.00', netto_deel: '100.00', doel_kosten_ledger_id: 'gb1' }],
  previews: [
    {
      mapping_id: MAPPING,
      doelentiteit_naam: 'Veldhoven Recreatie B.V.',
      onboarded: true,
      netto_totaal: '100.00',
      provisie_bedrag: '5.00',
      btw_bedrag: '22.05',
      boeking_status: null,
      boeking_id: null,
    },
  ],
  checks: { geblokkeerd: false, resultaten: [{ naam: 'Verdeling per regel = 100%', ok: true, melding: 'OK' }] },
})

interface Opties {
  toggleAan?: boolean
  bestaandeRun?: DoorbelastingRunDto | null
  aanroepen?: { url: string; method: string }[]
}

function installFetchMock({ toggleAan = true, bestaandeRun = null, aanroepen }: Opties) {
  let huidigeRun: DoorbelastingRunDto | null = bestaandeRun
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      aanroepen?.push({ url, method })
      if (url.endsWith('/doorbelasting-instelling')) return Promise.resolve(jsonResponse({ ingeschakeld: toggleAan }))
      if (url.endsWith(`/documenten/${DOC}/run`) && method === 'GET') {
        return Promise.resolve(huidigeRun ? jsonResponse(huidigeRun) : new Response(null, { status: 404 }))
      }
      if (url.endsWith(`/documenten/${DOC}/run`) && method === 'POST') {
        huidigeRun = run()
        return Promise.resolve(jsonResponse(huidigeRun))
      }
      if (url.endsWith('/vervallen') && method === 'POST') {
        huidigeRun = null
        return Promise.resolve(jsonResponse(run({ status: 'vervallen' })))
      }
      if (url.endsWith('/mappings')) {
        return Promise.resolve(
          jsonResponse([
            {
              id: MAPPING,
              doelentiteit_naam: 'Veldhoven Recreatie B.V.',
              doel_customer_guid: 'x',
              doel_administratie_id: null,
              intercompany: true,
              provisie_kosten_ledger_id: null,
              laatste_kosten_ledger_id: null,
              actief: true,
            },
          ]),
        )
      }
      if (url.endsWith('/boekvoorstel')) {
        return Promise.resolve(
          jsonResponse({
            regels: [{ id: REGEL, omschrijving: 'Steigermateriaal', netto_bedrag: '100.00' }],
          }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderBlok(status = 'te_controleren', onKlaargezet: (s: KlaargezetteDoorbelasting | null) => void = () => {}) {
  return render(
    <MemoryRouter>
      <DoorbelastenNaBoeken
        administratieId={ADM}
        documentId={DOC}
        status={status}
        soort="inkoopfactuur"
        boekvoorstelVersie={0}
        onKlaargezet={onKlaargezet}
      />
    </MemoryRouter>,
  )
}

describe('DoorbelastenNaBoeken (besluit Peter 25-08, punt A)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont niets zonder doorbelasting-toggle of op een geboekt document', async () => {
    installFetchMock({ toggleAan: false })
    renderBlok()
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled())
    expect(screen.queryByText('Doorbelasten na boeken')).not.toBeInTheDocument()
    vi.unstubAllGlobals()
    installFetchMock({ toggleAan: true })
    renderBlok('geboekt')
    expect(screen.queryByText('Doorbelasten na boeken')).not.toBeInTheDocument()
  })

  it('aanvinken start een klaargezette run (POST) en toont de verdeel-UI inline; leeg = knop geblokkeerd', async () => {
    const aanroepen: { url: string; method: string }[] = []
    const meldingen: (KlaargezetteDoorbelasting | null)[] = []
    installFetchMock({ aanroepen })
    renderBlok('te_controleren', (s) => meldingen.push(s))

    const vinkje = await screen.findByLabelText('Doorbelasten na boeken')
    await waitFor(() => expect(vinkje).toBeEnabled())
    expect(vinkje).not.toBeChecked()
    expect(meldingen.at(-1)).toBeNull()

    await userEvent.click(vinkje)
    await waitFor(() => expect(screen.getByText('klaargezet')).toBeInTheDocument())
    expect(aanroepen.some((a) => a.method === 'POST' && a.url.endsWith(`/documenten/${DOC}/run`))).toBe(true)
    // Verdeel-UI inline mét de bron-regel uit het boekvoorstel
    expect(screen.getByText('Steigermateriaal')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ Doelentiteit toevoegen' })).toBeInTheDocument()
    // Nog niets verdeeld → de boekknop-poort meldt geblokkeerd mét reden (A2)
    await waitFor(() => expect(meldingen.at(-1)?.geblokkeerd).toBe(true))
    expect(meldingen.at(-1)?.reden).toMatch(/nog geen verdeling/)
  })

  it('bestaande klaargezette run met groene checks meldt de boekknop "groen"; uitvinken laat vervallen na bevestiging', async () => {
    const aanroepen: { url: string; method: string }[] = []
    const meldingen: (KlaargezetteDoorbelasting | null)[] = []
    installFetchMock({ bestaandeRun: RUN_MET_VERDELING, aanroepen })
    renderBlok('klaar_om_te_boeken', (s) => meldingen.push(s))

    await waitFor(() => expect(screen.getByLabelText('Doorbelasten na boeken')).toBeChecked())
    expect(screen.getByText('Veldhoven Recreatie B.V.', { selector: 'b' })).toBeInTheDocument()
    await waitFor(() => expect(meldingen.at(-1)).toEqual({ runId: RUN, geblokkeerd: false, reden: null }))

    await userEvent.click(screen.getByLabelText('Doorbelasten na boeken'))
    expect(await screen.findByText('Doorbelasten na boeken uitzetten?')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Bevestigen' }))
    await waitFor(() => expect(screen.getByLabelText('Doorbelasten na boeken')).not.toBeChecked())
    expect(aanroepen.some((a) => a.method === 'POST' && a.url.endsWith(`/runs/${RUN}/vervallen`))).toBe(true)
    await waitFor(() => expect(meldingen.at(-1)).toBeNull())
  })

  it('bij de klant (ter_accordering) is de verdeling alleen-lezen', async () => {
    installFetchMock({ bestaandeRun: RUN_MET_VERDELING })
    renderBlok('ter_accordering')
    await waitFor(() => expect(screen.getByText('bij klant — alleen-lezen')).toBeInTheDocument())
    expect(screen.getByLabelText('Doorbelasten na boeken')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Verdeling opslaan' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+ Doelentiteit toevoegen' })).not.toBeInTheDocument()
  })
})
