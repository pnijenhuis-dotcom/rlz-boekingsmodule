import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BETAALSTATUS_OPTIES_FALLBACK, BoekvoorstelPanel } from './BoekvoorstelPanel'

/** BUG Peter 21-09 (Beleggingsmaatschappij Meyer, Belastingdienst 0015.21.664.V.51.0112): de check-rij "IBAN-wissel" stond
 * Blokkerend "gecontroleerd 09:15 (ongewijzigd)" terwijl het aanbieden 409 "staat al in de vertrouwde set" gaf — het scherm
 * sprak zichzelf tegen. Het patroon "check blokkerend + paneel 'al vertrouwd'" is onmogelijk gemaakt: de 409 draait de checks
 * VERS (`?extern=vers`) en de rij wordt groen; daarnaast draagt de "geraadpleegd om HH:MM"-regel een linkbtn
 * "Opnieuw controleren" zodat een mens nooit op de 15-min-klok van de cache hoeft te wachten. */

const ADMINISTRATIE_ID = 'aaaaaaaa-0000-0000-0000-000000000001'
const DOCUMENT_ID = 'bbbbbbbb-0000-0000-0000-000000000002'
const LEDGER_ID = 'cccccccc-0000-0000-0000-000000000003'
const TAXRATE_ID = 'dddddddd-0000-0000-0000-000000000004'
const VENDOR_ID = 'eeeeeeee-0000-0000-0000-000000000005'
const AL_VERTROUWD = 'Dit IBAN staat al in de vertrouwde set van deze crediteur'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const BOEKVOORSTEL = {
  document_id: DOCUMENT_ID,
  vendor_id: VENDOR_ID,
  referentie: '0015.21.664.V.51.0112',
  factuurdatum: '2026-09-15',
  totaalbedrag: '34.00',
  rlz_boekstuknummer: null,
  opgeslagen: true,
  regels: [
    {
      id: null,
      ledger_id: LEDGER_ID,
      taxrate_id: TAXRATE_ID,
      project_id: null,
      netto_bedrag: '34.00',
      btw_bedrag: '0.00',
      omschrijving: 'Voorlopige aanslag Vpb 2025',
    },
  ],
  regels_samenvoegen: false,
  samenvoegen_toegestaan: true,
  samengevoegde_regel: null,
  betaalstatus_opties: BETAALSTATUS_OPTIES_FALLBACK,
}

const GECONTROLEERD = '2026-09-21T07:15:00Z'

function rapport(ibanOk: boolean, uitCache: boolean) {
  return {
    geblokkeerd: !ibanOk,
    resultaten: [
      { naam: 'Verplichte velden', ok: true, melding: 'Alle verplichte velden zijn ingevuld' },
      {
        naam: 'IBAN-wissel',
        ok: ibanOk,
        melding: ibanOk
          ? 'IBAN NL04 **** 2244 komt overeen met een vertrouwde rekening'
          : 'IBAN op de factuur (NL04 **** 2244) wijkt af van de vertrouwde rekening(en) van deze crediteur — mogelijke IBAN-wissel',
      },
      { naam: 'Duplicaatcheck', ok: true, melding: 'Geen duplicaat gevonden' },
    ],
    extern_gecontroleerd_op: GECONTROLEERD,
    extern_uit_cache: uitCache,
    extern_nog_niet: false,
  }
}

interface Mock {
  checksCalls: string[]
  aanbiedenCalls: number
}

function installFetchMock(alVertrouwdStatus: 409 | 400 = 409): Mock {
  const stand: Mock = { checksCalls: [], aanbiedenCalls: 0 }
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/boekingsgeheugen/voorstel') && init?.method === 'POST') {
        return Promise.resolve(new Response(null, { status: 404 }))
      }
      if (url.endsWith('/grootboek')) {
        return Promise.resolve(jsonResponse({ rekeningen: [{ ledger_id: LEDGER_ID, code: '4820', naam: 'Vpb', soort: 2 }] }))
      }
      if (url.endsWith('/btw-codes')) return Promise.resolve(jsonResponse({ btw_codes: [{ id: TAXRATE_ID, naam: 'Geen btw' }] }))
      if (url.endsWith('/crediteuren')) return Promise.resolve(jsonResponse({ crediteuren: [{ id: VENDOR_ID, naam: 'Belastingdienst' }] }))
      if (url.endsWith('/projecten')) return Promise.resolve(jsonResponse({ projecten: [] }))
      if (url.endsWith('/project-instelling')) return Promise.resolve(jsonResponse({ verplicht: false }))
      if (url.endsWith('/boekvoorstel') && (!init || init.method === undefined)) {
        return Promise.resolve(jsonResponse(BOEKVOORSTEL))
      }
      if (url.includes('/boekvoorstel/checks') && init?.method === 'POST') {
        stand.checksCalls.push(url)
        // De cache-stand van 09:15 zegt Blokkerend; alleen een VERSE run ziet het akkoord.
        const vers = url.includes('extern=vers')
        return Promise.resolve(jsonResponse(vers ? rapport(true, false) : rapport(false, true)))
      }
      if (url.endsWith('/iban-accordering') && init?.method === 'POST') {
        stand.aanbiedenCalls += 1
        return Promise.resolve(jsonResponse({ detail: AL_VERTROUWD }, alVertrouwdStatus))
      }
      return Promise.resolve(new Response(null, { status: 404 }))
    }),
  )
  return stand
}

