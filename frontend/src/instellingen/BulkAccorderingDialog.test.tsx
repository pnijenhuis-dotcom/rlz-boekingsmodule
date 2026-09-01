// Bulk klant-accordering instellen (mockup bulk-accordering.html, 01-09): de dialoog toont de
// server-preview (scope-melding per accordeur mét BV-namen, overschrijf-waarschuwing mét
// telling vervallen rondes, uitkomstenlijst) en herbruikt exact die weergave als resultaat ná
// toepassen — de client rekent niets zelf.
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BulkAccorderingDialog } from './BulkAccorderingDialog'

const ARVUM = 'aaaaaaaa-0000-0000-0000-000000000001'
const MOLENHOF = 'aaaaaaaa-0000-0000-0000-000000000002'
const GERRITSEN = 'bbbbbbbb-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetchMock(aanroepen: { url: string; body: unknown }[] = []) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url === '/accordering/accordeur-kandidaten') {
        return Promise.resolve(jsonResponse({ kandidaten: [{ id: GERRITSEN, naam: 'J.W.F. Gerritsen' }] }))
      }
      if (url === '/accordering/bulk-instellen/preview') {
        aanroepen.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(
          jsonResponse({
            uitkomsten: [
              {
                administratie_id: ARVUM,
                administratie_naam: 'ARVUM B.V.',
                uitkomst: 'vervangen',
                rondes_vervallen: 2,
                toggle_aangezet: false,
                scope_toegevoegd_voor: [],
                reden: null,
              },
              {
                administratie_id: MOLENHOF,
                administratie_naam: 'Molenhof Beheer B.V.',
                uitkomst: 'ingesteld',
                rondes_vervallen: 0,
                toggle_aangezet: true,
                scope_toegevoegd_voor: ['J.W.F. Gerritsen'],
                reden: null,
              },
            ],
            scope_ontbreekt: [
              {
                accordeur_gebruiker_id: GERRITSEN,
                accordeur_naam: 'J.W.F. Gerritsen',
                administratie_ids: [MOLENHOF],
                administratie_namen: ['Molenhof Beheer B.V.'],
              },
            ],
          }),
        )
      }
      if (url === '/accordering/bulk-instellen') {
        aanroepen.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null })
        return Promise.resolve(
          jsonResponse({
            uitkomsten: [
              {
                administratie_id: ARVUM,
                administratie_naam: 'ARVUM B.V.',
                uitkomst: 'vervangen',
                rondes_vervallen: 2,
                toggle_aangezet: false,
                scope_toegevoegd_voor: [],
                reden: null,
              },
              {
                administratie_id: MOLENHOF,
                administratie_naam: 'Molenhof Beheer B.V.',
                uitkomst: 'ingesteld',
                rondes_vervallen: 0,
                toggle_aangezet: true,
                scope_toegevoegd_voor: ['J.W.F. Gerritsen'],
                reden: null,
              },
            ],
          }),
        )
      }
      return Promise.resolve(jsonResponse({ detail: `onverwacht pad: ${url}` }, 500))
    }),
  )
  return aanroepen
}

const ADMINISTRATIES = [
  { id: ARVUM, naam: 'ARVUM B.V.' },
  { id: MOLENHOF, naam: 'Molenhof Beheer B.V.' },
]

describe('BulkAccorderingDialog', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('toont ná het kiezen van een laag de preview: scope-melding, overschrijf-telling en uitkomstlijst', async () => {
    const aanroepen = installFetchMock()
    render(<BulkAccorderingDialog administraties={ADMINISTRATIES} onSluiten={vi.fn()} onGereed={vi.fn()} />)
    const gebruiker = userEvent.setup()

    await gebruiker.click(await screen.findByRole('combobox', { name: 'Accordeur laag 1' }))
    await gebruiker.click(await screen.findByRole('option', { name: 'J.W.F. Gerritsen' }))

    // Scope-melding mét BV-namen (mockup-tekst), overschrijf-waarschuwing mét telling.
    expect(
      await screen.findByText(/J\.W\.F\. Gerritsen heeft nog geen toegang tot Molenhof Beheer B\.V\./),
    ).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Overschrijven:')
    expect(screen.getByRole('alert')).toHaveTextContent('2 lopende accorderingsrondes')
    // Uitkomstenlijst = preview-weergave.
    expect(screen.getByText('vervangen · 2 rondes vervallen')).toBeInTheDocument()
    expect(screen.getByText('ingesteld · toggle aan · scope toegevoegd')).toBeInTheDocument()

    // De preview-call draagt de vink (default aan) en de volledige laag.
    const preview = aanroepen.find((a) => a.url.endsWith('/preview'))?.body as {
      scope_toevoegen: boolean
      lagen: { accordeur_gebruiker_id: string }[]
    }
    expect(preview.scope_toevoegen).toBe(true)
    expect(preview.lagen).toEqual([{ volgnummer: 1, accordeur_gebruiker_id: GERRITSEN, bedrag_drempel: null }])
  })

  it('toepassen toont het resultaat in dezelfde weergave en meldt gereed pas bij sluiten', async () => {
    const aanroepen = installFetchMock()
    const onGereed = vi.fn()
    render(<BulkAccorderingDialog administraties={ADMINISTRATIES} onSluiten={vi.fn()} onGereed={onGereed} />)
    const gebruiker = userEvent.setup()

    await gebruiker.click(await screen.findByRole('combobox', { name: 'Accordeur laag 1' }))
    await gebruiker.click(await screen.findByRole('option', { name: 'J.W.F. Gerritsen' }))
    const toepassen = await screen.findByRole('button', { name: 'Toepassen op 2 administraties' })
    await waitFor(() => expect(toepassen).toBeEnabled())
    await gebruiker.click(toepassen)

    expect(await screen.findByText('Resultaat (per administratie)')).toBeInTheDocument()
    expect(screen.getByText('vervangen · 2 rondes vervallen')).toBeInTheDocument()
    expect(aanroepen.some((a) => a.url === '/accordering/bulk-instellen')).toBe(true)
    expect(onGereed).not.toHaveBeenCalled()
    await gebruiker.click(screen.getByRole('button', { name: 'Sluiten' }))
    expect(onGereed).toHaveBeenCalledTimes(1)
  })

  it('een ongeldige bedragdrempel blokkeert de preview en de toepassen-knop', async () => {
    installFetchMock()
    render(<BulkAccorderingDialog administraties={ADMINISTRATIES} onSluiten={vi.fn()} onGereed={vi.fn()} />)
    const gebruiker = userEvent.setup()

    await gebruiker.click(await screen.findByRole('combobox', { name: 'Accordeur laag 1' }))
    await gebruiker.click(await screen.findByRole('option', { name: 'J.W.F. Gerritsen' }))
    await gebruiker.type(screen.getByLabelText('Voorwaarde laag 1'), 'abc')

    expect(await screen.findByText(/geldig drempelbedrag/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Toepassen op 2 administraties' })).toBeDisabled()
  })
})
