import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccorderingSectie } from './AccorderingSectie'

// Blok 4 bundel 08-09: de kantoor-historie toont een overgeslagen accordering als rij zonder acties.
const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

const OVERGESLAGEN = {
  id: DOCUMENT_ID,
  document_id: DOCUMENT_ID,
  status: 'overgeslagen',
  aangeboden_op: '2026-09-08T18:00:00Z',
  afgerond_op: null,
  stappen: [],
  boek_fout: null,
  boek_fout_op: null,
  overgeslagen_reden: 'intercompany',
  overgeslagen_leverancier_naam: 'Universal Nederland B.V.',
}

describe('AccorderingSectie — overgeslagen (intercompany)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de chip "overgeslagen — intercompany" mét leveranciersnaam en géén acties', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/accordering/herinneringen')) return Promise.resolve(jsonResponse({ laatst_herinnerd: {} }))
        if (url.includes('/accordering/documenten/')) return Promise.resolve(jsonResponse(OVERGESLAGEN))
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    render(
      <AccorderingSectie administratieId={ADMINISTRATIE_ID} documentId={DOCUMENT_ID} documentStatus="geboekt" onGewijzigd={() => {}} />,
    )
    const paneel = await screen.findByTestId('accordering-overgeslagen')
    expect(paneel).toHaveTextContent('overgeslagen — intercompany')
    expect(paneel).toHaveTextContent('Universal Nederland B.V.')
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
