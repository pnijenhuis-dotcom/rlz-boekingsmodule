import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ActivaInstellingDto } from '../activa/activaApi'
import { ActivaInstellingenBlok } from './ActivaInstellingenBlok'

/** Activa / MVA-blok (fase 1, akkoord Peter 21-09, migratie 0168): opt-in default UIT, grens mét RLZ-hint (bron wint),
 * termijn + afschrijvingsrekening per categorie, activarekeningen, registerstand, tellers; PUT = de volledige stand. */
const AID = 'aaaaaaaa-0000-0000-0000-000000000001'

function stand(overrides: Partial<ActivaInstellingDto> = {}): ActivaInstellingDto {
  return {
    automatisch_aanmaken_ingeschakeld: false,
    activeringsgrens: '450.00',
    grens_rlz: '450.00',
    grens_rlz_gelezen_op: '2026-09-21T06:30:00Z',
    effectieve_grens: '450.00',
    grens_bron: 'rlz',
    termijnen: { computers_software: 36 },
    afschrijving_ledgers: { inventaris: 'gb-0108' },
    register_leesbaar: false,
    register_geprobeerd_op: '2026-09-21T06:30:00Z',
    register_fout: 'HTTP 403 op FixedAssets',
    categorieen: [
      { code: 'inventaris', label: 'Inventaris', default_maanden: 60 },
      { code: 'computers_software', label: 'Computers / software', default_maanden: 36 },
      { code: 'steigermateriaal', label: 'Steigermateriaal', default_maanden: 60 },
    ],
    mva_rekeningen: [{ ledger_id: 'gb-0107', code: '0107', naam: 'Inventaris' }],
    afschrijving_ledger_opties: [
      { ledger_id: 'gb-0108', code: '0108', naam: 'Afschrijving inventaris' },
      { ledger_id: 'gb-0118', code: '0118', naam: 'Afschrijving machines' },
    ],
    koppelingen_tellers: { gepland: 1, aangemaakt: 2, overgeslagen: 0, mislukt: 1, beoordelen: 0 },
    ...overrides,
  }
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

describe('ActivaInstellingenBlok', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de stand: schakelaar uit, grens mét Reeleezee-hint (bron wint), categorieën mét termijn en rekening, registerstand 403, tellers', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json(stand()))))
    render(<ActivaInstellingenBlok administratieId={AID} naam="Pilates Bloom B.V." />)
    const schakelaar = await screen.findByRole('checkbox', { name: /Activum automatisch aanmaken ná boeken voor Pilates Bloom/ })
    expect(schakelaar).not.toBeChecked()
    expect(screen.getByRole('textbox', { name: /Activeringsgrens/ })).toHaveValue('450,00')
    expect(screen.getByTestId('activa-grens-rlz')).toHaveTextContent(/Reeleezee: €\s?450,00 — bron wint/)
    const tabel = screen.getByTestId('activa-categorie-tabel')
    expect(within(tabel).getByRole('combobox', { name: 'Termijn Inventaris' })).toHaveValue('60')
    expect(within(tabel).getByRole('combobox', { name: 'Termijn Computers / software' })).toHaveValue('36')
    expect(within(tabel).getByRole('combobox', { name: 'Afschrijvingsrekening Inventaris' })).toHaveValue('0108 · Afschrijving inventaris')
    expect(within(tabel).getByRole('combobox', { name: 'Afschrijvingsrekening Steigermateriaal' })).toHaveValue('')
    expect(screen.getByTestId('activa-registerstand')).toHaveTextContent(/recht ontbreekt \(403\)/)
    expect(screen.getByTestId('activa-mva-lijst')).toHaveTextContent('0107 Inventaris')
    expect(screen.getByTestId('activa-tellers')).toHaveTextContent('2 aangemaakt · 1 gepland · 0 niet geactiveerd · 1 mislukt · 0 beoordelen')
    expect(screen.getByRole('button', { name: 'Opslaan' })).toBeDisabled()
  })

  it('schakelaar aan + termijn wijzigen + grens wijzigen → Opslaan stuurt de volledige stand (PUT) en toont "opgeslagen"', async () => {
    const gebruiker = userEvent.setup()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as { automatisch_aanmaken_ingeschakeld: boolean; activeringsgrens: string; termijnen: Record<string, number> }
        return Promise.resolve(
          json(stand({ automatisch_aanmaken_ingeschakeld: body.automatisch_aanmaken_ingeschakeld, activeringsgrens: body.activeringsgrens, termijnen: body.termijnen })),
        )
      }
      return Promise.resolve(json(stand()))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<ActivaInstellingenBlok administratieId={AID} naam="Pilates Bloom B.V." />)
    await gebruiker.click(await screen.findByRole('checkbox', { name: /Activum automatisch aanmaken/ }))
    await gebruiker.selectOptions(screen.getByRole('combobox', { name: 'Termijn Steigermateriaal' }), '84')
    const grens = screen.getByRole('textbox', { name: /Activeringsgrens/ })
    await gebruiker.clear(grens)
    await gebruiker.type(grens, '1000')
    await gebruiker.click(screen.getByRole('button', { name: 'Opslaan' }))
    await waitFor(() => expect(screen.getByText('opgeslagen')).toBeInTheDocument())
    const put = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'PUT')
    expect(put?.[0]).toBe(`/administraties/${AID}/activa-instelling`)
    const putInit = put?.[1] as RequestInit | undefined
    expect(JSON.parse(String(putInit?.body))).toEqual({
      automatisch_aanmaken_ingeschakeld: true,
      activeringsgrens: '1000.00',
      termijnen: { inventaris: 60, computers_software: 36, steigermateriaal: 84 },
      afschrijving_ledgers: { inventaris: 'gb-0108' },
    })
    expect(screen.getByRole('checkbox', { name: /Activum automatisch aanmaken/ })).toBeChecked()
  })

  it('een ongeldige grens (negatief/tekst) blokkeert Opslaan mét melding; registerstand leesbaar en nog niet gemeten; geen activarekening = uitleg', async () => {
    const gebruiker = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json(stand({ register_leesbaar: true, register_fout: null, mva_rekeningen: [] })))))
    render(<ActivaInstellingenBlok administratieId={AID} naam="Pilates Bloom B.V." />)
    const grens = await screen.findByRole('textbox', { name: /Activeringsgrens/ })
    await gebruiker.clear(grens)
    await gebruiker.type(grens, '-5')
    expect(screen.getByText('bedrag ≥ 0 verwacht')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Opslaan' })).toBeDisabled()
    expect(screen.getByTestId('activa-registerstand')).toHaveTextContent(/activaregister leesbaar — gemeten/)
    expect(screen.getByTestId('activa-mva-leeg')).toHaveTextContent(/Geen activarekening herkend/)
  })

  it('registerstand nog niet gemeten en Reeleezee zonder grens → eigen waarde geldt', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json(stand({ register_leesbaar: null, register_geprobeerd_op: null, register_fout: null, grens_rlz: null, grens_bron: 'instelling' })))))
    render(<ActivaInstellingenBlok administratieId={AID} naam="Pilates Bloom B.V." />)
    expect(await screen.findByTestId('activa-registerstand')).toHaveTextContent(/nog niet gemeten/)
    expect(screen.queryByTestId('activa-grens-rlz')).toBeNull()
    expect(screen.getByText(/Reeleezee heeft geen grens ingesteld/)).toBeInTheDocument()
  })

  it('een opslaanfout (bv. 422 termijn) blijft zichtbaar als alert', async () => {
    const gebruiker = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => (init?.method === 'PUT' ? Promise.resolve(json({ detail: 'termijn moet een veelvoud van 12 zijn' }, 422)) : Promise.resolve(json(stand())))),
    )
    render(<ActivaInstellingenBlok administratieId={AID} naam="Pilates Bloom B.V." />)
    await gebruiker.click(await screen.findByRole('checkbox', { name: /Activum automatisch aanmaken/ }))
    await gebruiker.click(screen.getByRole('button', { name: 'Opslaan' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('termijn moet een veelvoud van 12 zijn')
  })

  it('laadfout = zichtbare melding, geen formulier', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({ detail: 'Not authenticated' }, 403))))
    render(<ActivaInstellingenBlok administratieId={AID} naam="Pilates Bloom B.V." />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Not authenticated')
    expect(screen.queryByRole('button', { name: 'Opslaan' })).toBeNull()
  })
})
