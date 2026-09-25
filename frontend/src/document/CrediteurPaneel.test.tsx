import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CrediteurPaneel, IBAN_ONTBREEKT_TEKST, adresUitRegel } from './CrediteurPaneel'

/* Blok 5 feedbackrun 25-09 — FV-14 (zijpaneel i.p.v. modale dialoog, prefill uit factuur/UBL incl. adres, IBAN-ontbreekt-
 * waarschuwing) + FV-15 (bewerk-modus zonder IBAN-veld, IBAN via de wisselroute, PUT op het bestaande id). */

const ADM = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOC = 'bbbbbbbb-0000-0000-0000-000000000001'
const VENDOR = 'eeeeeeee-0000-0000-0000-000000000001'

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

afterEach(() => vi.unstubAllGlobals())

describe('adresUitRegel', () => {
  it('splitst de UBL-adresregel deterministisch in velden', () => {
    expect(adresUitRegel('Kantoorlaan 12, 5611 AB Eindhoven, NL')).toEqual({
      straat: 'Kantoorlaan 12',
      postcode: '5611 AB',
      plaats: 'Eindhoven',
      land: 'NL',
    })
    expect(adresUitRegel('Kantoorlaan 12, Eindhoven')).toEqual({ straat: 'Kantoorlaan 12', postcode: '', plaats: 'Eindhoven', land: '' })
    expect(adresUitRegel(null)).toEqual({ straat: '', postcode: '', plaats: '', land: '' })
  })
})

