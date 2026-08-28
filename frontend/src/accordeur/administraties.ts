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
  /** Administratie-id (scope). */
  id: string
  /** Kaartsleutel (blok A 28-08): `administratie_id` of `administratie_id|afdeling_id` — één
   * kaart per afdeling van dezelfde BV zodat tellers eenduidig blijven (mockup afdelingen.html §3). */
  sleutel: string
  /** Weergavenaam: "Kempen Facilities · Buitendienst" bij een afdeling, anders de administratienaam. */
  naam: string | null
  afdelingId: string | null
  afdelingNaam: string | null
  /** Aantal te accorderen facturen in deze administratie. */
  teAccorderen: number
  /** Aantal open vragen van het kantoor aan déze accordeur (op de kaart én los). */
  vragen: number
  /** ISO-tijdstip van de langst wachtende factuur (null = alleen vragen). */
  oudsteWacht: string | null
}

/** Kaartsleutel van een wachtrij-item: per (administratie, afdeling). */
export function kaartSleutel(item: { administratie_id: string; afdeling_id?: string | null }): string {
  return item.afdeling_id ? `${item.administratie_id}|${item.afdeling_id}` : item.administratie_id
}

/** Administratie-id uit een kaartsleutel (vragen dragen geen afdeling — zij filteren op de BV). */
export function administratieVanSleutel(sleutel: string): string {
  return sleutel.split('|')[0]
}

/** Groepeert per administratie × afdeling; alleen kaarten met werk komen terug. Een vraag draagt
 * geen afdeling: die telt op de eerste kaart van haar administratie (of een eigen BV-kaart als er
 * geen facturen wachten). */
export function administratiesMetWerk(items: WachtrijItemDto[], vragen: AccordeurVraagDto[]): AdministratieStand[] {
  const per = new Map<string, AdministratieStand>()
  const stand = (
    sleutel: string,
    id: string,
    naam: string | null,
    afdelingId: string | null,
    afdelingNaam: string | null,
  ): AdministratieStand => {
    let s = per.get(sleutel)
    if (!s) {
      s = { id, sleutel, naam, afdelingId, afdelingNaam, teAccorderen: 0, vragen: 0, oudsteWacht: null }
      per.set(sleutel, s)
    } else if (!s.naam && naam) {
      s.naam = naam
    }
    return s
  }
  for (const item of items) {
    const afdelingNaam = item.afdeling_naam ?? null
    const naam = item.administratie_naam
      ? afdelingNaam
        ? `${item.administratie_naam} · ${afdelingNaam}`
        : item.administratie_naam
      : null
    const s = stand(kaartSleutel(item), item.administratie_id, naam, item.afdeling_id ?? null, afdelingNaam)
    s.teAccorderen += 1
    if (s.oudsteWacht === null || item.aangeboden_op < s.oudsteWacht) s.oudsteWacht = item.aangeboden_op
  }
  for (const vraag of vragen) {
    const bestaande = [...per.values()].find((s) => s.id === vraag.administratie_id)
    const s = bestaande ?? stand(vraag.administratie_id, vraag.administratie_id, vraag.administratie_naam, null, null)
    s.vragen += 1
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
  if (standen.length === 1) return standen[0].sleutel
  if (keuze !== null && standen.some((s) => s.sleutel === keuze)) return keuze
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
