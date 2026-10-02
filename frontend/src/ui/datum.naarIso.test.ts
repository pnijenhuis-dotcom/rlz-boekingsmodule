import { describe, expect, it } from 'vitest'
import { DATUM_FOUT_TEKST, naarIsoDatum, OngeldigeDatumFout } from './datum'

// Punt 15 run A 02-10 — Peter: KvK-upload gaf "geldig_tot: … invalid date separator, expected `-`". Dé ene
// normalisatie vóór verzenden: drie vormen → ISO; leeg → null; onherkenbaar → fout in gewone taal.
describe('naarIsoDatum', () => {
  it('laat een geldige ISO-waarde ongewijzigd door', () => {
    expect(naarIsoDatum('2026-12-31')).toBe('2026-12-31')
  })

  it('vertaalt dd-mm-jjjj en dd/mm/jjjj naar ISO', () => {
    expect(naarIsoDatum('31-12-2026')).toBe('2026-12-31')
    expect(naarIsoDatum('31/12/2026')).toBe('2026-12-31')
    expect(naarIsoDatum(' 5-1-2026 ')).toBe('2026-01-05')
  })

  it('leeg/null/undefined → null (de aanroeper beslist over verplicht)', () => {
    expect(naarIsoDatum('')).toBeNull()
    expect(naarIsoDatum('   ')).toBeNull()
    expect(naarIsoDatum(null)).toBeNull()
    expect(naarIsoDatum(undefined)).toBeNull()
  })

  it('neemt ook de soepele blur-vormen van de DatePicker mee (punt-scheidingsteken, ddmmjjjj)', () => {
    expect(naarIsoDatum('31.12.2026')).toBe('2026-12-31')
    expect(naarIsoDatum('31122026')).toBe('2026-12-31')
  })

  it('weigert rommel en niet-bestaande dagen mét de tekst van de backend', () => {
    for (const ruw of ['2026-02-30', '31-02-2026', 'morgen', '12/31/2026x', '2026/12/31']) {
      let fout: unknown
      try {
        naarIsoDatum(ruw, 'Geldig tot')
      } catch (e) {
        fout = e
      }
      expect(fout).toBeInstanceOf(OngeldigeDatumFout)
      expect((fout as Error).message).toBe(`Geldig tot: '${ruw}' ${DATUM_FOUT_TEKST}`)
      expect((fout as Error).message).toContain('schrijf de datum als 31-12-2026')
    }
  })
})
