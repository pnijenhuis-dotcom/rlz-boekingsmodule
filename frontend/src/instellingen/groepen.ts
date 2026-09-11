import { useCallback, useEffect, useState } from 'react'
import type { GroepDto } from '../api/types'
import { haalGroepenOp } from './instellingenApi'

/** Groepskenmerk op administratie (blok 8 run 11-09 middag, opdracht Peter 11-09; migratie 0135).
 * Pure helpers + één gedeelde hook voor de filter-keuzelijsten (klantenlijst, Inzicht › Reconciliatie) en het
 * veld "Groep" (detailpagina, wizard). Een groep is een FILTER, nooit een poort — zonder groepen verschijnt er
 * nergens iets, en een mislukte lijst-fetch blokkeert geen enkel scherm. */

export const CODE_MAX_LENGTE = 12
export const CODE_PATROON = /^[A-Z0-9]{2,12}$/

/** Deterministisch code-voorstel uit de naam — spiegel van `app/beheer/groepen.py::code_voorstel`:
 * accenten weg, alleen letters/cijfers, hoofdletters, max 12 tekens; korter dan 2 = leeg (de gebruiker vult zelf). */
export function codeVoorstel(naam: string): string {
  const zonderAccenten = naam.normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
  const kaal = zonderAccenten.replace(/[^A-Za-z0-9]/g, '').toUpperCase().slice(0, CODE_MAX_LENGTE)
  return kaal.length >= 2 ? kaal : ''
}

export function codeGeldig(code: string): boolean {
  return CODE_PATROON.test(code)
}

/** Weergavenaam mét archief-markering — een lid van een gearchiveerde groep blijft lid (nooit stil verdwenen). */
export function groepLabel(g: Pick<GroepDto, 'naam' | 'actief'>): string {
  return g.actief ? g.naam : `${g.naam} (gearchiveerd)`
}

export interface UseGroepenResultaat {
  groepen: GroepDto[] | null
  fout: string | null
  herlaad: () => void
  /** Optimistisch één groep toevoegen/bijwerken ná aanmaken/wijzigen (geen tweede fetch nodig). */
  zet: (g: GroepDto) => void
}

/** GET /groepen — tolerant: een fout (bv. 404 in een oude mock) levert een lege lijst mét `fout`; afnemers renderen
 * dan gewoon niets extra. `inclusiefGearchiveerd` = false voor keuzelijsten die alleen actieve groepen mogen tonen. */
export function useGroepen(inclusiefGearchiveerd = true): UseGroepenResultaat {
  const [groepen, setGroepen] = useState<GroepDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)

  useEffect(() => {
    let actief = true
    haalGroepenOp()
      .then((d) => {
        if (!actief) return
        const lijst = Array.isArray(d?.groepen) ? d.groepen : []
        setGroepen(inclusiefGearchiveerd ? lijst : lijst.filter((g) => g.actief))
      })
      .catch((err: unknown) => {
        if (!actief) return
        setGroepen([])
        setFout(err instanceof Error ? err.message : 'Groepen niet te laden')
      })
    return () => {
      actief = false
    }
  }, [inclusiefGearchiveerd, versie])

  const herlaad = useCallback(() => setVersie((v) => v + 1), [])
  const zet = useCallback((g: GroepDto) => {
    setGroepen((huidig) => {
      const lijst = huidig ?? []
      const rest = lijst.filter((x) => x.id !== g.id)
      return [...rest, g].sort((a, b) => Number(b.actief) - Number(a.actief) || a.naam.localeCompare(b.naam, 'nl'))
    })
  }, [])

  return { groepen, fout, herlaad, zet }
}
