// Peter 22-09 (casus Bouwadvies F/2026/01235): de twee handelingen op "intussen buiten de module geboekt" —
// afwijzen als al geboekt (voorgevulde reden, accordering ingetrokken) en toch verschillend (reden verplicht).
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ExternGeboektActies, externGeboektZin } from './ExternGeboektActies'
import type { ExternGeboektKern } from './reconciliatieApi'

const KERN: ExternGeboektKern = {
  extern_id: 'ffb1f1f3-0000-4000-8000-000000000518',
  extern_boekstuk: 'RLZ-04-00000518',
  systeem: 'Reeleezee',
  stand: 'geboekt',
  bedrag_extern: '173.84',
  extern_datum: '2026-08-26',
}

function stub(antwoord: unknown, status = 200) {
  const aangeroepen: { pad: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      aangeroepen.push({ pad: url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url === '/auth/token/vernieuwen') return Promise.resolve(new Response(null, { status: 401 }))
      return Promise.resolve(new Response(JSON.stringify(antwoord), { status, headers: { 'Content-Type': 'application/json' } }))
    }),
  )
  return aangeroepen
}

describe('ExternGeboektActies', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('zin benoemt boekstuk, bedrag, datum en "buiten de module"', () => {
    expect(externGeboektZin(KERN)).toBe('Deze factuur is al geboekt in Reeleezee als RLZ-04-00000518 (€ 173,84, 26-08-2026) — buiten de module om.')
    expect(externGeboektZin({ ...KERN, stand: 'concept', bedrag_extern: null, extern_datum: null })).toBe(
      'Deze factuur staat al als concept in Reeleezee als RLZ-04-00000518 — buiten de module om.',
    )
  })

  it('"Afwijzen — al geboekt als …": dialoog met voorgevulde reden, POST op de document-route, melding noemt de ingetrokken accordering', async () => {
    const aangeroepen = stub({ document_id: 'doc', status: 'afgewezen', reden: 'x', accordering_vervallen: true, afwijzing_id: 'afw' })
    const gelukt = vi.fn()
    render(<ExternGeboektActies administratieId="adm" documentId="doc" kern={KERN} leverancier="Beter Assemblage B.V." factuurnummer="F/2026/01235" onGelukt={gelukt} />)
    await userEvent.click(screen.getByRole('button', { name: 'Afwijzen — al geboekt als RLZ-04-00000518: F/2026/01235' }))
    const dialoog = await screen.findByTestId('extern-geboekt-afwijzen-dialoog')
    expect(dialoog).toHaveTextContent('Al geboekt in Reeleezee als RLZ-04-00000518 (buiten de module)')
    expect(dialoog).toHaveTextContent('niet meer nodig: al geboekt in Reeleezee')
    expect(dialoog).toHaveTextContent('Beter Assemblage B.V.')
    await userEvent.type(screen.getByLabelText('Toelichting (optioneel)'), 'door collega geboekt')
    await userEvent.click(screen.getByRole('button', { name: 'Afwijzen en accordering intrekken' }))
    await waitFor(() => expect(gelukt).toHaveBeenCalled())
    const post = aangeroepen.find((a) => a.pad === '/reconciliatie/documenten/doc/extern-geboekt/afwijzen')!
    expect(post.body).toEqual({
      administratie_id: 'adm',
      extern_id: KERN.extern_id,
      extern_boekstuk: 'RLZ-04-00000518',
      systeem: 'Reeleezee',
      toelichting: 'door collega geboekt',
    })
    expect(gelukt.mock.calls[0][0]).toContain('de accordering is ingetrokken')
  })

  it('"Toch verschillend — doorgaan": reden verplicht (≥ 5), POST mét bevinding_id, melding zegt wat er met de bevinding gebeurt', async () => {
    const aangeroepen = stub({ document_id: 'doc', extern_ids: [KERN.extern_id], reden: 'r', bevinding_geaccepteerd: false, checks_cache_ongeldig: 1 })
    const gelukt = vi.fn()
    render(<ExternGeboektActies administratieId="adm" documentId="doc" kern={KERN} bevindingId="bev-1" onGelukt={gelukt} />)
    await userEvent.click(screen.getByRole('button', { name: /^Toch verschillend — doorgaan/ }))
    const dialoog = await screen.findByTestId('extern-geboekt-verschillend-dialoog')
    const knop = screen.getByRole('button', { name: 'Vastleggen en doorgaan' })
    expect(knop).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Reden'), 'kort')
    expect(knop).toBeDisabled()
    expect(dialoog).toHaveTextContent('minimaal 5 tekens')
    await userEvent.type(screen.getByLabelText('Reden'), ' — tweede levering, ander bedrag')
    expect(knop).toBeEnabled()
    await userEvent.click(knop)
    await waitFor(() => expect(gelukt).toHaveBeenCalled())
    const post = aangeroepen.find((a) => a.pad === '/reconciliatie/documenten/doc/extern-geboekt/toch-verschillend')!
    expect(post.body).toEqual({
      administratie_id: 'adm',
      extern_id: KERN.extern_id,
      extern_boekstuk: 'RLZ-04-00000518',
      reden: 'kort — tweede levering, ander bedrag',
      bevinding_id: 'bev-1',
    })
    expect(gelukt.mock.calls[0][0]).toContain('verdwijnt bij de volgende dagelijkse controle')
  })

  it('een 409 van de server (bv. wacht op IBAN-accordering) blijft leesbaar in de dialoog', async () => {
    stub({ detail: 'Dit document wacht op de IBAN-accordering (vier ogen). Laat de tweede persoon die aanvraag eerst afwijzen of accorderen.' }, 409)
    render(<ExternGeboektActies administratieId="adm" documentId="doc" kern={KERN} onGelukt={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /^Afwijzen — al geboekt als/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Afwijzen en accordering intrekken' }))
    expect(await screen.findByText(/wacht op de IBAN-accordering/)).toBeInTheDocument()
  })
})