function renderPanel() {
  return render(
    <BoekvoorstelPanel
      administratieId={ADMINISTRATIE_ID}
      documentId={DOCUMENT_ID}
      status="te_controleren"
      onGeboekt={() => {}}
      onHersteld={() => {}}
      onIbanAangeboden={() => {}}
    />,
  )
}

function ibanRij(): HTMLElement | null {
  const cel = screen.queryAllByText('IBAN-wissel').find((el) => el.tagName === 'B')
  return cel ? cel.closest('tr') : null
}

describe('BoekvoorstelPanel — IBAN-wissel ná akkoord: één bron voor check-rij en paneel (BUG 21-09)', () => {
  beforeEach(() => {
    vi.stubGlobal('crypto', { ...globalThis.crypto, randomUUID: () => `local-${Math.random()}` })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  // 23-09 (nameting): de server gaf deze melding tot 23-09 als 400 en dit scherm herkende alleen 409 — in productie kreeg een mens
  // op 23-09 07:50Z de kale fout en géén verse controle. Sinds 23-09 zegt de server 409; 400 blijft herkend voor de overgang.
  it.each([409, 400] as const)('%i "staat al in de vertrouwde set" bij aanbieden → checks vers → IBAN-wissel OK en het aanbieden-paneel verdwijnt', async (statusCode) => {
    const stand = installFetchMock(statusCode)
    renderPanel()
    await waitFor(() => expect(ibanRij()).not.toBeNull())
    expect(ibanRij()).toHaveTextContent('Blokkerend')
    // De verouderde stand komt uit de cache: "(ongewijzigd …)" + de handeling erbij.
    expect(screen.getByTestId('externe-controle-regel')).toHaveTextContent('ongewijzigd')
    const invoer = screen.getByLabelText('Rekeningnummer (IBAN) van de factuur') as HTMLInputElement
    await userEvent.type(invoer, 'NL04RABO0200112244')
    await userEvent.click(screen.getByRole('button', { name: 'Rekening ter accordering aanbieden' }))
    await waitFor(() => expect(stand.aanbiedenCalls).toBe(1))
    // Eén bron: de 409 leidt tot een VERSE controle in plaats van een tegenstrijdig scherm.
    await waitFor(() => expect(stand.checksCalls.some((u) => u.includes('extern=vers'))).toBe(true))
    await waitFor(() => expect(ibanRij()).toHaveTextContent('OK'))
    expect(screen.queryByRole('button', { name: 'Rekening ter accordering aanbieden' })).toBeNull()
    expect(screen.queryByText(/wijkt af van de vertrouwde set/)).toBeNull()
  })

  it('"Opnieuw controleren" op de geraadpleegd-regel draait de externe checks vers (extern=vers)', async () => {
    const stand = installFetchMock()
    renderPanel()
    await waitFor(() => expect(ibanRij()).not.toBeNull())
    const knop = screen.getByRole('button', { name: 'Opnieuw controleren' })
    expect(knop.className).toContain('linkbtn')
    const voor = stand.checksCalls.length
    await userEvent.click(knop)
    await waitFor(() => expect(stand.checksCalls.length).toBeGreaterThan(voor))
    expect(stand.checksCalls[stand.checksCalls.length - 1]).toContain('extern=vers')
    await waitFor(() => expect(ibanRij()).toHaveTextContent('OK'))
    expect(screen.getByTestId('externe-controle-regel')).not.toHaveTextContent('ongewijzigd')
  })
})
