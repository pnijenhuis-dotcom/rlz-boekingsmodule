/** Veldwerkers-run 14-09 — regressievangnet tegen kolom-implosie op /veldwerkers (zelfde discipline als
 * `gebruikers/gebruikersKolommen.test.tsx`). Jsdom kent geen layout: dit toetst de BRON (geheel px-minimum per kolom,
 * unieke sleutels, acties als laatste, som ≤ beschikbare breedte op 1440); de échte pixels meet
 * `scripts/overflow_sweep.sh` met `harness-veldwerkers.html` (+ `?breed=1`) in headless Chrome. */
import { describe, expect, it } from 'vitest'
import { beschikbareBreedte } from '../gebruikers/gebruikersKolommen'
import { VELDWERKERS_KOLOMMEN, minimaleVeldwerkersTabelbreedte } from './veldwerkersKolommen'

describe('veldwerkersKolommen — de bron', () => {
  it('kolommen in de besloten volgorde: Veldwerker · Rol · Koppelingen · Dossier · Status · acties', () => {
    expect(VELDWERKERS_KOLOMMEN.map((k) => k.sleutel)).toEqual(['veldwerker', 'rol', 'koppelingen', 'dossier', 'status', 'acties'])
    expect(VELDWERKERS_KOLOMMEN.map((k) => k.kop)).toEqual(['Veldwerker', 'Rol', 'Koppelingen', 'Dossier', 'Status', ''])
  })

  it('elke kolom heeft een geheel px-minimum ≥ 100 (acties ≥ 150: één knop + ⋯) en een unieke sleutel', () => {
    const sleutels = new Set<string>()
    for (const k of VELDWERKERS_KOLOMMEN) {
      expect(Number.isInteger(k.minPx), k.sleutel).toBe(true)
      expect(k.minPx, `${k.sleutel} te smal`).toBeGreaterThanOrEqual(k.sleutel === 'acties' ? 150 : 100)
      expect(sleutels.has(k.sleutel), `dubbele sleutel ${k.sleutel}`).toBe(false)
      sleutels.add(k.sleutel)
    }
    expect(VELDWERKERS_KOLOMMEN.at(-1)?.sleutel).toBe('acties')
  })

  it('de tabel-min-width is exact de som van de kolomminima en past op 1440 zonder interne scroll', () => {
    const som = VELDWERKERS_KOLOMMEN.reduce((s, k) => s + k.minPx, 0)
    expect(minimaleVeldwerkersTabelbreedte()).toBe(som)
    expect(som, `${som} > ${beschikbareBreedte(1440)}`).toBeLessThanOrEqual(beschikbareBreedte(1440))
  })

  it('op 1170 past de tabel NIET zonder interne scroll (gedocumenteerd feit, geen wens) — het tekort blijft kleiner dan één kolom', () => {
    // Zou dit ooit wél passen (kolommen geschrapt/versmald), dan mag deze assertie omgekeerd worden.
    expect(minimaleVeldwerkersTabelbreedte()).toBeGreaterThan(beschikbareBreedte(1170))
    expect(minimaleVeldwerkersTabelbreedte() - beschikbareBreedte(1170)).toBeLessThan(Math.max(...VELDWERKERS_KOLOMMEN.map((k) => k.minPx)))
  })
})
