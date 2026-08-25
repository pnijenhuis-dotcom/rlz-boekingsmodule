// Slimme landing + Planning-hoofdmenu (steigerbouw-run C1/C2, besluiten Peter 24-08).
// Eén fetch per sessie op /uren/kantoor/mijn-toegang: module-recht "Meerwerk & urenstaten" +
// de administraties met de uren-&-meerwerk-opt-in binnen de eigen scope. FAIL-CLOSED: elke
// fout/twijfel = `null` → de bestaande werkvoorraad-landing en het gewone menu.
import { useEffect, useState } from 'react'
import { apiJson } from '../api/client'
import type { AdministratieDto } from '../api/types'

export interface MijnToegangDto {
  heeft_meerwerk_recht: boolean
  administraties_met_opt_in: string[]
  aantal_administraties_in_scope: number
  is_beheerder: boolean
}

let cache: { waarde: MijnToegangDto | null; tijd: number } | null = null

export function resetMijnToegangCache(): void {
  cache = null
}

export function useMijnToegang(): MijnToegangDto | null | undefined {
  const [toegang, setToegang] = useState<MijnToegangDto | null | undefined>(cache ? cache.waarde : undefined)
  useEffect(() => {
    if (cache && Date.now() - cache.tijd < 60_000) {
      setToegang(cache.waarde)
      return
    }
    let actief = true
    apiJson<MijnToegangDto>('/uren/kantoor/mijn-toegang')
      .then((data) => {
        cache = { waarde: data, tijd: Date.now() }
        if (actief) setToegang(data)
      })
      .catch(() => {
        cache = { waarde: null, tijd: Date.now() }
        if (actief) setToegang(null)
      })
    return () => {
      actief = false
    }
  }, [])
  return toegang
}

/** Mono-klant-medewerker (C1): géén Beheerder, precies één administratie in scope. */
export function isMonoKlant(toegang: MijnToegangDto | null | undefined, administraties: AdministratieDto[] | null): boolean {
  return (
    !!toegang && !toegang.is_beheerder && toegang.aantal_administraties_in_scope === 1 && (administraties?.length ?? 0) === 1
  )
}

/** Landingspad ná login (C1). null = bestaande werkvoorraad (fail-closed). Steigerbouw-deel als
 * de mono-klant-medewerker het module-recht heeft én die ene administratie de opt-in aan heeft. */
export function landingsPad(toegang: MijnToegangDto | null | undefined, administraties: AdministratieDto[] | null): string | null {
  if (!isMonoKlant(toegang, administraties) || !toegang || !administraties) return null
  const enige = administraties[0]
  if (toegang.heeft_meerwerk_recht && toegang.administraties_met_opt_in.includes(enige.id)) {
    return `/meerwerk?administratie=${enige.id}`
  }
  return `/?administratie=${enige.id}`
}

/** Planning-menu-item (C2): zichtbaar bij module-recht + ≥ 1 opt-in-administratie in scope. */
export function planningMenuPad(toegang: MijnToegangDto | null | undefined): string | null {
  if (!toegang || !toegang.heeft_meerwerk_recht || toegang.administraties_met_opt_in.length === 0) return null
  return toegang.administraties_met_opt_in.length === 1
    ? `/planning?administratie=${toegang.administraties_met_opt_in[0]}`
    : '/planning'
}
