/** Blok 1 07-09: module-tegenhangers (harde check "Duplicaat (module)") op het controlescherm + de mens-override
 * "Geen duplicaat — afmelden" (reden verplicht). */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DuplicaatAfvoerStandDto } from '../api/types'
import { DuplicaatAfvoerSectie } from './DuplicaatAfvoer'

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const ANDER_ID = 'cccccccc-0000-0000-0000-000000000003'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function standMetModuleTreffer(): DuplicaatAfvoerStandDto {
  return {
    kandidaat: null, // categorie (c): geen harde afvoer-match, wél rood
    afgevoerd_als_duplicaat_van: null,
    afgevoerde_duplicaten: [],
    module_treffers: [
      {
        document_id: ANDER_ID,
        categorie: 'crediteur_referentie',
        status: 'te_controleren',
        bestandsnaam: 'deel-1.pdf',
        aangemaakt_op: '2026-09-01T09:00:00Z',
        referentie: 'F-2026-0042',
        totaalbedrag: '500.00',
      },
    ],
    afmelding: null,
  }
}

describe('DuplicaatAfvoerSectie — module-tegenhangers + afmelden (blok 1 07-09)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont het paneel "controle rood" met de tegenhanger-lijst en géén afvoer-knop bij categorie (c); afmelden vereist een reden en POST naar duplicaat-afmelden', async () => {
    const gebruiker = userEvent.setup()
    const posts: Array<{ url: string; body: unknown }> = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (String(url).endsWith('/duplicaat-afmelden') && init?.method === 'POST') {
          posts.push({ url: String(url), body: JSON.parse(String(init.body)) })
          return Promise.resolve(
            jsonResponse({ reden: 'Deelfactuur', actor_id: 'u', tijdstip: '2026-09-07T10:00:00Z', tegenhangers: [ANDER_ID] }),
          )
        }
        return Promise.resolve(new Response(null, { status: 404 }))
      }),
    )
    const onGewijzigd = vi.fn()
    render(
      <MemoryRouter>
        <DuplicaatAfvoerSectie
          administratieId={ADMINISTRATIE_ID}
          documentId={DOCUMENT_ID}
          bestandsnaam="deel-2.pdf"
          status="te_controleren"
          stand={standMetModuleTreffer()}
          naamVoor={(id) => id}
          onGewijzigd={onGewijzigd}
        />
      </MemoryRouter>,
    )

    expect(screen.getByTestId('duplicaat-module')).toBeInTheDocument()
    expect(screen.getByText('controle rood')).toHaveClass('chip')
    expect(screen.getByRole('link', { name: 'deel-1.pdf' })).toHaveAttribute('href', `/documenten/${ADMINISTRATIE_ID}/${ANDER_ID}`)
    expect(screen.getByText(/zelfde crediteur \+ referentie \(ander bedrag\)/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Afvoeren als duplicaat…' })).not.toBeInTheDocument()

    await gebruiker.click(screen.getByRole('button', { name: 'Geen duplicaat — afmelden…' }))
    const dialoog = await screen.findByTestId('duplicaat-afmelden-dialoog')
    expect(dialoog).toBeInTheDocument()
    // Zonder reden: knop uitgeschakeld (reden verplicht).
    const bevestig = screen.getByRole('button', { name: 'Afmelden als geen duplicaat' })
    expect(bevestig).toBeDisabled()
    await gebruiker.type(screen.getByLabelText('Reden'), 'Deelfactuur 2 van 2, zelfde nummer')
    expect(bevestig).toBeEnabled()
    await gebruiker.click(bevestig)

    await waitFor(() => expect(posts).toHaveLength(1))
    expect(posts[0].url).toContain(`/administraties/${ADMINISTRATIE_ID}/documenten/${DOCUMENT_ID}/duplicaat-afmelden`)
    expect(posts[0].body).toEqual({ reden: 'Deelfactuur 2 van 2, zelfde nummer' })
    await waitFor(() => expect(onGewijzigd).toHaveBeenCalledTimes(1))
  })

  it('toont de afmelding als hint zodra er geen tegenhangers meer zijn', () => {
    render(
      <MemoryRouter>
        <DuplicaatAfvoerSectie
          administratieId={ADMINISTRATIE_ID}
          documentId={DOCUMENT_ID}
          bestandsnaam="deel-2.pdf"
          status="te_controleren"
          stand={{
            kandidaat: null,
            afgevoerd_als_duplicaat_van: null,
            afgevoerde_duplicaten: [],
            module_treffers: [],
            afmelding: { reden: 'Deelfactuur', actor_id: 'gebruiker-1', tijdstip: '2026-09-07T10:00:00Z', tegenhangers: [ANDER_ID] },
          }}
          naamVoor={(id) => (id === 'gebruiker-1' ? 'S. Bakker' : id)}
          onGewijzigd={() => undefined}
        />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('duplicaat-afgemeld')).toHaveTextContent('Afgemeld als geen duplicaat door S. Bakker')
    expect(screen.getByTestId('duplicaat-afgemeld')).toHaveTextContent('“Deelfactuur”')
  })
})
