import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CrediteurDubbelen } from './CrediteurDubbelen'

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

async function kiesAdministratie(gebruiker: ReturnType<typeof userEvent.setup>) {
  await gebruiker.click(screen.getByLabelText('Administratie'))
  await gebruiker.click(await screen.findByRole('option', { name: 'Kempen Facilities B.V.' }))
}

describe('CrediteurDubbelen (punt 14, opruimrun 28-08)', () => {
  afterEach(() => vi.restoreAllMocks())

  it('toont groepen per soort met crediteuren, nummers en IBAN — nummer-groepen eerst; KvK-knop haalt de officiële naam', async () => {
    const aanroepen: string[] = []
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input)
      aanroepen.push(url)
      if (url.endsWith('/crediteuren/dubbelen')) {
        return Promise.resolve(
          jsonResponse({
            aantal_crediteuren: 209,
            groepen: [
              {
                soort: 'kvk_nummer',
                sleutel: '12345678',
                crediteuren: [
                  { vendor_id: 'v-1-aaaaaaaa', naam: 'Wola B.V.', btw_nummer: 'NL123456782B01', kvk_nummer: '12345678', ibans: ['NL91ABNA0417164300'] },
                  { vendor_id: 'v-2-bbbbbbbb', naam: 'Wola b.v.', btw_nummer: null, kvk_nummer: '12345678', ibans: [] },
                ],
              },
              {
                soort: 'naam',
                sleutel: 'coolblue',
                crediteuren: [
                  { vendor_id: 'v-3-cccccccc', naam: 'Coolblue', btw_nummer: null, kvk_nummer: null, ibans: [] },
                  { vendor_id: 'v-4-dddddddd', naam: 'Coolblue B.V.', btw_nummer: null, kvk_nummer: null, ibans: [] },
                ],
              },
            ],
          }),
        )
      }
      if (url.includes('/crediteuren/kvk/12345678')) {
        return Promise.resolve(
          jsonResponse({ kvk_nummer: '12345678', gevonden: true, naam: 'Wola Holding B.V.', rechtsvorm: 'Besloten Vennootschap', plaats: 'Eindhoven', uitgeschreven: false, testomgeving: true }),
        )
      }
      return Promise.resolve(jsonResponse({ detail: 'onbekend' }, 404))
    })
    const gebruiker = userEvent.setup()
    render(<CrediteurDubbelen administraties={[{ id: ADM, naam: 'Kempen Facilities B.V.' }]} />)
    expect(screen.getByText(/Kies een administratie/)).toBeInTheDocument()
    await kiesAdministratie(gebruiker)

    expect(await screen.findByText(/2 groepen onder 209 actieve crediteuren/)).toBeInTheDocument()
    const rijen = screen.getAllByRole('row').slice(1)
    expect(rijen[0]).toHaveTextContent('zelfde KvK-nummer')
    expect(rijen[0]).toHaveTextContent('Wola B.V.')
    expect(rijen[0]).toHaveTextContent('NL123456782B01')
    expect(rijen[0]).toHaveTextContent('NL91ABNA0417164300')
    expect(rijen[1]).toHaveTextContent('zelfde naam')
    expect(rijen[1]).toHaveTextContent('Coolblue B.V.')
    // Geen verwijder-/samenvoegknop — alleen signaleren.
    expect(screen.queryByRole('button', { name: /samenvoegen|verwijder/i })).not.toBeInTheDocument()

    await gebruiker.click(screen.getByRole('button', { name: 'KvK controleren' }))
    expect(await screen.findByText('Wola Holding B.V.')).toBeInTheDocument()
    expect(screen.getByText(/KvK-testomgeving/)).toBeInTheDocument()
    expect(aanroepen.some((u) => u.includes(`/administraties/${ADM}/crediteuren/kvk/12345678`))).toBe(true)
  })

  it('meldt "geen dubbelen" expliciet', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ aantal_crediteuren: 12, groepen: [] }))
    const gebruiker = userEvent.setup()
    render(<CrediteurDubbelen administraties={[{ id: ADM, naam: 'Kempen Facilities B.V.' }]} />)
    await kiesAdministratie(gebruiker)
    await waitFor(() => expect(screen.getByText(/Geen dubbelen gevonden onder 12 actieve crediteuren/)).toBeInTheDocument())
  })
})
