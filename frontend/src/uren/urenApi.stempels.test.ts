import { describe, expect, it } from 'vitest'
import { gestempeldLabel, stempelToets, type DagDto } from './urenApi'

// Blok C 28-08 (mockup geofence-stempels.html §3): kolom "Gestempeld aanwezig" + toets — de
// weergaveregels zijn puur; de rekenkern (paren, middernacht, drempel) staat in de backend.
function dag(over: Partial<DagDto>): DagDto {
  return {
    id: 'd',
    datum: '2026-08-24',
    uren: '8',
    m2: null,
    opmerking: null,
    ingevuld_door_naam: null,
    namens: false,
    voorstel_uren: null,
    voorstel_m2: null,
    voorstel_opmerking: null,
    buiten_planning: false,
    dag_totaal_uren: '8',
    boven_dagmax: false,
    dagmax_uren: null,
    ...over,
  }
}

describe('gestempeldLabel / stempelToets', () => {
  it('sluit aan: label mét tijden en uren, toets ✓', () => {
    const d = dag({ gestempeld_uren: '8.30', stempel_van: '06:55:00', stempel_tot: '15:10:00', stempel_afwijking: false })
    expect(gestempeldLabel(d)).toBe('06:55 – 15:10 (8,3 u)')
    expect(stempelToets(d)).toEqual({ tekst: 'sluit aan', soort: 'ok' })
  })

  it('afwijking: "N u boven stempels — bespreken" (oranje), nooit een korting-tekst', () => {
    const d = dag({ uren: '8', gestempeld_uren: '5.00', stempel_van: '07:02:00', stempel_tot: '12:00:00', stempel_afwijking: true })
    expect(stempelToets(d)).toEqual({ tekst: '3 u boven stempels — bespreken', soort: 'vlag' })
    const onder = dag({ uren: '4', gestempeld_uren: '6.50', stempel_afwijking: true })
    expect(stempelToets(onder).tekst).toBe('2,5 u onder stempels — bespreken')
  })

  it('geen stempels: geen label, toets zwijgt ("geen toets mogelijk")', () => {
    const d = dag({ gestempeld_uren: null })
    expect(gestempeldLabel(d)).toBeNull()
    expect(stempelToets(d)).toEqual({ tekst: 'geen stempels — geen toets mogelijk', soort: 'geen' })
    expect(gestempeldLabel(dag({}))).toBeNull() // oude backend zonder veld
  })

  it('onvolledig paar: "?" als eindtijd en de markering in het label', () => {
    const d = dag({ uren: '4', gestempeld_uren: '4.10', stempel_van: '06:58:00', stempel_tot: null, stempel_onvolledig: true, stempel_afwijking: false })
    expect(gestempeldLabel(d)).toBe('06:58 – ? (4,1 u, onvolledig paar)')
  })
})
