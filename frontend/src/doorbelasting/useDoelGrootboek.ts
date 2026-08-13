import { useEffect, useRef, useState } from 'react'
import { ApiError, apiJson } from '../api/client'
import type { GrootboekLijstDto } from '../api/types'
import type { ComboboxOptie } from '../document/SearchableCombobox'

export interface DoelGrootboek {
  opties: ComboboxOptie[]
  /** Mensentaal-melding als het rekeningschema niet te laden is (bv. geen scope op de
   * doel-administratie) — de kiezer degradeert dan naar een nette melding, nooit een kale
   * lege lijst. */
  fout: string | null
  laden: boolean
}

/** Rekeningschema's van DOEL-administraties (mockup #verdeelmodal "GB in doeladministratie:
 * … live uit het RLZ-rekeningschema van díé administratie"): per uniek administratie-id één
 * fetch op het bestaande grootboek-endpoint uit de sync-cache; resultaten worden binnen de
 * hook gecachet zodat meerdere verdeelregels naar dezelfde doelentiteit één fetch delen.
 * Geen scope op de doel-administratie ⇒ nette melding (403 van de backend), geen blokkade
 * van de rest van het scherm. */
export function useDoelGrootboek(administratieIds: (string | null)[]): Record<string, DoelGrootboek> {
  const [kaart, setKaart] = useState<Record<string, DoelGrootboek>>({})
  // Cache over de levensduur van het scherm: al opgehaalde (of mislukte) id's niet opnieuw
  // fetchen bij elke re-render met dezelfde set.
  const gestart = useRef(new Set<string>())

  const sleutel = [...new Set(administratieIds.filter((id): id is string => id !== null))].sort().join(',')

  useEffect(() => {
    if (!sleutel) return
    const nieuw = sleutel.split(',').filter((id) => !gestart.current.has(id))
    if (nieuw.length === 0) return
    for (const id of nieuw) gestart.current.add(id)
    setKaart((huidig) => {
      const kopie = { ...huidig }
      for (const id of nieuw) kopie[id] = { opties: [], fout: null, laden: true }
      return kopie
    })
    // Bewust géén actief-cleanup-guard: onder StrictMode (dubbel effect, ref+state blijven
    // bewaard) zou de gestart-cache anders elke landing blokkeren en blijft "laden" hangen;
    // setState ná unmount is in React 18 een onschadelijke no-op.
    for (const id of nieuw) {
      apiJson<GrootboekLijstDto>(`/administraties/${id}/grootboek`)
        .then((data) => {
          setKaart((huidig) => ({
            ...huidig,
            [id]: {
              opties: data.rekeningen.map((r) => ({ id: r.ledger_id, code: r.code, label: r.naam })),
              fout: null,
              laden: false,
            },
          }))
        })
        .catch((err: unknown) => {
          const melding =
            err instanceof ApiError && err.status === 403
              ? 'Geen toegang tot het rekeningschema van deze doel-administratie (geen scope) — vraag scope aan bij de beheerder of laat een collega mét scope de keuze maken.'
              : `Rekeningschema van de doel-administratie niet te laden: ${err instanceof Error ? err.message : 'onbekende fout'}`
          setKaart((huidig) => ({ ...huidig, [id]: { opties: [], fout: melding, laden: false } }))
        })
    }
  }, [sleutel])

  return kaart
}
