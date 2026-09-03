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

const PROJECT_A = 'aaaa1111-0000-0000-0000-000000000001'
const PROJECT_B = 'aaaa1111-0000-0000-0000-000000000002'
const SLEUTEL = 'ffff0000-0000-0000-0000-000000000009'

interface Opties {
  toggleAan?: boolean
  bestaandeRun?: DoorbelastingRunDto | null
  /** Doel-projecten achter de mapping (25-08, deel 2 punt 2); projectVerplicht = doel heeft projectplicht. */
  projectVerplicht?: boolean
  /** Mapping mét onboarded doel (nodig voor project-/GB-keuze); default false zoals de oudere tests. */
  doelOnboarded?: boolean
  verdelingPuts?: unknown[]
  sleutelPosts?: { url: string; body: unknown }[]
  /** Server-antwoord op de default-aan-vraag: 'maakt' (nieuwe klaargezette run) of 'niets' (204 —
   * de mens had het vinkje al eens uitgezet). */
  defaultAan?: 'maakt' | 'niets'
  aanroepen?: { url: string; method: string }[]
  /** Doel-projectenlijst is leeg tot de sync-trigger van de doel-administratie is aangeroepen (v2 lege stand). */
  projectenLeegTotSync?: boolean
}

function installFetchMock({
  toggleAan = true,
  bestaandeRun = null,
  defaultAan = 'maakt',
  aanroepen,
  projectVerplicht = false,
  doelOnboarded = false,
  verdelingPuts,
  sleutelPosts,
  projectenLeegTotSync = false,
}: Opties) {
  let huidigeRun: DoorbelastingRunDto | null = bestaandeRun
  let projectenGesynct = !projectenLeegTotSync
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      aanroepen?.push({ url, method })
      if (url.endsWith('/administraties/doel-1/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [] }))
      if (url.endsWith('/administraties/doel-1/sync/projects') && method === 'POST') {
        projectenGesynct = true
        return Promise.resolve(jsonResponse({ aangemaakt: 2, bijgewerkt: 0, verdwenen: 0 }))
      }
      if (url.endsWith(`/mappings/${MAPPING}/projecten`)) {
        if (!projectenGesynct) {
          return Promise.resolve(jsonResponse({ doel_administratie_id: 'doel-1', project_verplicht: projectVerplicht, projecten: [] }))
        }
        return Promise.resolve(
          jsonResponse({
            doel_administratie_id: 'doel-1',
            project_verplicht: projectVerplicht,
            projecten: [
              { id: PROJECT_A, naam: 'Pand A', is_actief: true, contract_m2: '100.00' },
              { id: PROJECT_B, naam: 'Pand B', is_actief: true, contract_m2: null },
            ],
          }),
        )
      }
      if (url.endsWith('/verdeelsleutels') && method === 'GET') {
        return Promise.resolve(
          jsonResponse([
            { id: SLEUTEL, naam: 'Alle panden', versie: 2, actief: true, definitie: { doelen: [] }, aangemaakt_op: '2026-08-25T09:00:00Z' },
          ]),
        )
      }
      if (url.endsWith('/verdeelsleutels') && method === 'POST') {
        const body = init?.body ? JSON.parse(String(init.body)) : null
        sleutelPosts?.push({ url, body })
        return Promise.resolve(jsonResponse({ id: 'nieuw', naam: body.naam, versie: 1, actief: true, definitie: { doelen: body.doelen }, aangemaakt_op: '2026-08-25T10:00:00Z' }))
      }
      if (url.endsWith(`/verdeelsleutels/${SLEUTEL}/toepassen`) && method === 'POST') {
        sleutelPosts?.push({ url, body: null })
        huidigeRun = { ...RUN_MET_VERDELING, verdeelsleutel: { id: SLEUTEL, naam: 'Alle panden', versie: 2, toegepast_op: '2026-08-25T10:00:00Z' } }
        return Promise.resolve(jsonResponse(huidigeRun))
      }
      if (url.endsWith('/verdeling') && method === 'PUT') {
        const body = init?.body ? JSON.parse(String(init.body)) : null
        verdelingPuts?.push(body)
        huidigeRun = RUN_MET_VERDELING
        return Promise.resolve(jsonResponse(huidigeRun))
      }
      if (url.endsWith('/doorbelasting-instelling')) return Promise.resolve(jsonResponse({ ingeschakeld: toggleAan }))
      if (url.endsWith(`/documenten/${DOC}/run/default`) && method === 'POST') {
        if (defaultAan === 'niets' || huidigeRun) {
          return Promise.resolve(huidigeRun ? jsonResponse(huidigeRun) : new Response(null, { status: 204 }))
        }
        huidigeRun = run()
        return Promise.resolve(jsonResponse(huidigeRun))
      }
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
              doel_administratie_id: doelOnboarded ? 'doel-1' : null,
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

  it('default AAN (besluit 25-08, deel 2 punt 5): zonder eerdere run staat het vinkje standaard aan via de default-route; leeg = knop geblokkeerd', async () => {
    const aanroepen: { url: string; method: string }[] = []
    const meldingen: (KlaargezetteDoorbelasting | null)[] = []
    installFetchMock({ aanroepen })
    renderBlok('te_controleren', (s) => meldingen.push(s))

    const vinkje = await screen.findByLabelText('Doorbelasten na boeken')
    await waitFor(() => expect(vinkje).toBeChecked())
    expect(aanroepen.some((a) => a.method === 'POST' && a.url.endsWith(`/documenten/${DOC}/run/default`))).toBe(true)
    // Géén gewone POST (dat is de expliciete klik) — de default-route is de enige aanmaak.
    expect(aanroepen.some((a) => a.method === 'POST' && a.url.endsWith(`/documenten/${DOC}/run`))).toBe(false)
    await waitFor(() => expect(screen.getByText('klaargezet')).toBeInTheDocument())
    // Verdeel-UI inline mét de bron-regel uit het boekvoorstel
    expect(screen.getByText('Steigermateriaal')).toBeInTheDocument()
    // Aanvulling blok D 03-09: zelfde component als "+ Regel toevoegen" (btn secondary), nooit een kale linkbtn
    expect(screen.getByRole('button', { name: '+ Doelentiteit' })).toHaveClass('btn', 'secondary')
    expect(screen.getByRole('button', { name: 'Verdeelsleutel' })).toHaveClass('btn', 'secondary')
    // Nog niets verdeeld → de boekknop-poort meldt geblokkeerd mét reden (A2)
    await waitFor(() => expect(meldingen.at(-1)?.geblokkeerd).toBe(true))
    expect(meldingen.at(-1)?.reden).toMatch(/nog geen verdeling/)
  })

  it('eerder uitgevinkt (server 204 op de default-route): vinkje blijft uit; aanvinken is de expliciete POST', async () => {
    const aanroepen: { url: string; method: string }[] = []
    const meldingen: (KlaargezetteDoorbelasting | null)[] = []
    installFetchMock({ aanroepen, defaultAan: 'niets' })
    renderBlok('te_controleren', (s) => meldingen.push(s))

    const vinkje = await screen.findByLabelText('Doorbelasten na boeken')
    await waitFor(() => expect(vinkje).toBeEnabled())
    expect(vinkje).not.toBeChecked()
    expect(aanroepen.some((a) => a.method === 'POST' && a.url.endsWith(`/documenten/${DOC}/run/default`))).toBe(true)
    expect(meldingen.at(-1)).toBeNull()

    await userEvent.click(vinkje)
    await waitFor(() => expect(screen.getByText('klaargezet')).toBeInTheDocument())
    expect(aanroepen.some((a) => a.method === 'POST' && a.url.endsWith(`/documenten/${DOC}/run`))).toBe(true)
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

  it('doorbelasting × projecten (deel 2 punt 2): "alle actieve projecten" + verdeelbasis gaan mee in de opslag; ontbrekende m² wordt benoemd', async () => {
    const verdelingPuts: unknown[] = []
    installFetchMock({ bestaandeRun: RUN_MET_VERDELING, verdelingPuts, doelOnboarded: true })
    renderBlok('klaar_om_te_boeken')
    await waitFor(() => expect(screen.getByLabelText('Doorbelasten na boeken')).toBeChecked())

    await userEvent.click(await screen.findByRole('button', { name: 'alle actieve projecten' }))
    expect(screen.getByText('2 gekozen')).toBeInTheDocument()
    // default m² → Pand B zonder m² wordt benoemd (nooit gokken)
    expect(screen.getByText(/geen m² bekend: Pand B/)).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('gelijk per object'))
    expect(screen.queryByText(/geen m² bekend/)).not.toBeInTheDocument()

    // v2: geen opslaanknop — een complete verdeling gaat automatisch naar de server
    await waitFor(() => expect(verdelingPuts).toHaveLength(1), { timeout: 3000 })
    const body = verdelingPuts[0] as { regels: { project_ids: string[]; verdeelbasis: string | null }[] }
    expect(body.regels[0].project_ids).toEqual([PROJECT_A, PROJECT_B])
    expect(body.regels[0].verdeelbasis).toBe('gelijk')
  })

  it('project verplicht in het doel: chip zichtbaar en opslaan zonder project wordt geweigerd', async () => {
    const verdelingPuts: unknown[] = []
    installFetchMock({ bestaandeRun: RUN_MET_VERDELING, projectVerplicht: true, verdelingPuts, doelOnboarded: true })
    renderBlok('klaar_om_te_boeken')
    expect(await screen.findByText('project verplicht')).toBeInTheDocument()
    // Zonder project: de blokkeer-reden staat onder de tabel en er wordt niets (automatisch) opgeslagen
    await userEvent.clear(screen.getByLabelText('Percentage voor Steigermateriaal'))
    await userEvent.type(screen.getByLabelText('Percentage voor Steigermateriaal'), '100')
    expect(await screen.findByTestId('verdeling-blokkade')).toHaveTextContent(/Project verplicht in Veldhoven Recreatie B.V./)
    await new Promise((r) => setTimeout(r, 900))
    expect(verdelingPuts).toHaveLength(0)
  })

  it('verdeelsleutel: toepassen is één klik (POST) en de run toont sleutel + versie; opslaan als sleutel bewaart "alle actieve" dynamisch', async () => {
    const sleutelPosts: { url: string; body: unknown }[] = []
    installFetchMock({ bestaandeRun: RUN_MET_VERDELING, sleutelPosts, doelOnboarded: true })
    renderBlok('klaar_om_te_boeken')
    await waitFor(() => expect(screen.getByLabelText('Doorbelasten na boeken')).toBeChecked())

    // v2: één menu "Verdeelsleutel ▾" met toepassen per sleutel en opslaan-als
    await userEvent.click(await screen.findByRole('button', { name: 'Verdeelsleutel' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Toepassen: Alle panden (v2)' }))
    await waitFor(() => expect(sleutelPosts.some((p) => p.url.endsWith(`/verdeelsleutels/${SLEUTEL}/toepassen`))).toBe(true))
    expect(await screen.findByText(/toegepast op/)).toBeInTheDocument()
    expect(screen.getByText('Alle panden', { selector: 'b' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'alle actieve projecten' }))
    await userEvent.click(screen.getByRole('button', { name: 'Verdeelsleutel' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: 'Opslaan als sleutel…' }))
    await userEvent.type(screen.getByLabelText('Naam nieuwe verdeelsleutel'), 'Nieuwe sleutel')
    await userEvent.click(screen.getByRole('button', { name: 'Opslaan als sleutel' }))
    await waitFor(() => expect(sleutelPosts.some((p) => p.url.endsWith('/verdeelsleutels') && p.body)).toBe(true))
    const post = sleutelPosts.find((p) => p.url.endsWith('/verdeelsleutels') && p.body)!.body as {
      naam: string
      doelen: { mapping_id: string; projecten: unknown; verdeelbasis: string | null }[]
    }
    expect(post.naam).toBe('Nieuwe sleutel')
    expect(post.doelen[0]).toMatchObject({ mapping_id: MAPPING, projecten: 'alle_actief', verdeelbasis: 'm2' })
    expect(await screen.findByText(/opgeslagen als versie 1/)).toBeInTheDocument()
  })

  it('%-parse-bugfix 02-09: "1110000" of geplakt "11.100,00" wordt geweigerd mét uitleg, nooit doorgerekend; rest-prefill is afgerond', async () => {
    const verdelingPuts: unknown[] = []
    installFetchMock({ bestaandeRun: RUN_MET_VERDELING, verdelingPuts, doelOnboarded: true })
    renderBlok('klaar_om_te_boeken')
    await waitFor(() => expect(screen.getByLabelText('Doorbelasten na boeken')).toBeChecked())

    const veld = screen.getByLabelText('Percentage voor Steigermateriaal')
    await userEvent.clear(veld)
    await userEvent.type(veld, '1110000')
    expect(screen.getAllByText(/geen geldig percentage/).length).toBeGreaterThan(0)
    expect(veld).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByTestId('verdeling-blokkade')).toHaveTextContent(/geen geldig percentage/)

    await userEvent.clear(veld)
    await userEvent.paste('11.100,00')
    expect(screen.getAllByText(/geen geldig percentage/).length).toBeGreaterThan(0)

    // Rest-prefill: 88,9 gevuld → nieuwe rij krijgt exact "11,1" (niet 11,099999999999994)
    await userEvent.clear(veld)
    await userEvent.type(veld, '88,9')
    await userEvent.click(screen.getByRole('button', { name: '+ Doelentiteit' }))
    const velden = screen.getAllByLabelText('Percentage voor Steigermateriaal')
    expect(velden[1]).toHaveValue('11,1')
    // % ↔ bedrag live gekoppeld: bedrag typen zet het percentage (€ 60 van € 100 = 60%)
    const bedragVelden = screen.getAllByLabelText('Bedrag voor Steigermateriaal')
    await userEvent.clear(bedragVelden[1])
    await userEvent.type(bedragVelden[1], '60')
    expect(screen.getAllByLabelText('Percentage voor Steigermateriaal')[1]).toHaveValue('60')
    expect(verdelingPuts).toHaveLength(0)
  })

  it('lege projectstand is een actie (v2 ④): "Nu synchroniseren" triggert de projecten-sync van de doel-administratie en herlaadt de lijst', async () => {
    const aanroepen: { url: string; method: string }[] = []
    installFetchMock({ bestaandeRun: RUN_MET_VERDELING, doelOnboarded: true, aanroepen, projectenLeegTotSync: true })
    renderBlok('klaar_om_te_boeken')
    expect(await screen.findByTestId('projecten-leeg')).toHaveTextContent('nog geen projecten gesynchroniseerd')
    await userEvent.click(screen.getByRole('button', { name: 'Nu synchroniseren' }))
    await waitFor(() => expect(aanroepen.some((a) => a.method === 'POST' && a.url.endsWith('/administraties/doel-1/sync/projects'))).toBe(true))
    // ná de sync komt de lijst terug en verdwijnt de lege stand
    expect(await screen.findByRole('button', { name: 'alle actieve projecten' })).toBeInTheDocument()
    expect(screen.queryByTestId('projecten-leeg')).not.toBeInTheDocument()
  })

  it('bij de klant (ter_accordering) is de verdeling alleen-lezen', async () => {
    installFetchMock({ bestaandeRun: RUN_MET_VERDELING })
    renderBlok('ter_accordering')
    await waitFor(() => expect(screen.getByText('bij klant — alleen-lezen')).toBeInTheDocument())
    expect(screen.getByLabelText('Doorbelasten na boeken')).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Verdeelsleutel' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '+ Doelentiteit' })).not.toBeInTheDocument()
  })
})
