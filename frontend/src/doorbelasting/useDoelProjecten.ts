import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import type { DoelProjectDto } from '../api/types'
import { haalDoelProjectenOp } from './doorbelastingApi'

export interface DoelProjecten {
  projecten: DoelProjectDto[]
  /** project_verplicht van de doel-administratie: dan is een project per verdeelregel verplicht. */
  projectVerplicht: boolean
  /** null = doel niet onboarded (geen projecten kiesbaar). */
  doelAdministratieId: string | null
  fout: string | null
  laden: boolean
}

/** Projecten van DOEL-administraties per whitelist-rij (doorbelasting × projecten, besluit Peter
 * 25-08): één fetch per mapping-id, gecachet over de levensduur van het scherm — zelfde patroon
 * als useDoelGrootboek. Geen scope op het doel ⇒ nette melding, geen blokkade van de rest. */
export function useDoelProjecten(administratieId: string, mappingIds: (string | null)[]): Record<string, DoelProjecten> {
  const [kaart, setKaart] = useState<Record<string, DoelProjecten>>({})
  const gestart = useRef(new Set<string>())
  const sleutel = [...new Set(mappingIds.filter((id): id is string => id !== null))].sort().join(',')

  useEffect(() => {
    if (!sleutel) return
    const nieuw = sleutel.split(',').filter((id) => !gestart.current.has(id))
    if (nieuw.length === 0) return
    for (const id of nieuw) gestart.current.add(id)
    setKaart((huidig) => {
      const kopie = { ...huidig }
      for (const id of nieuw) kopie[id] = { projecten: [], projectVerplicht: false, doelAdministratieId: null, fout: null, laden: true }
      return kopie
    })
    for (const id of nieuw) {
      haalDoelProjectenOp(administratieId, id)
        .then((data) => {
          setKaart((huidig) => ({
            ...huidig,
            [id]: {
              projecten: data.projecten,
              projectVerplicht: data.project_verplicht,
              doelAdministratieId: data.doel_administratie_id,
              fout: null,
              laden: false,
            },
          }))
        })
        .catch((err: unknown) => {
          const melding =
            err instanceof ApiError && err.status === 403
              ? 'Geen toegang tot de projecten van deze doel-administratie (geen scope).'
              : `Projecten van de doel-administratie niet te laden: ${err instanceof Error ? err.message : 'onbekende fout'}`
          setKaart((huidig) => ({
            ...huidig,
            [id]: { projecten: [], projectVerplicht: false, doelAdministratieId: null, fout: melding, laden: false },
          }))
        })
    }
  }, [administratieId, sleutel])

  return kaart
}
