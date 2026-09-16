import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DocumentListItemDto } from '../api/types'
import { ToastProvider } from '../ui/basis'
import { DocumentenBulkBalk, bereikSelectie, isBulkSelecteerbaar } from './DocumentenBulkActies'

/** Bulk-acties documentenlijst (Peter 16-09): selectiebalk mét teller en "alle N in deze weergave", primaire knop
 * Verwijderen… + ⋯ (Type wijzigen…, Verplaatsen…, Afwijzen…), één reden, één POST …/documenten/bulk met de selectie,
 * uitkomst per rij ná afloop, selectie leeg; shift-klik-bereik als pure helper. */

const ADMIN = 'aaaaaaaa-0000-4000-8000-000000000001'

function doc(id: string, over: Partial<DocumentListItemDto> = {}): DocumentListItemDto {
  return {
    id,
    bestandsnaam: `${id}.pdf`,
    status: 'te_controleren',
    bron: 'e-mail',
    soort: 'inkoopfactuur',
    mogelijk_duplicaat_van: null,
    toegewezen_aan: null,
    aangemaakt_op: '2026-09-16T08:00:00Z',
    laatst_gewijzigd_op: '2026-09-16T08:00:00Z',
    afwijzing: null,
    leverancier: `Leverancier ${id}`,
    totaalbedrag: '100.00',
    factuurdatum: '2026-09-12',
    automatisch_geboekt: false,
    ...over,
  }
}

const DOCS = [doc('d1'), doc('d2'), doc('d3', { status: 'klaar_om_te_boeken' })]

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function Harnas({ start = [] as string[], posts }: { start?: string[]; posts: { url: string; body: unknown }[] }) {
  // Kleine host die de selectie bijhoudt zoals het scherm dat doet.
  const [sel, setSel] = (globalThis as unknown as { React: typeof import('react') }).React.useState(new Set(start))
  return (
    <ToastProvider>
      <DocumentenBulkBalk
        administratieId={ADMIN}
        administratieNaam="De Bazar Apeldoorn"
        selectie={sel}
        zichtbaar={DOCS}
        onSelecteerZichtbaar={(aan) => setSel(aan ? new Set(DOCS.map((d) => d.id)) : new Set())}
        onWissen={() => setSel(new Set())}
        onAfgerond={() => posts.push({ url: 'afgerond', body: null })}
      />
      <output data-testid="stand">{[...sel].sort().join(',')}</output>
    </ToastProvider>
  )
}

