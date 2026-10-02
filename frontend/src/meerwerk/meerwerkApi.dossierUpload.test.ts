import { afterEach, describe, expect, it, vi } from 'vitest'
import { uploadDossierDocument } from './meerwerkApi'

// Punt 15 run A 02-10 — kantoor (DossierModal): dezelfde helper als de veld-app; de verstuurde `geldig_tot` is ISO.
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function laatsteBody(mock: { mock: { calls: unknown[][] } }): FormData {
  const init = mock.mock.calls.at(-1)?.[1] as RequestInit
  return init.body as FormData
}

const BESTAND = new File([new Uint8Array([37, 80, 68, 70])], 'kvk.pdf', { type: 'application/pdf' })

afterEach(() => vi.unstubAllGlobals())

describe('uploadDossierDocument (kantoor)', () => {
  it.each([
    ['jjjj-mm-dd', '2026-12-31'],
    ['dd-mm-jjjj', '31-12-2026'],
    ['dd/mm/jjjj', '31/12/2026'],
  ])('stuurt geldig_tot als ISO bij invoer %s', async (_vorm, invoer) => {
    const mock = vi.fn((_u: RequestInfo | URL, _i?: RequestInit) => Promise.resolve(jsonResponse({ documenten: [] })))
    vi.stubGlobal('fetch', mock)
    await uploadDossierDocument('adm', 'gebr', { type_code: 'kvk_uittreksel', geldig_tot: invoer, bestand: BESTAND })
    expect(laatsteBody(mock).get('geldig_tot')).toBe('2026-12-31')
    expect(String(mock.mock.calls.at(-1)?.[0])).toContain('/uren/kantoor/dossier/adm/gebr/upload')
  })

  it('toont de 422-tekst van de server letterlijk (contract scherm ↔ server)', async () => {
    const detail = "Geldig tot: '31.12.2026' is geen geldige datum — schrijf de datum als 31-12-2026"
    vi.stubGlobal('fetch', vi.fn((_u: RequestInfo | URL, _i?: RequestInit) => Promise.resolve(jsonResponse({ detail }, 422))))
    // De helper vangt dit al vóór verzenden; forceer de serverroute met een ISO-waarde die de server afkeurt.
    await expect(uploadDossierDocument('adm', 'gebr', { type_code: 'kvk_uittreksel', geldig_tot: '2026-12-31', bestand: BESTAND })).rejects.toThrow(detail)
  })

  it('verstuurt niets bij een onherkenbare datum', async () => {
    const mock = vi.fn((_u: RequestInfo | URL, _i?: RequestInit) => Promise.resolve(jsonResponse({ documenten: [] })))
    vi.stubGlobal('fetch', mock)
    await expect(uploadDossierDocument('adm', 'gebr', { type_code: 'kvk_uittreksel', geldig_tot: 'morgen', bestand: BESTAND })).rejects.toThrow(
      'schrijf de datum als 31-12-2026',
    )
    expect(mock).not.toHaveBeenCalled()
  })
})
