import { describe, expect, it } from 'vitest'
import { KOLOM_PX, OMSCHRIJVING_MIN_PX, minimaleTabelbreedte } from './boekingsregelsKolommen'

/** Addendum kantoor-run 27-08 punt 4 — regressievangnet kolom-implosie. De overflow-sweep meet
 * pagina-overflow en ziet een per-letter-brekende omschrijving-kolom niet; deze test bewaakt de
 * minimumbreedtes die de leesbaarheid in een smal paneel garanderen. */
describe('boekingsregelsKolommen (punt 4, tabel-implosie)', () => {
  it('elke kolom heeft een absolute minimumbreedte in px — nooit meer procenten van een te smalle tabel', () => {
    for (const [naam, px] of Object.entries(KOLOM_PX)) {
      expect(Number.isInteger(px), `${naam} moet een geheel aantal px zijn`).toBe(true)
      expect(px, `${naam} te smal`).toBeGreaterThan(0)
    }
    // Zoekvelden moeten bruikbaar blijven: code + begin van de omschrijving zichtbaar.
    expect(KOLOM_PX.grootboek).toBeGreaterThanOrEqual(140)
    expect(KOLOM_PX.btw).toBeGreaterThanOrEqual(110)
    expect(KOLOM_PX.project).toBeGreaterThanOrEqual(130)
    // Geld altijd volledig leesbaar ("123.456,78" incl. paddings — bestaande norm 104 px).
    expect(KOLOM_PX.netto).toBeGreaterThanOrEqual(104)
    expect(KOLOM_PX.btwBedrag).toBeGreaterThanOrEqual(104)
  })

  it('de omschrijving-kolom heeft een ondergrens waarop gewone woorden op woordgrenzen wrappen (≥ 160 px)', () => {
    expect(OMSCHRIJVING_MIN_PX).toBeGreaterThanOrEqual(160)
  })

  it('de tabel-min-width is exact de som van de kolomminima — met en zonder projectkolom', () => {
    const zonder = KOLOM_PX.grootboek + KOLOM_PX.btw + KOLOM_PX.netto + KOLOM_PX.btwBedrag + KOLOM_PX.verwijder + OMSCHRIJVING_MIN_PX
    expect(minimaleTabelbreedte(false)).toBe(zonder)
    expect(minimaleTabelbreedte(true)).toBe(zonder + KOLOM_PX.project)
    // Sanity: onder deze breedte scrollt .tabel-scroll horizontaal i.p.v. kolommen te pletten.
    expect(minimaleTabelbreedte(false)).toBeGreaterThan(560) // de oude, te lage vaste min-width
  })
})
