import type { AdministratieDto } from '../api/types'
import { normaliseerTekst } from '../bank/bankZoek'
import type { KlantRij } from './useWerkvoorraadData'

/* Zoekveld op de klantenlijst (Peter 18-09: "graag zoekveld bij administraties, zodat je niet de hele lijst door hoeft te
 * scrollen" — 71+ administraties, alleen een Groep-filter). Client-side over de rijen die al in de tellers-cache-respons
 * staan (geen server-call): administratienaam en groepsnaam, diakriet-loos en hoofdletter-ongevoelig zoals `bankZoek.ts`.
 * Elke spatie-gescheiden term moet treffen (AND). Leeg = alles. Werkt náást het (server-side) Groep-filter. */

export const KLANTZOEK_OPSLAGSLEUTEL = 'werkvoorraad-klantzoek'

export function klantZoektekst(k: KlantRij, administraties: Pick<AdministratieDto, 'id' | 'groep_naam'>[] = []): string[] {
  const adm = administraties.find((a) => a.id === k.administratie_id)
  return [k.naam, adm?.groep_naam ?? ''].filter((t) => t.trim()).map(normaliseerTekst)
}

export function klantMatcht(k: KlantRij, zoek: string, administraties: Pick<AdministratieDto, 'id' | 'groep_naam'>[] = []): boolean {
  const termen = normaliseerTekst(zoek).split(' ').filter(Boolean)
  if (termen.length === 0) return true
  const velden = klantZoektekst(k, administraties)
  return termen.every((term) => velden.some((v) => v.includes(term)))
}

export function filterKlanten(klanten: KlantRij[], zoek: string, administraties: Pick<AdministratieDto, 'id' | 'groep_naam'>[] = []): KlantRij[] {
  if (!normaliseerTekst(zoek)) return klanten
  return klanten.filter((k) => klantMatcht(k, zoek, administraties))
}

/** Laatste zoekterm per browsersessie (sessionStorage; de URL `?zoek=` wint altijd). Opslag kan ontbreken/weigeren. */
export function leesOnthoudenZoek(): string {
  try {
    return window.sessionStorage.getItem(KLANTZOEK_OPSLAGSLEUTEL) ?? ''
  } catch {
    return ''
  }
}

export function onthoudZoek(zoek: string): void {
  try {
    if (zoek) window.sessionStorage.setItem(KLANTZOEK_OPSLAGSLEUTEL, zoek)
    else window.sessionStorage.removeItem(KLANTZOEK_OPSLAGSLEUTEL)
  } catch {
    /* opslag geblokkeerd — de zoekterm leeft dan alleen in de URL */
  }
}
