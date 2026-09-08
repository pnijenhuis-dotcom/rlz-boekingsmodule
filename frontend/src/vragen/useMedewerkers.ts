import { useEffect, useMemo, useState } from 'react'
import type { MedewerkerDto } from '../api/types'
import { haalMedewerkersOp } from './vragenApi'

/** Weergave van een lege toewijzing (07-09 "leeg = doorlopen"): een vraag/afwijzing zónder toegewezene is geen
 * fout maar een kantoorbrede rij — de kolom "Toegewezen" en de detailregels zeggen dat expliciet. */
export const NIET_TOEGEWEZEN = '— (niet toegewezen)'

/** Naam van een toegewezene, of het expliciete niet-toegewezen-label bij null. */
export function toegewezeneLabel(naamVoor: (id: string | null) => string, id: string | null | undefined): string {
  return id ? naamVoor(id) : NIET_TOEGEWEZEN
}

/** Systeem-actor (backend `app/db/systeem_actor.py::SYSTEEM_ACTOR_ID`) — een échte platform.gebruiker-
 * rij die nooit kan inloggen en overal staat waar een proces zónder mens iets deed (o.a. de
 * automatische duplicaat-afvoer). Nooit in de per-administratie-medewerkerslijst (geen scope) — zonder
 * deze herkenning toont `naamVoor()` de generieke terugval 'onbekende medewerker', wat de indruk wekt
 * dat er iets mis is met de toewijzing i.p.v. dat het systeem het deed. */
export const SYSTEEM_ACTOR_ID = '00000000-0000-0000-0000-000000000001'

/** Naam van een actor in een afwijzings-/duplicaat-afvoercontext (blok 3, fixrun 08-09): de
 * systeem-actor krijgt hier het herkenbare label "automatisch (duplicaatregel)" i.p.v. de generieke
 * 'onbekende medewerker' — de systeem-actor is op de `Afwijzing`-rij uitsluitend de schrijver van een
 * automatische duplicaat-afvoer (nooit van een gewone afwijzing, die vergt altijd een mens op de knop).
 * Voor elke andere id valt dit terug op `naamVoor` — één bron, geen dubbele vertaling. */
export function actorLabel(naamVoor: (id: string | null) => string, id: string | null | undefined): string {
  if (id === SYSTEEM_ACTOR_ID) return 'automatisch (duplicaatregel)'
  return naamVoor(id ?? null)
}

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

  /** Blok B5 (26-08): is deze gebruiker een klant-accordeur (vraag "bij de klant")? */
  const isKlantAccordeur = useMemo(() => {
    const set = new Set((medewerkers ?? []).filter((m) => m.is_klant_accordeur).map((m) => m.id))
    return (gebruikerId: string | null): boolean => !!gebruikerId && set.has(gebruikerId)
  }, [medewerkers])

  return { medewerkers, naamVoor, isKlantAccordeur, fout }
}