describe('CrediteurPaneel — nieuw (FV-14)', () => {
  it('is een niet-modaal zijpaneel (geen overlay, aria-modal=false) mét prefill uit de UBL incl. adres en chips', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: unknown[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/crediteuren') && init?.method === 'POST') {
          aanroepen.push(JSON.parse(String(init.body)))
          return Promise.resolve(jsonResponse({ id: VENDOR, naam: 'BDO', waarschuwingen: [] }, 201))
        }
        return Promise.reject(new Error(`onverwacht: ${url}`))
      }),
    )
    const onAangemaakt = vi.fn()
    render(
      <div>
        <div data-testid="factuur-viewer">factuurbeeld</div>
        <CrediteurPaneel
          administratieId={ADM}
          documentId={DOC}
          voorgevuld={{ naam: 'BDO Accountancy', kvk_nummer: '91000006', btw_nummer: 'NL100039595B01', iban: 'NL95KETN1000000010' }}
          herkomst={{ kvk: true, btw: true, iban: true, adres: true }}
          bron="UBL"
          adres="Philitelaan 40, 5617 AL Eindhoven, NL"
          onAangemaakt={onAangemaakt}
          onBestaand={() => {}}
          onSluit={() => {}}
        />
      </div>,
    )
    const paneel = screen.getByRole('dialog')
    expect(paneel).toHaveAttribute('aria-modal', 'false')
    expect(paneel.tagName).toBe('ASIDE')
    // Geen Radix-overlay: de viewer blijft gewoon in de DOM bereikbaar (niet aria-hidden, niet afgedekt).
    expect(document.querySelector('[data-radix-dialog-overlay], .fixed.inset-0')).toBeNull()
    expect(screen.getByTestId('factuur-viewer')).not.toHaveAttribute('aria-hidden')
    expect(within(paneel).getByLabelText('Naam')).toHaveValue('BDO Accountancy')
    expect(within(paneel).getByLabelText('Straat en huisnummer')).toHaveValue('Philitelaan 40')
    expect(within(paneel).getByLabelText('Postcode')).toHaveValue('5617 AL')
    expect(within(paneel).getByLabelText('Plaats')).toHaveValue('Eindhoven')
    expect(within(paneel).getByLabelText('Land (code)')).toHaveValue('NL')
    expect(within(paneel).getAllByText('uit UBL').length).toBeGreaterThanOrEqual(4)
    expect(within(paneel).queryByTestId('crediteur-iban-ontbreekt')).not.toBeInTheDocument()

    await gebruiker.click(within(paneel).getByRole('button', { name: 'Aanmaken in RLZ ✓' }))
    await waitFor(() => expect(onAangemaakt).toHaveBeenCalled())
    expect(aanroepen).toEqual([
      {
        naam: 'BDO Accountancy',
        kvk_nummer: '91000006',
        btw_nummer: 'NL100039595B01',
        adres: { straat: 'Philitelaan 40', postcode: '5617 AL', plaats: 'Eindhoven', land: 'NL' },
        iban: 'NL95KETN1000000010',
        document_id: DOC,
      },
    ])
  })

  it('ontbrekend IBAN = waarschuwing, geen blokkade (de knop blijft aan, de POST gaat zonder iban)', async () => {
    const gebruiker = userEvent.setup()
    const aanroepen: Record<string, unknown>[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((_url: string, init?: RequestInit) => {
        aanroepen.push(JSON.parse(String(init?.body)))
        return Promise.resolve(jsonResponse({ id: VENDOR, naam: 'Confide BV', waarschuwingen: ['geen IBAN vastgelegd — …'] }, 201))
      }),
    )
    const onAangemaakt = vi.fn()
    render(
      <CrediteurPaneel
        administratieId={ADM}
        documentId={DOC}
        voorgevuld={{ naam: 'Confide BV', kvk_nummer: null, btw_nummer: null, iban: null }}
        herkomst={{}}
        onAangemaakt={onAangemaakt}
        onBestaand={() => {}}
        onSluit={() => {}}
      />,
    )
    expect(screen.getByTestId('crediteur-iban-ontbreekt')).toHaveTextContent(IBAN_ONTBREEKT_TEKST)
    const knop = screen.getByRole('button', { name: 'Aanmaken in RLZ ✓' })
    expect(knop).toBeEnabled()
    await gebruiker.click(knop)
    await waitFor(() => expect(onAangemaakt).toHaveBeenCalled())
    expect(aanroepen[0]).toMatchObject({ naam: 'Confide BV', iban: null })
    expect(aanroepen[0]).not.toHaveProperty('adres')
  })

  it('Escape en ✕ sluiten het paneel', async () => {
    const gebruiker = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn())
    const onSluit = vi.fn()
    render(
      <CrediteurPaneel
        administratieId={ADM}
        documentId={DOC}
        voorgevuld={{ naam: '', kvk_nummer: null, btw_nummer: null, iban: null }}
        herkomst={{}}
        onAangemaakt={() => {}}
        onBestaand={() => {}}
        onSluit={onSluit}
      />,
    )
    await gebruiker.click(screen.getByRole('button', { name: 'Paneel sluiten' }))
    expect(onSluit).toHaveBeenCalledTimes(1)
    await gebruiker.type(screen.getByLabelText('Naam'), '{Escape}')
    expect(onSluit).toHaveBeenCalledTimes(2)
  })
})

