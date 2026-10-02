import { afterEach, describe, expect, it, vi } from 'vitest'
import { uploadDossierDocument } from './urenApi'

// Punt 15 run A 02-10 — veld-app (UrenFlow › dossier): de verstuurde `geldig_tot` is ALTIJD ISO, ongeacht hoe de
// datum getypt werd; een onherkenbare datum gaat de lijn niet op maar wordt een leesbare fout.
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function laatsteBody(mock: { mock: { calls: unknown[][] } }): FormData {
  const init = mock.mock.calls.at(-1)?.[1] as RequestInit
  return init.body as FormData
}

const BESTAND = new File([new Uint8Array([37, 80, 68, 70])], 'kvk.pdf', { type: 'application/pdf' })

afterEach(() => vi.unstubAllGlobals())

describe('uploadDossierDocument (veld-app)', () => {
  it.each([
    ['jjjj-mm-dd', '2026-12-31'],
    ['dd-mm-jjjj', '31-12-2026'],
    ['dd/mm/jjjj', '31/12/2026'],
  ])('stuurt geldig_tot als ISO bij invoer %s', async (_vorm, invoer) => {
    const mock = vi.fn((_u: RequestInfo | URL, _i?: RequestInit) => Promise.resolve(jsonResponse({ documenten: [] })))
    vi.stubGlobal('fetch', mock)
    await uploadDossierDocument({ administratie_id: 'adm', type_code: 'kvk_uittreksel', geldig_tot: invoer, namens: null, bestand: BESTAND })
    const body = laatsteBody(mock)
    expect(body.get('geldig_tot')).toBe('2026-12-31')
    expect(body.get('type_code')).toBe('kvk_uittreksel')
    expect(String(mock.mock.calls.at(-1)?.[0])).toContain('/uren/dossier/upload')
  })

  it('laat geldig_tot weg als het leeg is (afwezig-pad ongewijzigd)', async () => {
    const mock = vi.fn((_u: RequestInfo | URL, _i?: RequestInit) => Promise.resolve(jsonResponse({ documenten: [] })))
    vi.stubGlobal('fetch', mock)
    await uploadDossierDocument({ administratie_id: 'adm', type_code: 'steigerpas', geldig_tot: null, namens: null, bestand: BESTAND })
    expect(laatsteBody(mock).has('geldig_tot')).toBe(false)
  })

  it('verstuurt niets bij een onherkenbare datum en geeft de melding in gewone taal', async () => {
    const mock = vi.fn((_u: RequestInfo | URL, _i?: RequestInit) => Promise.resolve(jsonResponse({ documenten: [] })))
    vi.stubGlobal('fetch', mock)
    await expect(
      uploadDossierDocument({ administratie_id: 'adm', type_code: 'kvk_uittreksel', geldig_tot: '31-02-2027', namens: null, bestand: BESTAND }),
    ).rejects.toThrow("Geldig tot: '31-02-2027' is geen geldige datum — schrijf de datum als 31-12-2026")
    expect(mock).not.toHaveBeenCalled()
  })
})
