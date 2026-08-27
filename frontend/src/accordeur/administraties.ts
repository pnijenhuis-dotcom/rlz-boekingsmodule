// BV-openingsscherm (besluit Peter 27-08, mockup accordeur-vragen.html scherm 0 "Uw
// administraties"): pure afleidingen uit de wachtrij + "vragen aan u" — geen extra endpoint, de
// wachtrij draagt per item al administratie_id/-naam en aangeboden_op (fase 2-verificatiepunt:
// de backend voegt de administraties van de accordeur samen). Regels:
//   • alleen administraties MÉT actief werk (te accorderen en/of een open vraag aan u) — geen
//     "✓ bij"-rijen; niets te doen = lege staat "✓ Alles is bij";
//   • precies één administratie mét werk = keuzescherm overslaan, direct die wachtrij;
//   • volgorde: langst wachtende bovenaan, dan op naam.

import type { AccordeurVraagDto, WachtrijItemDto } from './accordeurApi'

export interface AdministratieStand {
  id: string
  naam: string | null
  /** Aantal te accorderen facturen in deze administratie. */
  teAccorderen: number
  /** Aantal open vragen van het kantoor aan déze accordeur (op de kaart én los). */
  vragen: number
  /** ISO-tijdstip van de langst wachtende factuur (null = alleen vragen). */
  oudsteWacht: string | null
}

/** Groepeert per administratie; alleen administraties met werk komen terug. */
export function administratiesMetWerk(items: WachtrijItemDto[], vragen: AccordeurVraagDto[]): AdministratieStand[] {
  const per = new Map<string, AdministratieStand>()
  const stand = (id: string, naam: string | null): AdministratieStand => {
    let s = per.get(id)
    if (!s) {
      s = { id, naam, teAccorderen: 0, vragen: 0, oudsteWacht: null }
      per.set(id, s)
    } else if (!s.naam && naam) {
      s.naam = naam
    }
    return s
  }
  for (const item of items) {
    const s = stand(item.administratie_id, item.administratie_naam)
    s.teAccorderen += 1
    if (s.oudsteWacht === null || item.aangeboden_op < s.oudsteWacht) s.oudsteWacht = item.aangeboden_op
  }
  for (const vraag of vragen) {
    stand(vraag.administratie_id, vraag.administratie_naam).vragen += 1
  }
  return [...per.values()].sort((a, b) => {
    // Langst wachtend eerst; administraties met alleen vragen achteraan; daarna op naam.
    if (a.oudsteWacht !== b.oudsteWacht) {
      if (a.oudsteWacht === null) return 1
      if (b.oudsteWacht === null) return -1
      return a.oudsteWacht < b.oudsteWacht ? -1 : 1
    }
    return (a.naam ?? '').localeCompare(b.naam ?? '', 'nl')
  })
}

/** Welke administratie de wachtrij toont: de expliciete keuze zolang die nog werk heeft; is er
 * precies één administratie met werk, dan altijd die (keuzescherm overslaan); anders null =
 * het overzicht (≥ 2) of de lege staat (0). */
export function kiesActieveAdministratie(keuze: string | null, standen: AdministratieStand[]): string | null {
  if (standen.length === 1) return standen[0].id
  if (keuze !== null && standen.some((s) => s.id === keuze)) return keuze
  return null
}

/** "Oudste wacht sinds vandaag / gisteren / N dagen" — kalenderdagen in de lokale tijdzone. */
export function wachtSindsTekst(iso: string | null, nu: Date = new Date()): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  const dagStart = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const dagen = Math.max(0, Math.round((dagStart(nu) - dagStart(d)) / 86_400_000))
  if (dagen === 0) return 'Oudste wacht sinds vandaag'
  if (dagen === 1) return 'Oudste wacht sinds gisteren'
  return `Oudste wacht al ${dagen} dagen`
}

export function vragenChipTekst(aantal: number): string {
  return aantal === 1 ? '💬 1 vraag aan u' : `💬 ${aantal} vragen aan u`
}
