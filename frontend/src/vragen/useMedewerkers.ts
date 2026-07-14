import { useEffect, useMemo, useState } from 'react'
import type { MedewerkerDto } from '../api/types'
import { haalMedewerkersOp } from './vragenApi'

/** Toewijsbare medewerkers van één administratie (vraagmodal, toegewezen-kolom, vragen-view) +
 * een naam-opzoeker voor gebruiker-UUID's. Een id buiten de lijst (bv. iemand wiens scope later
 * is ingetrokken) valt terug op een herkenbaar label, nooit op een kale UUID. */
export function useMedewerkers(administratieId: string | null) {
  const [medewerkers, setMedewerkers] = useState<MedewerkerDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    if (!administratieId) return
    let actief = true
    setMedewerkers(null)
    setFout(null)
    haalMedewerkersOp(administratieId)
      .then((data) => {
        if (actief) setMedewerkers(data.medewerkers)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId])

  const naamVoor = useMemo(() => {
    const map = new Map((medewerkers ?? []).map((m) => [m.id, m.naam]))
    return (gebruikerId: string | null): string => {
      if (!gebruikerId) return '—'
      return map.get(gebruikerId) ?? 'onbekende medewerker'
    }
  }, [medewerkers])

  return { medewerkers, naamVoor, fout }
}