function installFetch(posts: { url: string; body: unknown }[], antwoord?: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(json({ administraties: [{ id: ADMIN, naam: 'De Bazar Apeldoorn' }, { id: 'bbbbbbbb-0000-4000-8000-000000000002', naam: 'Kempen Facilities B.V.' }] }))
      }
      if (url.endsWith('/documenten/bulk') && init?.method === 'POST') {
        posts.push({ url, body: JSON.parse(String(init.body)) })
        return Promise.resolve(
          json(
            antwoord ?? {
              actie: 'verwijderen',
              geselecteerd: 3,
              gelukt: 2,
              overgeslagen: 1,
              geen_toegang: 0,
              rijen: [
                { document_id: 'd1', bestandsnaam: 'd1.pdf', uitkomst: 'gelukt', reden: null, status: 'verwijderd' },
                { document_id: 'd2', bestandsnaam: 'd2.pdf', uitkomst: 'gelukt', reden: null, status: 'verwijderd' },
                { document_id: 'd3', bestandsnaam: 'd3.pdf', uitkomst: 'overgeslagen', reden: 'overgeslagen — geboekt: Geboekte documenten kunnen niet verwijderd worden (bewaarplicht).', status: null },
              ],
            },
          ),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('bereikSelectie / isBulkSelecteerbaar', () => {
  it('shift-klik selecteert het bereik in lijstvolgorde, ook omgekeerd; zonder vorige klik alleen de rij', () => {
    const ids = ['a', 'b', 'c', 'd', 'e']
    expect([...bereikSelectie(ids, 'b', 'd', new Set(['b']))].sort()).toEqual(['b', 'c', 'd'])
    expect([...bereikSelectie(ids, 'd', 'a', new Set(['d']))].sort()).toEqual(['a', 'b', 'c', 'd'])
    expect([...bereikSelectie(ids, null, 'c', new Set())]).toEqual(['c'])
  })

  it('eindstatussen zijn niet bulk-selecteerbaar', () => {
    expect(isBulkSelecteerbaar({ status: 'te_controleren' })).toBe(true)
    expect(isBulkSelecteerbaar({ status: 'geboekt' })).toBe(false)
    expect(isBulkSelecteerbaar({ status: 'verwijderd' })).toBe(false)
    expect(isBulkSelecteerbaar({ status: 'ter_accordering' })).toBe(true) // server beslist (overgeslagen mét reden)
  })
})

describe('DocumentenBulkBalk', () => {
  it('alle N in deze weergave → Verwijderen… → reden → één POST met de selectie; uitkomst per rij; selectie leeg', async () => {
    const posts: { url: string; body: unknown }[] = []
    installFetch(posts)
    const gebruiker = userEvent.setup()
    const React = await import('react')
    ;(globalThis as unknown as { React: typeof React }).React = React
    render(<Harnas posts={posts} />)
    const balk = screen.getByTestId('documenten-bulk-balk')
    expect(balk).toHaveTextContent('3 in deze weergave')
    expect(screen.getByTestId('bulk-verwijderen')).toBeDisabled()
    await gebruiker.click(within(balk).getByRole('checkbox', { name: 'Alle 3 documenten in deze weergave selecteren' }))
    expect(balk).toHaveTextContent('3 van 3 geselecteerd')
    await gebruiker.click(screen.getByTestId('bulk-verwijderen'))
    const dialoog = screen.getByTestId('documenten-bulk-dialoog')
    expect(dialoog).toHaveTextContent('Verwijderen — 3 documenten')
    expect(screen.getByTestId('documenten-bulk-bevestig')).toBeDisabled()
    await gebruiker.type(within(dialoog).getByLabelText('Reden'), 'ProfX-journaal, geen inkoopfactuur')
    await gebruiker.click(screen.getByTestId('documenten-bulk-bevestig'))
    await waitFor(() => expect(posts.filter((p) => p.url.endsWith('/documenten/bulk'))).toHaveLength(1))
    expect(posts[0]).toEqual({
      url: `/administraties/${ADMIN}/documenten/bulk`,
      body: { document_ids: ['d1', 'd2', 'd3'], actie: 'verwijderen', reden: 'ProfX-journaal, geen inkoopfactuur' },
    })
    const resultaat = await screen.findByTestId('documenten-bulk-resultaat')
    expect(resultaat).toHaveTextContent('Verwijderen: 2 gelukt, 1 overgeslagen.')
    expect(resultaat).toHaveTextContent('d3.pdf')
    expect(resultaat).toHaveTextContent('overgeslagen — geboekt')
    expect(screen.getByTestId('stand')).toHaveTextContent('')
    expect(posts.some((p) => p.url === 'afgerond')).toBe(true)
  })

  it('⋯ → Type wijzigen… stuurt soort; Verplaatsen… vraagt een doeladministratie (niet de eigen)', async () => {
    const posts: { url: string; body: unknown }[] = []
    installFetch(posts, { actie: 'soort_wijzigen', geselecteerd: 1, gelukt: 1, overgeslagen: 0, geen_toegang: 0, rijen: [] })
    const gebruiker = userEvent.setup()
    const React = await import('react')
    ;(globalThis as unknown as { React: typeof React }).React = React
    render(<Harnas start={['d1']} posts={posts} />)
    await gebruiker.click(screen.getByRole('button', { name: 'Meer bulk-acties' }))
    await gebruiker.click(await screen.findByRole('menuitem', { name: '⇄ Type wijzigen…' }))
    const dialoog = screen.getByTestId('documenten-bulk-dialoog')
    expect(dialoog).toHaveTextContent('Type wijzigen — 1 document')
    await gebruiker.selectOptions(within(dialoog).getByLabelText('Nieuw documenttype'), 'kassarapport')
    await gebruiker.click(screen.getByTestId('documenten-bulk-bevestig'))
    await waitFor(() => expect(posts.filter((p) => p.url.endsWith('/documenten/bulk'))).toHaveLength(1))
    expect(posts[0].body).toEqual({ document_ids: ['d1'], actie: 'soort_wijzigen', soort: 'kassarapport' })

    // Ná afloop is de selectie leeg (⋯ uit); opnieuw selecteren via "alle in deze weergave".
    expect(screen.getByRole('button', { name: 'Meer bulk-acties' })).toBeDisabled()
    await gebruiker.click(screen.getByRole('checkbox', { name: 'Alle 3 documenten in deze weergave selecteren' }))
    // Verplaatsen: bevestigen pas mogelijk mét een doel; de eigen administratie staat niet in de lijst.
    await gebruiker.click(screen.getByRole('button', { name: 'Meer bulk-acties' }))
    await gebruiker.click(await screen.findByRole('menuitem', { name: '⇥ Verplaatsen naar administratie…' }))
    const d2 = screen.getByTestId('documenten-bulk-dialoog')
    expect(d2).toHaveTextContent('Verplaatsen naar administratie — 3 documenten')
    expect(screen.getByTestId('documenten-bulk-bevestig')).toBeDisabled()
    expect(d2).toHaveTextContent('verhuizen van De Bazar Apeldoorn naar de gekozen administratie')
  })
})