describe('CrediteurPaneel — bewerken (FV-15)', () => {
  it('laadt de crediteur, toont IBANs lees-only zónder IBAN-veld, en slaat op via PUT op het bestaande id', async () => {
    const gebruiker = userEvent.setup()
    const puts: { url: string; body: Record<string, unknown> }[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith(`/crediteuren/${VENDOR}`) && (!init || !init.method)) {
          return Promise.resolve(
            jsonResponse({
              id: VENDOR,
              naam: 'Floor Bouwliftenservice',
              kvk_nummer: '12345678',
              btw_nummer: null,
              adres: { straat: 'Liftweg 1', postcode: '1234 AB', plaats: 'Ede', land: 'NL', regel: 'Liftweg 1, 1234 AB Ede, NL' },
              vertrouwde_ibans: ['NL91ABNA0417164300'],
              backend: 'rlz',
            }),
          )
        }
        if (url.endsWith(`/crediteuren/${VENDOR}`) && init?.method === 'PUT') {
          puts.push({ url, body: JSON.parse(String(init.body)) })
          return Promise.resolve(jsonResponse({ id: VENDOR, naam: 'Floor Bouwliftenservice B.V.', waarschuwingen: [] }))
        }
        return Promise.reject(new Error(`onverwacht: ${url}`))
      }),
    )
    const onGewijzigd = vi.fn()
    const onIbanRoute = vi.fn()
    const onSluit = vi.fn()
    render(
      <CrediteurPaneel
        administratieId={ADM}
        documentId={DOC}
        modus="bewerken"
        vendorId={VENDOR}
        voorgevuld={{ naam: 'Floor Bouwliftenservice', kvk_nummer: null, btw_nummer: null, iban: null }}
        herkomst={{}}
        onAangemaakt={() => {}}
        onBestaand={() => {}}
        onGewijzigd={onGewijzigd}
        onIbanRoute={onIbanRoute}
        onSluit={onSluit}
      />,
    )
    const paneel = screen.getByRole('dialog')
    expect(within(paneel).getByRole('heading', { name: 'Crediteurgegevens bewerken' })).toBeInTheDocument()
    await waitFor(() => expect(within(paneel).getByLabelText('KvK-nummer')).toHaveValue('12345678'))
    expect(within(paneel).getByLabelText('Straat en huisnummer')).toHaveValue('Liftweg 1')
    // Géén vrij IBAN-veld in bewerk-modus; wél de vertrouwde set lees-only + de route.
    expect(within(paneel).queryByLabelText(/IBAN/)).not.toBeInTheDocument()
    expect(within(paneel).getByTestId('crediteur-ibans-leesonly')).toHaveTextContent('NL91ABNA0417164300')
    expect(within(paneel).queryByTestId('crediteur-iban-ontbreekt')).not.toBeInTheDocument()

    await gebruiker.clear(within(paneel).getByLabelText('Naam'))
    await gebruiker.type(within(paneel).getByLabelText('Naam'), 'Floor Bouwliftenservice B.V.')
    await gebruiker.click(within(paneel).getByRole('button', { name: 'Opslaan in RLZ ✓' }))
    await waitFor(() => expect(onGewijzigd).toHaveBeenCalled())
    expect(puts).toHaveLength(1)
    expect(puts[0].url).toContain(`/administraties/${ADM}/crediteuren/${VENDOR}`)
    expect(puts[0].body).toEqual({
      naam: 'Floor Bouwliftenservice B.V.',
      kvk_nummer: '12345678',
      btw_nummer: null,
      adres: { straat: 'Liftweg 1', postcode: '1234 AB', plaats: 'Ede', land: 'NL' },
    })
    expect(puts[0].body).not.toHaveProperty('iban')

    await gebruiker.click(within(paneel).getByTestId('crediteur-iban-route'))
    expect(onIbanRoute).toHaveBeenCalledTimes(1)
    expect(onSluit).toHaveBeenCalled()
  })

  it('bewerken zonder vertrouwd IBAN toont de waarschuwing (niet blokkerend)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          jsonResponse({
            id: VENDOR,
            naam: 'Floor',
            kvk_nummer: null,
            btw_nummer: null,
            adres: { straat: null, postcode: null, plaats: null, land: null, regel: null },
            vertrouwde_ibans: [],
            backend: 'rlz',
          }),
        ),
      ),
    )
    render(
      <CrediteurPaneel
        administratieId={ADM}
        documentId={DOC}
        modus="bewerken"
        vendorId={VENDOR}
        voorgevuld={{ naam: 'Floor', kvk_nummer: null, btw_nummer: null, iban: null }}
        herkomst={{}}
        onAangemaakt={() => {}}
        onBestaand={() => {}}
        onSluit={() => {}}
      />,
    )
    await waitFor(() => expect(screen.getByTestId('crediteur-iban-ontbreekt')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Opslaan in RLZ ✓' })).toBeEnabled()
  })
})
