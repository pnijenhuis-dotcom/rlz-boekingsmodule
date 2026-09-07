// Pro-rato-periode "heel jaar" (D4 07-09, mockup-notitie ⑩): keuzelijst mét beide jaaropties en dekkingslabel,
// verdeling verstuurt de periode-code "JJJJ", bevroren jaarverdeling toont het serverlabel.
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProjectverdelingDto } from '../api/types'
import { isJaarPeriode, periodeLabel } from './HerverdeelDialoog'
import { ProjectverdelingBlok, defaultPeriode, periodeOpties } from './ProjectverdelingBlok'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOC = 'bbbbbbbb-0000-0000-0000-000000000002'
const EINDHOVEN = 'cccccccc-0000-0000-0000-000000000011'
const TILBURG = 'cccccccc-0000-0000-0000-000000000012'
const VENLO = 'cccccccc-0000-0000-0000-000000000013'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const MAAND_VOORSTEL: ProjectverdelingDto = {
  document_id: DOC,
  status: 'voorstel',
  opgeslagen: true,
  prefill: false,
  basisbedrag: '2000.00',
  vaste_regels: [],
  pro_rato: true,
  pro_rato_periode: '2026-07',
  pro_rato_periode_label: 'juli 2026',
  pro_rato_bedrag: '2000.00',
  delen: [
    { project_id: EINDHOVEN, project_naam: '26120 Eindhoven (BAM)', wijze: 'pro_rato', bedrag: '1200.00', aandeel: '0.600000', omzet: '6000.00' },
    { project_id: TILBURG, project_naam: '26127 Tilburg (Heijmans)', wijze: 'pro_rato', bedrag: '500.00', aandeel: '0.250000', omzet: '2500.00' },
    { project_id: VENLO, project_naam: '26131 Venlo (Dura)', wijze: 'pro_rato', bedrag: '300.00', aandeel: '0.150000', omzet: '1500.00' },
  ],
  omzetstanden: [],
  aantal_projecten_met_omzet: 3,
  omzet_cache_leeg: false,
  compleet: true,
  blokkade: null,
  boek_cyclus: 0,
  hercontrole: null,
}

const JAAR_VOORSTEL: ProjectverdelingDto = {
  ...MAAND_VOORSTEL,
  pro_rato_periode: '2025',
  pro_rato_periode_label: '2025',
}

const JAAR_GEBOEKT: ProjectverdelingDto = {
  ...MAAND_VOORSTEL,
  status: 'geboekt',
  pro_rato_periode: '2026',
  pro_rato_periode_label: '2026 (t/m juli)',
}

function installFetchMock(get: ProjectverdelingDto, puts: unknown[], putAntwoord: ProjectverdelingDto = get) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith(`/administraties/${ADM}/projecten`)) {
        return Promise.resolve(
          jsonResponse({
            projecten: [
              { id: EINDHOVEN, naam: '26120 Eindhoven (BAM)' },
              { id: TILBURG, naam: '26127 Tilburg (Heijmans)' },
              { id: VENLO, naam: '26131 Venlo (Dura)' },
            ],
          }),
        )
      }
      if (url.endsWith('/projectverdeling') && method === 'PUT') {
        puts.push(init?.body ? JSON.parse(String(init.body)) : null)
        return Promise.resolve(jsonResponse(putAntwoord))
      }
      if (url.endsWith('/projectverdeling')) return Promise.resolve(jsonResponse(get))
      return Promise.resolve(jsonResponse({ detail: `onbekend pad ${url}` }, 404))
    }),
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('pro-rato-periode heel jaar (D4)', () => {
  it('periodeLabel: maandcode, oude datumvorm en jaarcode mét dekking t/m de laatste afgesloten maand', () => {
    expect(periodeLabel('2026-07')).toBe('juli 2026')
    expect(periodeLabel('2026-07-01')).toBe('juli 2026')
    expect(periodeLabel('2026', new Date(2026, 8, 15))).toBe('2026 (t/m augustus)')
    expect(periodeLabel('2025', new Date(2026, 8, 15))).toBe('2025')
    expect(periodeLabel('2026', new Date(2026, 0, 15))).toBe('2026 (nog geen afgesloten maand)')
    expect(periodeLabel(null)).toBe('')
    expect(isJaarPeriode('2026')).toBe(true)
    expect(isJaarPeriode('2026-07')).toBe(false)
    expect(isJaarPeriode(null)).toBe(false)
    expect(defaultPeriode(new Date(2026, 8, 15))).toBe('2026-08')
  })

  it('keuzelijst: 12 maanden + lopend jaar (t/m laatste afgesloten maand) + vorig jaar; in januari geen lopend jaar', () => {
    const opties = periodeOpties(new Date(2026, 8, 15))
    expect(opties).toHaveLength(14)
    expect(opties[0]).toEqual({ code: '2026-08', label: 'pro rato augustus 2026 ▾' })
    expect(opties.find((o) => o.code === '2026')?.label).toBe('pro rato omzet 2026 (t/m augustus) ▾')
    expect(opties.find((o) => o.code === '2025')?.label).toBe('pro rato omzet 2025 ▾')
    const januari = periodeOpties(new Date(2026, 0, 15))
    expect(januari).toHaveLength(13)
    expect(januari.map((o) => o.code)).not.toContain('2026')
    expect(januari.map((o) => o.code)).toContain('2025')
  })

  it('jaaroptie kiezen verstuurt periode "JJJJ" naar de server (auto-opslaan)', async () => {
    const puts: unknown[] = []
    installFetchMock(MAAND_VOORSTEL, puts, JAAR_VOORSTEL)
    render(<ProjectverdelingBlok administratieId={ADM} documentId={DOC} status="te_controleren" soort="inkoopfactuur" boekvoorstelVersie={0} />)
    await screen.findByText(/Restant — pro rato omzet juli 2026/)
    const select = screen.getByLabelText('Pro rato omzetperiode') as HTMLSelectElement
    const nu = new Date()
    const vorigJaar = String(nu.getFullYear() - 1)
    expect(within(select).getByRole('option', { name: `pro rato omzet ${vorigJaar} ▾` })).toBeInTheDocument()
    if (nu.getMonth() > 0) {
      expect(within(select).getByRole('option', { name: new RegExp(`pro rato omzet ${nu.getFullYear()} \\(t/m `) })).toBeInTheDocument()
    }
    await userEvent.selectOptions(select, vorigJaar)
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 })
    expect(puts[puts.length - 1]).toEqual({ vaste_regels: [], pro_rato_periode: vorigJaar })
    // Serverantwoord (jaar 2025) wordt de getoonde stand, mét de jaar-hint.
    expect(await screen.findByText(/Restant — pro rato omzet 2025/)).toBeInTheDocument()
    expect(screen.getByText(/alleen afgesloten maanden/)).toBeInTheDocument()
  })

  it('bevroren jaarverdeling toont het serverlabel mét dekking op het boekmoment', async () => {
    installFetchMock(JAAR_GEBOEKT, [])
    render(<ProjectverdelingBlok administratieId={ADM} documentId={DOC} status="geboekt" soort="inkoopfactuur" boekvoorstelVersie={0} />)
    expect(await screen.findByText(/Restant — pro rato omzet 2026 \(t\/m juli\)/)).toBeInTheDocument()
    expect(screen.getByText(/alleen afgesloten maanden/)).toBeInTheDocument()
  })
})
