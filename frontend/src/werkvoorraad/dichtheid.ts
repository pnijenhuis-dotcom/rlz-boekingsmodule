import { useCallback, useState } from 'react'

/** Dichtheidsvoorkeur van de documentenlijst (werkstroom-run 27/28-08, punt 3b): normaal of
 * compact, per gebruiker onthouden in localStorage — hetzelfde voorkeuren-patroon als het thema
 * (ui/thema.ts), de review-splitter (ui/ReviewSplitter.tsx) en de verkoop-viewerbreedte: een
 * presentatievoorkeur per browser, geen serverdata en dus geen migratie. localStorage kan
 * ontbreken of gooien (private mode, jsdom) — dan gewoon de standaard, nooit een fout. */
export type Dichtheid = 'normaal' | 'compact'

export const DICHTHEID_OPSLAG_SLEUTEL = 'rlz.documentenlijst.dichtheid'
const STANDAARD: Dichtheid = 'normaal'

export function leesDichtheid(): Dichtheid {
  try {
    const waarde = window.localStorage.getItem(DICHTHEID_OPSLAG_SLEUTEL)
    return waarde === 'compact' ? 'compact' : STANDAARD
  } catch {
    return STANDAARD
  }
}

export function bewaarDichtheid(dichtheid: Dichtheid): void {
  try {
    window.localStorage.setItem(DICHTHEID_OPSLAG_SLEUTEL, dichtheid)
  } catch {
    // Geen opslag beschikbaar: de keuze geldt dan alleen voor deze pagina-instantie.
  }
}

export function useDichtheid(): [Dichtheid, (d: Dichtheid) => void] {
  const [dichtheid, setDichtheidState] = useState<Dichtheid>(leesDichtheid)
  const setDichtheid = useCallback((d: Dichtheid) => {
    bewaarDichtheid(d)
    setDichtheidState(d)
  }, [])
  return [dichtheid, setDichtheid]
}
