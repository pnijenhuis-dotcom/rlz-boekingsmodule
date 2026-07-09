import { useEffect, useState } from 'react'
import { apiJson } from '../api/client'
import type { GrootboekLijstDto, ProjectLijstDto, TaxrateLijstDto, VendorLijstDto } from '../api/types'
import type { ComboboxOptie } from './SearchableCombobox'

interface LijstResultaat {
  opties: ComboboxOptie[]
  fout: string | null
}

function useLijst<T>(pad: string, naarOpties: (data: T) => ComboboxOptie[]): LijstResultaat {
  const [opties, setOpties] = useState<ComboboxOptie[]>([])
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    let actief = true
    setOpties([])
    setFout(null)
    apiJson<T>(pad)
      .then((data) => {
        if (actief) setOpties(naarOpties(data))
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [pad])

  return { opties, fout }
}

/** Gevuld uit de sync-caches van de gekozen administratie (CLAUDE.md-taak 2.1) — nooit
 * rechtstreeks van RLZ, altijd via de al gesyncte platform-/boekhouding-tabellen. */
export function useGrootboekOpties(administratieId: string): LijstResultaat {
  return useLijst<GrootboekLijstDto>(`/administraties/${administratieId}/grootboek`, (d) =>
    d.rekeningen.map((r) => ({ id: r.ledger_id, label: `${r.code} · ${r.naam}` })),
  )
}

export function useTaxrateOpties(administratieId: string): LijstResultaat {
  return useLijst<TaxrateLijstDto>(`/administraties/${administratieId}/btw-codes`, (d) =>
    d.btw_codes.map((t) => ({ id: t.id, label: t.naam ?? t.id })),
  )
}

export function useVendorOpties(administratieId: string): LijstResultaat {
  return useLijst<VendorLijstDto>(`/administraties/${administratieId}/crediteuren`, (d) =>
    d.crediteuren.map((v) => ({ id: v.id, label: v.naam ?? v.id })),
  )
}

export function useProjectOpties(administratieId: string): LijstResultaat {
  return useLijst<ProjectLijstDto>(`/administraties/${administratieId}/projecten`, (d) =>
    d.projecten.map((p) => ({ id: p.id, label: p.naam ?? p.id })),
  )
}
