import { describe, expect, it } from 'vitest'
import { rondesPreviewTekst, rondesTekst } from './rondesTekst'

describe('rondesTekst — herberekenen i.p.v. vervallen (bundel 09-09 blok 2)', () => {
  it('niets geraakt = geen tekst', () => {
    expect(rondesPreviewTekst(0, 0)).toBe('')
    expect(rondesTekst(0, 0)).toBe('')
  })

  it('vooraf: "N rondes worden herberekend, waarvan M vervallen"', () => {
    expect(rondesPreviewTekst(3, 1)).toBe(
      '3 lopende accorderingsrondes worden herberekend, waarvan 1 vervalt (geen enkel gegeven akkoord past daar nog; die documenten gaan terug naar "Klaar om te boeken")',
    )
    expect(rondesPreviewTekst(1, 0)).toContain('1 lopende accorderingsronde wordt herberekend')
    expect(rondesPreviewTekst(1, 0)).not.toContain('vervalt')
    expect(rondesPreviewTekst(2, 2)).toContain('waarvan 2 vervallen')
  })

  it('achteraf: herberekend + eventueel vervallen-deel mét actie', () => {
    expect(rondesTekst(2, 0)).toBe(
      ' 2 lopende accorderingsrondes herberekend: gegeven akkoorden blijven staan, ontbrekende lagen zijn opnieuw aangevraagd.',
    )
    expect(rondesTekst(2, 1)).toContain('1 daarvan is vervallen')
    expect(rondesTekst(2, 1)).toContain('"Klaar om te boeken"')
    expect(rondesTekst(3, 2)).toContain('2 daarvan zijn vervallen')
  })
})
