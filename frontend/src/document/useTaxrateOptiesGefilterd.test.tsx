import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ComboboxOptie } from './SearchableCombobox'
import { filterEnSorteerTaxrates, GROEP_BUITENLAND, landPrefix, useTaxrateOptiesGefilterd } from './useTaxrateOptiesGefilterd'

/** NL-eerst btw-keuzelijst (Peter 18-09 DEEL B). Opties zoals BLOW ze uit RLZ krijgt (22 tarieven, waarvan 10 EU/Ex-EU). */
const OPTIES: ComboboxOptie[] = [
  { id: 'hoog', code: '21%', label: 'NL, Hoog Tarief', percentage: 0.21, favoriet: true, gebruik12m: 120 },
  { id: 'laag', code: '9%', label: 'NL, Laag tarief', percentage: 0.09, favoriet: true, gebruik12m: 40 },
  { id: 'nul', code: '0%', label: 'NL, Nul tarief', percentage: 0, gebruik12m: 3 },
  { id: 'vrij', code: '0%', label: 'NL, Geen BTW (Vrijgesteld)', percentage: 0, vrijgesteld: true, gebruik12m: 0 },
  { id: 'verlegd', code: '0%', label: 'NL, BTW verlegd (hoog)', percentage: 0, verlegd: true, gebruik12m: 8 },
  { id: 'auto', code: '12%', label: 'NL, Auto tarief', percentage: 0.12, gebruik12m: 0 },
  { id: 'eu-p-h', code: '0%', label: 'EU, Producten Hoog tarief', percentage: 0, verlegd: true, buitenland: true, gebruik12m: 0 },
  { id: 'eu-d-h', code: '0%', label: 'EU, Diensten Hoog tarief (vanaf 2010)', percentage: 0, verlegd: true, buitenland: true, gebruik12m: 2 },
  { id: 'exeu', code: '0%', label: 'Ex EU, Diensten Laag tarief (vanaf 2010)', percentage: 0, verlegd: true, buitenland: true, gebruik12m: 0 },
  { id: 'de', code: '19%', label: 'DE, Hoog', percentage: 0.19, buitenland: true, gebruik12m: 0 },
]

describe('useTaxrateOptiesGefilterd — NL-eerst keuzelijst (18-09)', () => {
  it('sorteert op gebruik (12 mnd) en daarna alfabetisch; buitenland krijgt de groep', () => {
    const uit = filterEnSorteerTaxrates(OPTIES, 'NL')
    expect(uit.slice(0, 3).map((o) => o.id)).toEqual(['hoog', 'laag', 'verlegd'])
    expect(uit.filter((o) => o.groep === GROEP_BUITENLAND).map((o) => o.id).sort()).toEqual(['de', 'eu-d-h', 'eu-p-h', 'exeu'])
    // Nul-tarieven blijven onderscheidbaar op RLZ-naam (nul / vrijgesteld / verlegd) — niets samengevoegd.
    expect(uit.filter((o) => o.percentage === 0 && !o.buitenland)).toHaveLength(3)
  })

  it('land NL → ingeklapte groep "Buitenland-tarieven tonen (N)"; onbekend → niets ingeklapt (alles zichtbaar)', () => {
    const nl = renderHook(() => useTaxrateOptiesGefilterd(OPTIES, 'NL')).result.current
    expect(nl.ingeklapteGroep?.groep).toBe(GROEP_BUITENLAND)
    expect(nl.ingeklapteGroep?.label(4)).toBe('Buitenland-tarieven tonen (4)')
    const onbekend = renderHook(() => useTaxrateOptiesGefilterd(OPTIES, null)).result.current
    expect(onbekend.ingeklapteGroep).toBeUndefined()
    expect(onbekend.opties).toHaveLength(OPTIES.length)
  })

  it('land ≠ NL → alles zichtbaar mét de tarieven van dat land/EU bovenaan', () => {
    const de = filterEnSorteerTaxrates(OPTIES, 'DE')
    expect(de.slice(0, 3).map((o) => o.id).sort()).toEqual(['de', 'eu-d-h', 'eu-p-h'])
    expect(renderHook(() => useTaxrateOptiesGefilterd(OPTIES, 'DE')).result.current.ingeklapteGroep).toBeUndefined()
  })

  it('landPrefix leest het RLZ-naamprefix vóór de komma', () => {
    expect(landPrefix('EU, Producten Hoog tarief')).toBe('EU')
    expect(landPrefix('NL, Hoog Tarief')).toBe('NL')
    expect(landPrefix('Hoog')).toBeNull()
  })
})
