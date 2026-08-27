import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VerplaatsModal } from './VerplaatsModal'
import { redenNietVerplaatsbaar, VERPLAATS_STATUSSEN } from './verplaatsen'

const BRON = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOEL = 'aaaaaaaa-0000-0000-0000-000000000002'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function installFetchMock(opties: { verplaatsAanroepen?: { url: string; body: unknown }[]; verplaatsStatus?: number; detail?: string }) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/auth/administraties')) {
        return Promise.resolve(
          jsonResponse({
            administraties: [
              { id: BRON, naam: 'ARVUM B.V.' },
              { id: DOEL, naam: 'Port of Rotterdam N.V.' },
              { id: 'aaaaaaaa-0000-0000-0000-000000000003', naam: 'Kempen Facilities B.V.' },
            ],
          }),
        )
      }
      if (url.endsWith('/verplaats') && init?.method === 'POST') {
        opties.verplaatsAanroepen?.push({ url, body: JSON.parse(String(init.body)) })
        if (opties.verplaatsStatus && opties.verplaatsStatus >= 400) {
          return Promise.resolve(jsonResponse({ detail: opties.detail ?? 'Nee' }, opties.verplaatsStatus))
        }
        return Promise.resolve(
          jsonResponse({
            document_id: DOCUMENT_ID,
            status: 'te_controleren',
            van_administratie_id: BRON,
            van_administratie_naam: 'ARVUM B.V.',
            naar_administratie_id: DOEL,
            naar_administratie_naam: 'Port of Rotterdam N.V.',
            leerregels_gecorrigeerd: ['tenaamstelling'],
            vragen_verhuisd: 0,
            vragen_hertoegewezen: 0,
          }),
        )
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
}

describe('redenNietVerplaatsbaar (spiegel van app/documenten/verplaatsen.py)', () => {
  it('kantoorbak-statussen mogen; geboekt en ter_accordering leggen uit waarom niet', () => {
    for (const status of VERPLAATS_STATUSSEN) expect(redenNietVerplaatsbaar(status, 'inkoopfactuur')).toBeNull()
    expect(redenNietVerplaatsbaar('geboekt', 'inkoopfactuur')).toMatch(/storno|Tegenboeken/)
    expect(redenNietVerplaatsbaar('ter_accordering', 'inkoopfactuur')).toMatch(/trek de accordering eerst in/)
    expect(redenNietVerplaatsbaar('extractie_bezig', 'inkoopfactuur')).toMatch(/loopt nog/)
    expect(redenNietVerplaatsbaar('te_controleren', 'kassarapport')).toMatch(/Alleen inkoopfacturen/)
  })
})

describe('VerplaatsModal (addendum 27-08 punt 5)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('biedt de andere administraties in de doorzoekbare combobox (huidige uitgesloten) en POST het gekozen doel', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: { url: string; body: unknown }[] = []
    installFetchMock({ verplaatsAanroepen: aanroepen })
    const onVerplaatst = vi.fn()
    render(
      <VerplaatsModal
        administratieId={BRON}
        administratieNaam="ARVUM B.V."
        documentId={DOCUMENT_ID}
        bestandsnaam="factuur-4711.pdf"
        openVragen={1}
        onVerplaatst={onVerplaatst}
        onAnnuleren={() => {}}
      />,
    )
    expect(screen.getByRole('dialog', { name: 'Verplaats naar andere administratie' })).toBeInTheDocument()
    // Consequenties staan vooraf uitgelegd.
    expect(screen.getByText(/extractie draait opnieuw/)).toBeInTheDocument()
    expect(screen.getByText(/toewijzings-geheugen leert mee/)).toBeInTheDocument()
    expect(screen.getByText(/De open vraag verhuist mee/)).toBeInTheDocument()

    const knop = screen.getByRole('button', { name: 'Verplaatsen' })
    expect(knop).toBeDisabled()

    const veld = screen.getByRole('combobox', { name: /Doeladministratie/ })
    await gebruiker.click(veld)
    await gebruiker.type(veld, 'Rotter')
    const optie = await screen.findByRole('option', { name: 'Port of Rotterdam N.V.' })
    expect(screen.queryByRole('option', { name: 'ARVUM B.V.' })).not.toBeInTheDocument()
    await gebruiker.click(optie)

    const verstuur = screen.getByRole('button', { name: 'Verplaatsen naar Port of Rotterdam N.V.' })
    expect(verstuur).toBeEnabled()
    await gebruiker.click(verstuur)

    await waitFor(() => expect(onVerplaatst).toHaveBeenCalledTimes(1))
    expect(aanroepen).toHaveLength(1)
    expect(aanroepen[0].url).toBe(`/administraties/${BRON}/documenten/${DOCUMENT_ID}/verplaats`)
    expect(aanroepen[0].body).toEqual({ doel_administratie_id: DOEL })
    expect(onVerplaatst.mock.calls[0][0]).toMatchObject({ naar_administratie_id: DOEL, leerregels_gecorrigeerd: ['tenaamstelling'] })
  })

  it('toont de server-uitleg (409) zichtbaar in de modal en blijft open', async () => {
    const gebruiker = userEvent.setup()
    installFetchMock({ verplaatsStatus: 409, detail: 'Het document ligt bij de klant ter accordering — trek de accordering eerst in.' })
    const onVerplaatst = vi.fn()
    render(
      <VerplaatsModal
        administratieId={BRON}
        administratieNaam="ARVUM B.V."
        documentId={DOCUMENT_ID}
        bestandsnaam="factuur.pdf"
        openVragen={0}
        onVerplaatst={onVerplaatst}
        onAnnuleren={() => {}}
      />,
    )
    const veld = screen.getByRole('combobox', { name: /Doeladministratie/ })
    await gebruiker.click(veld)
    await gebruiker.click(await screen.findByRole('option', { name: 'Port of Rotterdam N.V.' }))
    await gebruiker.click(screen.getByRole('button', { name: /^Verplaatsen naar/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/trek de accordering eerst in/)
    expect(onVerplaatst).not.toHaveBeenCalled()
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
