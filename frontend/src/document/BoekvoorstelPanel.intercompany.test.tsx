import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'

// Blok 4 bundel 08-09 (besluit Peter): een leverancier met IC-vlag slaat de klant-accordering over — de knop op het
// controlescherm is dan "Boeken in RLZ ✓" i.p.v. "Ter accordering →", mét zichtbare uitleg-chip; de backend levert dat
// als additief veld `accordering_overgeslagen_reden` op het boekvoorstel. Zonder het veld: ongewijzigd gedrag.

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const VENDOR_ID = '33333333-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function boekvoorstel(extra: Record<string, unknown>) {
  return {
    document_id: DOCUMENT_ID,
    vendor_id: VENDOR_ID,
    referentie: 'RLZ-2080143037',
    factuurdatum: '2026-08-01',
    totaalbedrag: '212.21',
    rlz_boekstuknummer: null,
    opgeslagen: true,
    regels: [],
    regels_samenvoegen: true,
    samenvoegen_toegestaan: true,
    samengevoegde_regel: null,
    ...extra,
  }
}

function installFetchMock(opties: { accorderingAan: boolean; boekvoorstel: unknown }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/accordering/instellingen')) {
        return Promise.resolve(jsonResponse({ ingeschakeld: opties.accorderingAan, lagen: [] }))
      }
      if (url.endsWith(`/accordering/documenten/${DOCUMENT_ID}`) && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse(null))
      }
      if (url.endsWith('/grootboek')) return Promise.resolve(jsonResponse({ rekeningen: [] }))
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [] }))
      if (url.endsWith('/crediteuren')) {
        return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Universal Nederland B.V.' }] }))
      }
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse(opties.boekvoorstel))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

function renderPanel() {
  return render(
    <BoekvoorstelPanel
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      status="klaar_om_te_boeken"
      onGeboekt={() => {}}
      onHersteld={() => {}}
    />,
  )
}

describe('BoekvoorstelPanel — intercompany slaat klant-accordering over (blok 4 bundel 08-09)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('accordering aan + accordering_overgeslagen_reden "intercompany" → knop "Boeken in RLZ ✓" + uitleg-chip', async () => {
    installFetchMock({ accorderingAan: true, boekvoorstel: boekvoorstel({ accordering_overgeslagen_reden: 'intercompany' }) })
    renderPanel()
    expect(await screen.findByRole('button', { name: 'Boeken in RLZ ✓' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Ter accordering/ })).not.toBeInTheDocument()
    const chip = screen.getByTestId('accordering-overgeslagen-intercompany')
    expect(chip).toHaveTextContent('intercompany')
    expect(chip).toHaveTextContent('Klant-accordering wordt overgeslagen')
  })

  it('accordering aan zónder het veld (of null) → ongewijzigd "Ter accordering →", geen chip', async () => {
    installFetchMock({ accorderingAan: true, boekvoorstel: boekvoorstel({ accordering_overgeslagen_reden: null }) })
    renderPanel()
    expect(await screen.findByRole('button', { name: 'Ter accordering →' })).toBeInTheDocument()
    expect(screen.queryByTestId('accordering-overgeslagen-intercompany')).not.toBeInTheDocument()
  })

  it('accordering uit → gewone boekknop, geen chip (ook al zou het veld gevuld zijn)', async () => {
    installFetchMock({ accorderingAan: false, boekvoorstel: boekvoorstel({ accordering_overgeslagen_reden: 'intercompany' }) })
    renderPanel()
    expect(await screen.findByRole('button', { name: 'Boeken in RLZ ✓' })).toBeInTheDocument()
    expect(screen.queryByTestId('accordering-overgeslagen-intercompany')).not.toBeInTheDocument()
  })
})
