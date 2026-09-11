import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdministratieInstellingenDto, GroepDto } from '../api/types'
import { GroepRij } from './GroepRij'

/** Veld "Groep" op tab Algemeen (blok 8 run 11-09): keuzelijst uit GET /groepen, kiezen = PUT
 * /administraties/{id}/groep, "+ Nieuwe groep…" = inline naam + code-voorstel → POST /groepen → PUT. */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const KG: GroepDto = { id: 'bbbbbbbb-0000-0000-0000-000000000001', naam: 'Kempen groep', code: 'KEMPENGROEP', actief: true, aantal_administraties: 2 }
const OUD: GroepDto = { id: 'bbbbbbbb-0000-0000-0000-000000000002', naam: 'Oude groep', code: 'OUD', actief: false, aantal_administraties: 1 }

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function administratie(overrides: Partial<AdministratieInstellingenDto> = {}): AdministratieInstellingenDto {
  return {
    id: ADMINISTRATIE_ID,
    naam: 'Kempen Facilities B.V.',
    boeken_ingeschakeld: true,
    project_verplicht: false,
    ai_extractie_ingeschakeld: true,
    eigenaar_gebruiker_id: null,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
    uren_meerwerk_ingeschakeld: false,
    uren_dagmax_uren: '12',
    afdelingen_ingeschakeld: false,
    voorraad_ingeschakeld: false,
    mini_voorraad_ingeschakeld: false,
    ...overrides,
  }
}

function installFetchMock(opties: { groepen?: GroepDto[]; aanroepen: { url: string; method: string; body: unknown }[]; putStatus?: number }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const body = init?.body ? JSON.parse(String(init.body)) : undefined
      if (method !== 'GET') opties.aanroepen.push({ url, method, body })
      if (url.startsWith('/groepen') && method === 'GET') return Promise.resolve(jsonResponse({ groepen: opties.groepen ?? [KG, OUD] }))
      if (url === '/groepen' && method === 'POST') {
        return Promise.resolve(jsonResponse({ id: 'cccccccc-0000-0000-0000-000000000003', naam: body.naam, code: body.code, actief: true, aantal_administraties: 0 }, 201))
      }
      if (url.endsWith('/groep') && method === 'PUT') {
        if (opties.putStatus) return Promise.resolve(jsonResponse({ detail: 'Groep Oude groep is gearchiveerd — heractiveer ’m eerst of kies een andere.' }, opties.putStatus))
        const g = [KG, OUD].find((x) => x.id === body.groep_id)
        return Promise.resolve(jsonResponse({ groep_id: body.groep_id, groep_naam: g?.naam ?? (body.groep_id ? 'Nieuw' : null), groep_code: g?.code ?? null }))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('GroepRij', () => {
  it('toont de groepen, kiest er één → PUT met groep_id, "opgeslagen" en onGewijzigd', async () => {
    const aanroepen: { url: string; method: string; body: unknown }[] = []
    installFetchMock({ aanroepen })
    const onGewijzigd = vi.fn()
    render(<GroepRij administratie={administratie()} onGewijzigd={onGewijzigd} />)
    const select = await screen.findByLabelText('Groep van Kempen Facilities B.V.')
    expect(screen.getByRole('option', { name: '— geen groep —' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Kempen groep' })).toBeInTheDocument()
    // Gearchiveerde groepen zijn niet kiesbaar (tenzij het de huidige is).
    expect(screen.queryByRole('option', { name: /Oude groep/ })).not.toBeInTheDocument()

    await userEvent.selectOptions(select, KG.id)
    await waitFor(() => expect(screen.getByText('opgeslagen')).toBeInTheDocument())
    expect(aanroepen).toEqual([{ url: `/administraties/${ADMINISTRATIE_ID}/groep`, method: 'PUT', body: { groep_id: KG.id } }])
    expect(onGewijzigd).toHaveBeenCalledTimes(1)
  })

  it('huidige gearchiveerde groep blijft zichtbaar mét chip; wissen = PUT null', async () => {
    const aanroepen: { url: string; method: string; body: unknown }[] = []
    installFetchMock({ aanroepen })
    render(<GroepRij administratie={administratie({ groep_id: OUD.id, groep_naam: 'Oude groep', groep_actief: false })} />)
    const select = await screen.findByLabelText('Groep van Kempen Facilities B.V.')
    expect((select as HTMLSelectElement).value).toBe(OUD.id)
    expect(screen.getByRole('option', { name: 'Oude groep (gearchiveerd)' })).toBeInTheDocument()
    expect(await screen.findByText('groep gearchiveerd')).toBeInTheDocument()
    await userEvent.selectOptions(select, '')
    await waitFor(() => expect(aanroepen).toEqual([{ url: `/administraties/${ADMINISTRATIE_ID}/groep`, method: 'PUT', body: { groep_id: null } }]))
  })

  it('"+ Nieuwe groep…" opent naam + code-voorstel (bewerkbaar) → POST /groepen → PUT met de nieuwe id', async () => {
    const aanroepen: { url: string; method: string; body: unknown }[] = []
    installFetchMock({ aanroepen, groepen: [] })
    render(<GroepRij administratie={administratie()} />)
    const select = await screen.findByLabelText('Groep van Kempen Facilities B.V.')
    await userEvent.selectOptions(select, '__nieuw__')
    const naam = screen.getByLabelText('Naam nieuwe groep')
    await userEvent.type(naam, 'Kempen groep')
    const code = screen.getByLabelText('Code nieuwe groep') as HTMLInputElement
    expect(code.value).toBe('KEMPENGROEP') // voorstel uit de naam
    await userEvent.clear(code)
    await userEvent.type(code, 'kg') // handmatig: hoofdletters afgedwongen
    expect(code.value).toBe('KG')
    await userEvent.click(screen.getByRole('button', { name: 'Groep aanmaken' }))
    await waitFor(() => expect(aanroepen).toHaveLength(2))
    expect(aanroepen[0]).toEqual({ url: '/groepen', method: 'POST', body: { naam: 'Kempen groep', code: 'KG' } })
    expect(aanroepen[1]).toEqual({ url: `/administraties/${ADMINISTRATIE_ID}/groep`, method: 'PUT', body: { groep_id: 'cccccccc-0000-0000-0000-000000000003' } })
    // Terug in de keuzelijst mét de nieuwe groep geselecteerd.
    const terug = await screen.findByLabelText('Groep van Kempen Facilities B.V.')
    expect((terug as HTMLSelectElement).value).toBe('cccccccc-0000-0000-0000-000000000003')
  })

  it('409 van de server (gearchiveerde groep) is zichtbaar als fout', async () => {
    const aanroepen: { url: string; method: string; body: unknown }[] = []
    installFetchMock({ aanroepen, putStatus: 409 })
    render(<GroepRij administratie={administratie()} />)
    await userEvent.selectOptions(await screen.findByLabelText('Groep van Kempen Facilities B.V.'), KG.id)
    expect(await screen.findByRole('alert')).toHaveTextContent(/gearchiveerd/)
  })
})
