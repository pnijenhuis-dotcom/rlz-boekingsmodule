import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isActivumAanmakenMislukt, OpnieuwAanmakenActie } from './OpnieuwAanmakenActie'
import type { BevindingDto } from './reconciliatieApi'

// BUG 24-09 (BLOw 23-09): activum niet aangemaakt ná een mens-klik = actie-bevinding mét "Opnieuw aanmaken" op de rij —
// dezelfde kaart-route zonder body (server vult de afschrijvingsrekening voor); 422 = de letterlijke zin van de server.

function bevinding(overrides: Partial<BevindingDto> = {}): BevindingDto {
  return {
    id: 'bev-1',
    run_id: 'run-1',
    blok: 'activa',
    soort: 'afwijking',
    administratie_id: 'adm-1',
    administratie_naam: 'BLOw B.V',
    vingerafdruk: 'activa:adm-1:activum_aanmaken_mislukt_mens:k1',
    tekst: "AFWIJKING administratie=adm-1 soort=activum_aanmaken_mislukt_mens: activum 'Kantoorinventaris' € 935.00 niet aangemaakt ná een mens-klik: …",
    titel: 'Activum niet aangemaakt ná uw klik · Kantoorinventaris · BLOw B.V',
    wat: "Iemand koos 'Activum aanmaken' …",
    doe: "Klik 'Opnieuw aanmaken' op deze rij …",
    details: [],
    sinds: '2026-09-24T04:30:00Z',
    nieuw: true,
    acceptatie: null,
    gezien: null,
    detail: {
      afwijking_soort: 'activum_aanmaken_mislukt_mens',
      herkomst: 'mens',
      document_id: 'doc-1',
      regel_volgnummer: 1,
      koppeling_id: 'k1',
      reden: 'geen afschrijvingsrekening — kies op de kaart of stel in onder Instellingen › Activa',
    },
    doel_pad: '/?administratie=adm-1&document=doc-1',
    ...overrides,
  } as BevindingDto
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function voorstelMet(status: 'aangemaakt' | 'mislukt' | 'gepland', reden: string | null = null) {
  return {
    administratie_id: 'adm-1',
    document_id: 'doc-1',
    document_geboekt: true,
    grens: '450.00',
    grens_bron: 'rlz',
    automatisch_ingeschakeld: false,
    register_leesbaar: true,
    register_fout: null,
    kandidaten: [
      {
        regel_volgnummer: 1,
        koppeling: { id: 'k1', status, herkomst: 'mens', rlz_fixed_asset_id: status === 'aangemaakt' ? 'fa-1' : null, rlz_receipt_number: status === 'aangemaakt' ? '3' : null, reden, door: null, gewijzigd_op: null },
      },
    ],
    onder_grens: [],
    afschrijving_ledger_opties: [],
  }
}

describe('OpnieuwAanmakenActie (BUG 24-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('herkent alleen activa-afwijkingen activum_aanmaken_mislukt(_mens) mét document, regel en administratie', () => {
    expect(isActivumAanmakenMislukt(bevinding())).toBe(true)
    expect(isActivumAanmakenMislukt(bevinding({ detail: { ...bevinding().detail, afwijking_soort: 'activum_aanmaken_mislukt' } }))).toBe(true)
    expect(isActivumAanmakenMislukt(bevinding({ detail: { ...bevinding().detail, afwijking_soort: 'activum_zonder_boeking' } }))).toBe(false)
    expect(isActivumAanmakenMislukt(bevinding({ blok: 'documenten' }))).toBe(false)
    expect(isActivumAanmakenMislukt(bevinding({ administratie_id: null }))).toBe(false)
    expect(isActivumAanmakenMislukt(bevinding({ detail: { afwijking_soort: 'activum_aanmaken_mislukt_mens', document_id: 'doc-1' } }))).toBe(false)
  })

  it('klik = POST op de kaart-route zonder afschrijvingsrekening in de body; aangemaakt → melding mét RLZ-nummer', async () => {
    const aanroepen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        aanroepen.push(`${init?.method ?? 'GET'} ${url} ${init?.body ?? ''}`)
        return Promise.resolve(jsonResponse(voorstelMet('aangemaakt')))
      }),
    )
    const gelukt = vi.fn()
    render(<OpnieuwAanmakenActie bevinding={bevinding()} onGelukt={gelukt} />)
    await userEvent.click(screen.getByRole('button', { name: /Activum opnieuw aanmaken \(BLOw B.V\)/ }))
    await waitFor(() => expect(gelukt).toHaveBeenCalled())
    expect(aanroepen).toEqual(['POST /administraties/adm-1/documenten/doc-1/activa-voorstel/1/aanmaken {}'])
    expect(gelukt.mock.calls[0][0]).toBe('Activum aangemaakt in Reeleezee (nr 3).')
    expect(gelukt.mock.calls[0][1]).toBe('ok')
    expect(screen.getByText('Activum aangemaakt in Reeleezee (nr 3).')).toBeInTheDocument()
  })

  it('422 "Kies een afschrijvingsrekening …" staat letterlijk op de rij (de mens kiest op het controlescherm)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(jsonResponse({ detail: 'Kies een afschrijvingsrekening — RLZ vereist er één per activum' }, 422))))
    const gelukt = vi.fn()
    render(<OpnieuwAanmakenActie bevinding={bevinding()} onGelukt={gelukt} />)
    await userEvent.click(screen.getByRole('button', { name: /Activum opnieuw aanmaken/ }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Kies een afschrijvingsrekening — RLZ vereist er één per activum'))
    expect(gelukt).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: /Activum opnieuw aanmaken/ })).toBeEnabled()
  })

  it('RLZ weigert opnieuw (koppeling blijft mislukt) → de nieuwe reden zichtbaar, nooit stil', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(jsonResponse(voorstelMet('mislukt', 'aanmaken in Reeleezee nog niet mogelijk — wordt onderzocht (…)')))),
    )
    render(<OpnieuwAanmakenActie bevinding={bevinding()} onGelukt={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /Activum opnieuw aanmaken/ }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/nog niet gelukt: aanmaken in Reeleezee nog niet mogelijk — wordt onderzocht/))
  })
})
