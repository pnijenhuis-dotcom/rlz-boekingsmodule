// Mini-voorraad opt-in (opdracht 06-09, F1): Beheerder-toggle op de administratie-detailpagina naast
// "Voorraad bijhouden" — zelfde toggle-helper (PendingToggle → bevestigingsdialoog in InstellingenScreen)
// — en de chip "Mini-voorraad" in de administraties-tabel.
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AdministratieInstellingenDto } from '../api/types'
import { AdministratieDetailPagina } from './AdministratieDetailPagina'
import { chipsVoor } from './AdministratiesV2'

function administratie(overrides: Partial<AdministratieInstellingenDto> = {}): AdministratieInstellingenDto {
  return {
    id: 'aaaaaaaa-0000-0000-0000-000000000001',
    naam: 'Universal Steigerbouw B.V.',
    boeken_ingeschakeld: true,
    project_verplicht: false,
    ai_extractie_ingeschakeld: true,
    eigenaar_gebruiker_id: null,
    is_vastgoed: false,
    verkoop_autoboeken_ingeschakeld: false,
    uren_meerwerk_ingeschakeld: true,
    uren_dagmax_uren: '12',
    afdelingen_ingeschakeld: false,
    voorraad_ingeschakeld: true,
    mini_voorraad_ingeschakeld: false,
    ...overrides,
  }
}

function renderPagina(a: AdministratieInstellingenDto, onPending = vi.fn()) {
  render(
    <MemoryRouter initialEntries={[`/instellingen/administraties/${a.id}`]}>
      <AdministratieDetailPagina
        administratie={a}
        accordeursVersie={0}
        onPending={onPending}
        onWebservice={vi.fn()}
        onSchrijftest={vi.fn()}
        onArchiveren={vi.fn()}
        onDossierTypen={vi.fn()}
        onDagmax={vi.fn()}
        onHerlaad={vi.fn()}
      />
    </MemoryRouter>,
  )
  return onPending
}

describe('AdministratieDetailPagina — mini-voorraad opt-in (06-09)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('toont de toggle "Mini-voorraad speciale producten" naast "Voorraad bijhouden"; aanzetten = PendingToggle type mini_voorraad (bevestiging + audit volgen)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 404 }))))
    const gebruiker = userEvent.setup()
    const onPending = renderPagina(administratie())
    const voorraad = screen.getByRole('checkbox', { name: 'Voorraad bijhouden voor Universal Steigerbouw B.V.' })
    const mini = screen.getByRole('checkbox', { name: 'Mini-voorraad speciale producten voor Universal Steigerbouw B.V.' })
    expect(voorraad).toBeChecked()
    expect(mini).not.toBeChecked()
    expect(screen.getByRole('link', { name: 'materiaalcatalogus › Mini-voorraad →' })).toHaveAttribute('href', '/instellingen/materiaal')
    await gebruiker.click(mini)
    expect(onPending).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'mini_voorraad', administratieId: 'aaaaaaaa-0000-0000-0000-000000000001', naam: 'Universal Steigerbouw B.V.', nieuweWaarde: true }),
    )
  })

  it('gearchiveerde administratie: toggle uitgeschakeld', () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(null, { status: 404 }))))
    renderPagina(administratie({ gearchiveerd_op: '2026-09-01T10:00:00Z', mini_voorraad_ingeschakeld: true }))
    const mini = screen.getByRole('checkbox', { name: 'Mini-voorraad speciale producten voor Universal Steigerbouw B.V.' })
    expect(mini).toBeChecked()
    expect(mini).toBeDisabled()
  })

  it('chipsVoor: module-chip "Mini-voorraad" alleen bij de opt-in', () => {
    expect(chipsVoor(administratie({ mini_voorraad_ingeschakeld: true })).map((c) => c.tekst)).toContain('Mini-voorraad')
    expect(chipsVoor(administratie()).map((c) => c.tekst)).not.toContain('Mini-voorraad')
  })
})
