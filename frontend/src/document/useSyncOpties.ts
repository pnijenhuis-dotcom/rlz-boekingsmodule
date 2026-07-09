import { useEffect, useState } from 'react'
import { apiJson } from '../api/client'
import type {
  GrootboekLijstDto,
  ProjectLijstDto,
  ProjectVerplichtDto,
  TaxrateLijstDto,
  VendorLijstDto,
} from '../api/types'
import type { ComboboxOptie } from './SearchableCombobox'

interface LijstResultaat {
  opties: ComboboxOptie[]
  fout: string | null
  laden: boolean
}

function useLijst<T>(pad: string, herlaadSleutel: number, naarOpties: (data: T) => ComboboxOptie[]): LijstResultaat {
  const [opties, setOpties] = useState<ComboboxOptie[]>([])
  const [fout, setFout] = useState<string | null>(null)
  const [laden, setLaden] = useState(true)

  useEffect(() => {
    let actief = true
    setLaden(true)
    setFout(null)
    apiJson<T>(pad)
      .then((data) => {
        if (actief) setOpties(naarOpties(data))
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
      .finally(() => {
        if (actief) setLaden(false)
      })
    return () => {
      actief = false
    }
    // Bewust niet `naarOpties` in de deps: de aanroepende hooks (useGrootboekOpties e.a.) geven
    // elke render een nieuwe closure mee — die opnemen zou een refetch-loop veroorzaken. `pad` +
    // `herlaadSleutel` zijn de enige signalen die daadwerkelijk om een nieuwe fetch vragen.
  }, [pad, herlaadSleutel])

  return { opties, fout, laden }
}

/** Gevuld uit de sync-caches van de gekozen administratie (CLAUDE.md-taak 2.1) — nooit
 * rechtstreeks van RLZ, altijd via de al gesyncte platform-/boekhouding-tabellen.
 * `herlaadSleutel` ophogen (bv. na "Nu synchroniseren", design-pass taak 3) forceert een refetch. */
export function useGrootboekOpties(administratieId: string, herlaadSleutel = 0): LijstResultaat {
  return useLijst<GrootboekLijstDto>(`/administraties/${administratieId}/grootboek`, herlaadSleutel, (d) =>
    d.rekeningen.map((r) => ({ id: r.ledger_id, code: r.code, label: r.naam })),
  )
}

export function useTaxrateOpties(administratieId: string, herlaadSleutel = 0): LijstResultaat {
  return useLijst<TaxrateLijstDto>(`/administraties/${administratieId}/btw-codes`, herlaadSleutel, (d) =>
    d.btw_codes.map((t) => {
      const percentage = t.percentage != null ? Number(t.percentage) : undefined
      return {
        id: t.id,
        code: percentage !== undefined ? `${Math.round(percentage * 100)}%` : undefined,
        label: t.naam ?? t.id,
        percentage,
      }
    }),
  )
}

export function useVendorOpties(administratieId: string, herlaadSleutel = 0): LijstResultaat {
  return useLijst<VendorLijstDto>(`/administraties/${administratieId}/crediteuren`, herlaadSleutel, (d) =>
    d.crediteuren.map((v) => ({ id: v.id, label: v.naam ?? v.id })),
  )
}

export function useProjectOpties(administratieId: string, herlaadSleutel = 0): LijstResultaat {
  return useLijst<ProjectLijstDto>(`/administraties/${administratieId}/projecten`, herlaadSleutel, (d) =>
    d.projecten.map((p) => ({ id: p.id, label: p.naam ?? p.id })),
  )
}

/** Design-pass taak 4: bepaalt of de Project-kolom in het controlescherm zichtbaar/verplicht is
 * voor deze administratie. Geen Beheerder-only endpoint (elke gescoopte gebruiker mag dit lezen);
 * bij een laadfout nemen we "niet verplicht" aan zodat het scherm nooit vastloopt op deze check. */
export function useProjectVerplicht(administratieId: string): boolean {
  const [verplicht, setVerplicht] = useState(false)

  useEffect(() => {
    let actief = true
    apiJson<ProjectVerplichtDto>(`/administraties/${administratieId}/project-instelling`)
      .then((data) => {
        if (actief) setVerplicht(data.verplicht)
      })
      .catch(() => {
        if (actief) setVerplicht(false)
      })
    return () => {
      actief = false
    }
  }, [administratieId])

  return verplicht
}

const SYNC_PADEN = ['ledgers', 'taxrates', 'vendors', 'projects'] as const

/** "Nu synchroniseren" (design-pass taak 3) — alle vier de caches tegelijk verversen via de
 * bestaande on-demand trigger-endpoints (Beheerder/scope-check, app/sync/router.py). Best-effort:
 * geeft de fouten van de mislukte paden terug i.p.v. bij de eerste fout te stoppen, zodat een
 * enkel probleem (bv. rechten op één resource) niet de andere drie blokkeert. */
export async function synchroniseerAlleCaches(administratieId: string): Promise<string[]> {
  const resultaten = await Promise.all(
    SYNC_PADEN.map(async (pad) => {
      try {
        await apiJson(`/administraties/${administratieId}/sync/${pad}`, { method: 'POST' })
        return null
      } catch (err) {
        return `${pad}: ${err instanceof Error ? err.message : 'onbekende fout'}`
      }
    }),
  )
  return resultaten.filter((fout): fout is string => fout !== null)
}
