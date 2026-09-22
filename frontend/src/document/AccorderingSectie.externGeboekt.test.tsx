// 22-09 (Peter, casus Bouwadvies): strandt het boeken ná het laatste akkoord op een extern al geboekt stuk, dan krijgt
// de melding dezelfde twee knoppen als Inzicht › Reconciliatie — geen proza "los de oorzaak op", geen woord "bug".
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccorderingSectie, externGeboektKernUitBoekFout } from './AccorderingSectie'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

const AFGEROND_MET_EXTERN = {
  id: 'acc-1',
  document_id: DOCUMENT_ID,
  status: 'afgerond',
  aangeboden_op: '2026-09-16T09:13:00Z',
  afgerond_op: '2026-09-21T19:15:00Z',
  stappen: [],
  boek_fout: 'Boeken geblokkeerd door harde checks: 1 bestaande factuur/facturen in RLZ met dezelfde crediteur en referentie — al geboekt in Reeleezee: RLZ-04-00000518 (referentie F/2026/01235, buiten de module)',
  boek_fout_op: '2026-09-21T19:15:05Z',
  boek_fout_extern_geboekt: {
    extern_id: 'ffb1f1f3-0000-4000-8000-000000000518',
    extern_boekstuk: 'RLZ-04-00000518',
    extern_referentie: 'F/2026/01235',
    extern_stand: 'geboekt',
    bedrag_extern: '173.84',
    extern_datum: '2026-08-26',
    systeem: 'Reeleezee',
  },
}

function installFetchMock(accordering: unknown) {
  const aangeroepen: { url: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      aangeroepen.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined })
      if (url.endsWith('/extern-geboekt/afwijzen') && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ document_id: DOCUMENT_ID, status: 'afgewezen', reden: 'x', accordering_vervallen: false, afwijzing_id: 'afw' }))
      }
      if (url.endsWith('/accordering/herinneringen')) return Promise.resolve(jsonResponse({ laatst_herinnerd: {} }))
      if (url.includes('/accordering/documenten/')) return Promise.resolve(jsonResponse(accordering))
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return aangeroepen
}

describe('AccorderingSectie — boekfout is een extern al geboekt stuk (22-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('kern-vertaling: alleen mét extern_id; systeem/stand met defaults', () => {
    expect(externGeboektKernUitBoekFout(null)).toBeNull()
    expect(externGeboektKernUitBoekFout({ extern_boekstuk: 'x' })).toBeNull()
    expect(externGeboektKernUitBoekFout(AFGEROND_MET_EXTERN.boek_fout_extern_geboekt)).toEqual({
      extern_id: 'ffb1f1f3-0000-4000-8000-000000000518',
      extern_boekstuk: 'RLZ-04-00000518',
      systeem: 'Reeleezee',
      stand: 'geboekt',
      bedrag_extern: '173.84',
      extern_datum: '2026-08-26',
    })
  })

  it('toont de twee knoppen i.p.v. "Los de oorzaak op", zonder het woord bug; afwijzen roept de document-route aan', async () => {
    const aangeroepen = installFetchMock(AFGEROND_MET_EXTERN)
    const gewijzigd = vi.fn()
    const { container } = render(
      <AccorderingSectie administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} documentStatus="ter_accordering" onGewijzigd={gewijzigd} />,
    )
    const acties = await screen.findByTestId('extern-geboekt-acties')
    expect(acties).toHaveTextContent('Afwijzen — al geboekt als RLZ-04-00000518')
    expect(acties).toHaveTextContent('Toch verschillend — doorgaan')
    expect(container.textContent).not.toContain('Los de oorzaak op')
    expect(container.textContent).not.toMatch(/\bbug\b/i)
    expect(screen.queryByRole('button', { name: /Opnieuw boeken/ })).toBeNull()
    expect(container.textContent).toContain('staat al in Reeleezee als RLZ-04-00000518')
    await userEvent.click(screen.getByRole('button', { name: /^Afwijzen — al geboekt als RLZ-04-00000518/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Afwijzen en accordering intrekken' }))
    await waitFor(() => expect(gewijzigd).toHaveBeenCalled())
    const post = aangeroepen.find((a) => a.url === `/reconciliatie/documenten/${DOCUMENT_ID}/extern-geboekt/afwijzen`)!
    expect(post.body).toMatchObject({ administratie_id: ADMINISTRATIE_ID, extern_boekstuk: 'RLZ-04-00000518', systeem: 'Reeleezee' })
    expect(await screen.findByTestId('accordering-melding')).toHaveTextContent('Afgewezen als al geboekt (RLZ-04-00000518)')
  })

  it('een andere boekfout houdt de gewone melding + "Opnieuw boeken"', async () => {
    installFetchMock({ ...AFGEROND_MET_EXTERN, boek_fout: 'Boeken geblokkeerd door harde checks: Regel 1 mist grootboek', boek_fout_extern_geboekt: null })
    const { container } = render(
      <AccorderingSectie administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} documentStatus="ter_accordering" onGewijzigd={() => {}} />,
    )
    expect(await screen.findByRole('button', { name: 'Opnieuw boeken (klant-akkoord compleet)' })).toBeInTheDocument()
    expect(container.textContent).toContain('Los de oorzaak op')
    expect(screen.queryByTestId('extern-geboekt-acties')).toBeNull()
  })
})
