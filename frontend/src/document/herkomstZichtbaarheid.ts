/** Rustig controlescherm — "groen = niets tonen" (Peter 02-10, BESLISSINGEN "BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR,
 * RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)", punt 2).
 *
 * Peter (letterlijk): "Die velden onder crediteuren (AI 85% · herkend op btw-nummer NL · …) hoef ik allemaal niet te zien
 * … dit is weer van die info waar je wel naar kijkt en niks mee doet. verbergen" en "als het klopt niet tonen, maakt
 * alleen het beeldscherm heel druk en als het niet klopt past de medewerker het wel aan".
 *
 * Eén deterministische regel per chip, afgeleid uit de bestaande chip-klasse (designpass v2: groen = status, oranje =
 * bevestigen, rood = blokkade):
 * - AFWIJKING (`afwijking`, `blokkerend`, `vraag`) = altijd zichtbaar, als één regel onder het veld: conflict, onzeker
 *   onder de drempel, niet gevonden, meerduidig, "factuur noemt een ander project — kies zelf", "pinbon zegt …",
 *   "niet gelezen (afgedekt)", "btw herrekend (netto gewijzigd)", "weergave hersteld", KvK-mismatch, …
 * - HERKOMST (`ok`, `handmatig`, `geheugen`, `stil`, neutraal) = alleen onder "Herkomst tonen" per blok (crediteur,
 *   kopgegevens, boekingsregels): "AI 98 %", "uit factuur", "herkend op btw-nummer", "Geheugen 100 %", "uit template",
 *   "uit UBL", land-chip, KvK-/btw-nummer-chips, "ingekort", "standaard administratie", "uit geheugen", …
 * - `altijdTonen` = een chip die qua klasse rustig is maar inhoudelijk een afwijking: "week van de factuurdatum
 *   (aanname)" (periode NIET uit de factuur), "btw in kosten (niet aftrekbaar)", "samenvoegen niet mogelijk: …",
 *   "administratie niet btw-plichtig" (de enige inhoud van de cel).
 * Harde checks, de check-rij-acties en de oranje aangifte-check vallen hier bewust buiten (eigen tabel, ongewijzigd).
 * Puur (geen React) — de stand per blok leeft per browsersessie (sessionStorage, nooit server-state). */

export type ChipSoort = 'afwijking' | 'herkomst'

export type HerkomstBlok = 'crediteur' | 'kopgegevens' | 'regels'

export const HERKOMST_BLOKKEN: readonly HerkomstBlok[] = ['crediteur', 'kopgegevens', 'regels']

/** Chip-klassen (naast `chip`) die een afwijking betekenen — altijd zichtbaar. */
const AFWIJKING_KLASSEN: ReadonlySet<string> = new Set(['afwijking', 'blokkerend', 'vraag'])

/** Klasse-string (bv. "chip ok", "ok", "chip afwijking", "") → soort. `altijdTonen` maakt een rustige klasse tóch een
 * afwijking (inhoudelijke uitzonderingen, zie de module-docstring). */
export function chipSoort(klasse: string | null | undefined, altijdTonen = false): ChipSoort {
  if (altijdTonen) return 'afwijking'
  const tokens = (klasse ?? '')
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t !== '' && t !== 'chip')
  return tokens.some((t) => AFWIJKING_KLASSEN.has(t)) ? 'afwijking' : 'herkomst'
}

/** Mag deze chip in de huidige stand van het blok gerenderd worden? Afwijking = altijd; herkomst = alleen als het blok
 * op "Herkomst tonen" staat. */
export function chipZichtbaar(klasse: string | null | undefined, herkomstTonen: boolean, altijdTonen = false): boolean {
  return chipSoort(klasse, altijdTonen) === 'afwijking' || herkomstTonen
}

/** Periode-chip (punt 2, derde regel): alleen tonen als de periode NIET uit de factuur komt — de terugval "week van de
 * factuurdatum (aanname)" is een afwijking, "uit factuur"/"handmatig" is herkomst. */
export function periodeIsAanname(herkomst: string | null | undefined): boolean {
  return herkomst === 'afgeleid_van_factuurdatum'
}

export const HERKOMST_OPSLAGSLEUTEL_PREFIX = 'rlz.controle.herkomst.'

/** Stand per blok uit sessionStorage; ontbreekt/weigert = dicht (standaard: rustig). */
export function leesHerkomstStand(blok: HerkomstBlok, opslag: Pick<Storage, 'getItem'> | null = sessionOpslag()): boolean {
  try {
    return opslag?.getItem(HERKOMST_OPSLAGSLEUTEL_PREFIX + blok) === '1'
  } catch {
    return false
  }
}

export function bewaarHerkomstStand(
  blok: HerkomstBlok,
  aan: boolean,
  opslag: Pick<Storage, 'setItem' | 'removeItem'> | null = sessionOpslag(),
): void {
  try {
    if (aan) opslag?.setItem(HERKOMST_OPSLAGSLEUTEL_PREFIX + blok, '1')
    else opslag?.removeItem(HERKOMST_OPSLAGSLEUTEL_PREFIX + blok)
  } catch {
    // opslag geblokkeerd (privévenster/gewiste data): de stand leeft dan alleen in het scherm
  }
}

export function leesAlleHerkomstStanden(): Record<HerkomstBlok, boolean> {
  return {
    crediteur: leesHerkomstStand('crediteur'),
    kopgegevens: leesHerkomstStand('kopgegevens'),
    regels: leesHerkomstStand('regels'),
  }
}

function sessionOpslag(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage : null
  } catch {
    return null
  }
}
