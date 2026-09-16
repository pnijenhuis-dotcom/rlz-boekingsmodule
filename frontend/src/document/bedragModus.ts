import { useCallback, useState } from 'react'

/** Bruto/netto-schakelaar op bedragvelden (blok E ProfX-opdracht, Peter 16-09: "gelieve netto/bruto selecteerbaar
 * (klikken = switch)"). Eén voorkeur per gebruiker voor álle regel-tabellen (inkoop-controlescherm én omzetscherm),
 * onthouden in localStorage — hetzelfde presentatievoorkeur-patroon als de dichtheid (werkvoorraad/dichtheid.ts):
 * geen serverdata, geen migratie; localStorage kan ontbreken of gooien → standaard, nooit een fout.
 *
 * De omrekening is deterministisch en cent-exact op het percentage van de btw-code van de regel; zónder btw-code is
 * er geen omrekening mogelijk en blijft het veld in de bron-modus (tooltip). De andere waarde wordt bewust NIET onder
 * het veld getoond (besluit Peter 16-09: kost breedte — wisselen via het kopje volstaat). */
export type BedragModus = 'netto' | 'bruto'

export const BEDRAGMODUS_OPSLAG_SLEUTEL = 'rlz.bedragmodus'
const STANDAARD: BedragModus = 'netto'

export function leesBedragModus(): BedragModus {
  try {
    return window.localStorage.getItem(BEDRAGMODUS_OPSLAG_SLEUTEL) === 'bruto' ? 'bruto' : STANDAARD
  } catch {
    return STANDAARD
  }
}

export function bewaarBedragModus(modus: BedragModus): void {
  try {
    window.localStorage.setItem(BEDRAGMODUS_OPSLAG_SLEUTEL, modus)
  } catch {
    // Geen opslag: de keuze geldt alleen voor deze pagina-instantie.
  }
}

export function useBedragModus(): [BedragModus, () => void] {
  const [modus, setModus] = useState<BedragModus>(leesBedragModus)
  const wissel = useCallback(() => {
    setModus((huidig) => {
      const volgende: BedragModus = huidig === 'netto' ? 'bruto' : 'netto'
      bewaarBedragModus(volgende)
      return volgende
    })
  }, [])
  return [modus, wissel]
}

export function anderModus(modus: BedragModus): BedragModus {
  return modus === 'netto' ? 'bruto' : 'netto'
}

/** Cent-exact afronden (half-up op centen, zelfde conventie als regelsom.py). */
export function rondCenten(waarde: number): number {
  return Math.round((waarde + Number.EPSILON) * 100) / 100
}

/** Netto → bruto op het percentage (0.21 = 21 %); het btw-bedrag is netto × pct afgerond, bruto = netto + btw. */
export function nettoNaarBruto(netto: number, percentage: number): number {
  return rondCenten(netto + rondCenten(netto * percentage))
}

/** Bruto → netto: netto = bruto / (1 + pct) afgerond; btw = bruto − netto (cent-exact sluitend, restcent in de btw). */
export function brutoNaarNetto(bruto: number, percentage: number): number {
  return rondCenten(bruto / (1 + percentage))
}

/** Waarde in `van`-modus omrekenen naar `naar`-modus; zonder percentage (geen btw-code) = ongewijzigd. */
export function rekenOm(waarde: number, van: BedragModus, naar: BedragModus, percentage: number | undefined): number {
  if (van === naar || percentage === undefined) return waarde
  return van === 'netto' ? nettoNaarBruto(waarde, percentage) : brutoNaarNetto(waarde, percentage)
}

export function kopLabel(modus: BedragModus, basis = 'Omzet'): string {
  return modus === 'netto' ? `${basis} netto` : `${basis} bruto`
}
