import { describe, expect, it } from 'vitest'
import { isCompact } from './compacteRegels'
import { minimaleTabelbreedte } from './boekingsregelsKolommen'

/** Punt 7 run A (02-10): de omschakeling naar de compacte regelweergave is een pure functie van containerbreedte en
 * kolomminima-som — de gemeten pane-breedtes van 02-10 (530/591/632 px op 1280/1385/1455 px) zijn de regressiegevallen. */
describe('compacteRegels.isCompact', () => {
  it('de gemeten formulier-panes van 1280/1385/1455 px zijn compact, mét en zónder projectplicht', () => {
    for (const breedte of [530, 591, 632]) {
      expect(isCompact(breedte, minimaleTabelbreedte(false))).toBe(true)
      expect(isCompact(breedte, minimaleTabelbreedte(true))).toBe(true)
    }
  })

  it('op of boven de som van de kolomminima blijft de brede tabel staan', () => {
    expect(isCompact(minimaleTabelbreedte(false), minimaleTabelbreedte(false))).toBe(false)
    expect(isCompact(1200, minimaleTabelbreedte(true))).toBe(false)
  })

  it('een container zonder maat (nog niet gelayout) is nooit compact', () => {
    expect(isCompact(0, minimaleTabelbreedte(false))).toBe(false)
  })
})
