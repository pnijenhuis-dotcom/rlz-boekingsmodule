/** Herkomst-chips voor regel-niveau voorstellen op het controlescherm (medewerker-wensen 04-09,
 * mockup projectverdeling-en-regelvoorstellen.html blok 2 + 3 — 1-op-1):
 * - grootboek per regel (blok D, backend `gb_bron`): groen "uit geheugen" (deterministisch, app-bevestigd),
 *   oranje "uit historie, nog niet bevestigd" (alleen RLZ-historie), oranje "geheugen wisselend" (conflict,
 *   jongste keuze), oranje "AI-voorstel — bevestig" (AI-classificatie tegen de historische grootboeken);
 * - btw-default van de administratie (blok E, backend `btw_bron = 'standaard'`): neutrale grijze chip
 *   "standaard administratie".
 * Pure beslislogica los van React (zelfde patroon als geheugenVoorstel.ts) zodat de chip-stand direct
 * unit-testbaar is. Teal = actie, groen = status, oranje = bevestigen (semantiek-regel designpass v2). */

export type GbBron = 'geheugen' | 'geheugen_seed' | 'geheugen_conflict' | 'ai'

export type BtwBron = 'factuur' | 'standaard'

export interface RegelChip {
  /** CSS-klassen naast `chip` — `ok` (groen), `afwijking` (oranje), `handmatig` (neutraal grijs), `blokkerend` (rood). */
  klasse: 'ok' | 'afwijking' | 'handmatig' | 'blokkerend'
  tekst: string
  titel: string
}

const GB_BRONNEN: ReadonlySet<string> = new Set<GbBron>(['geheugen', 'geheugen_seed', 'geheugen_conflict', 'ai'])

/** Server-waarde → gevalideerde bron; onbekende/lege waarden tellen als "geen voorstel". */
export function gbBronUitDto(waarde: string | null | undefined): GbBron | null {
  return waarde && GB_BRONNEN.has(waarde) ? (waarde as GbBron) : null
}

export function btwBronUitDto(waarde: string | null | undefined, taxrateId: string | null): BtwBron | null {
  if (!taxrateId) return null
  return waarde === 'factuur' || waarde === 'standaard' ? waarde : null
}

/** Chip-besluit voor het grootboek-veld: alleen zolang het voorstel nog in het veld staat én de mens het
 * veld niet zelf heeft aangeraakt (zelfde regel als de btw-chip "uit factuur"). */
export function bepaalGbChip(
  bron: GbBron | null,
  detail: string | null,
  huidigLedgerId: string | null,
  handmatig: boolean,
): RegelChip | null {
  if (!bron || !huidigLedgerId || handmatig) return null
  const toelichting = detail ? ` ${detail}.` : ''
  switch (bron) {
    case 'geheugen':
      return {
        klasse: 'ok',
        tekst: 'uit geheugen',
        titel: `Deterministisch regel-geheugen: deze omschrijving is bij deze leverancier eerder zo geboekt en door een mens bevestigd.${toelichting} De harde checks blijven de poort.`,
      }
    case 'geheugen_seed':
      return {
        klasse: 'afwijking',
        tekst: 'uit historie, nog niet bevestigd',
        titel: `Regel-geheugen uit de Reeleezee-historie — nog niet in de app bevestigd.${toelichting} Bevestigen (boeken) maakt 'm voortaan groen.`,
      }
    case 'geheugen_conflict':
      return {
        klasse: 'afwijking',
        tekst: 'geheugen wisselend — controleer',
        titel: `Deze omschrijving is bij deze leverancier op verschillende grootboeken geboekt; de jongste keuze staat vooringevuld.${toelichting}`,
      }
    case 'ai':
      return {
        klasse: 'afwijking',
        tekst: 'AI-voorstel — bevestig',
        titel: `AI-classificatie tegen de grootboeken die deze leverancier eerder gebruikte — een voorstel, geen geheugen.${toelichting} Bevestigen (boeken) of corrigeren leert het regel-geheugen; daarna is dezelfde omschrijving groen.`,
      }
  }
}

/** Chip-besluit voor de btw-default van de administratie (blok E). De factuur-chip blijft in het paneel
 * zelf (percentage in de tekst). */
export function bepaalBtwStandaardChip(bron: BtwBron | null, huidigTaxrateId: string | null, handmatig: boolean): RegelChip | null {
  if (bron !== 'standaard' || !huidigTaxrateId || handmatig) return null
  return {
    klasse: 'handmatig',
    tekst: 'standaard administratie',
    titel:
      'Standaard btw-voorstel van deze administratie (Instellingen › Boeken & AI) — vult alleen regels waar factuur en leverancier-geheugen niets opleveren. Controleer; de harde checks blijven de poort.',
  }
}

/* --- Overstap-vertaling van een OPEN boekvoorstel (Odoo-slotstuk 04-09, C1 hervertaling) ---------------------
 * Bij een Reeleezee → Odoo-overstap hervertaalt de server de regels van nog open boekvoorstellen via de bevestigde
 * mapping en legt per veld een informatief spoor vast (`boekvoorstel_regel.overstap_vertaling`). Twee chips:
 *   - oranje "vertaald bij overstap"  — het veld draagt nog exact de vertaalde Odoo-waarde (`naar_id`): controleer en boek;
 *   - rood   "niet vertaalbaar bij overstap — kies" — geen Odoo-tegenhanger in de mapping, veld is leeg gelaten.
 * Zelfde regel als de gb-/btw-chips: weg zodra de mens het veld aanraakt of een andere waarde in het veld staat. */

export type OverstapVeld = 'grootboek' | 'btw' | 'project'

export interface OverstapVeldVertaling {
  van_id: string | null
  van_code: string | null
  van_naam: string | null
  naar_id: string | null
  naar_code?: string | null
  naar_naam?: string | null
  reden?: string | null
}

export type OverstapVertaling = Partial<Record<OverstapVeld, OverstapVeldVertaling | null>> & { op?: string | null }

function alsTekst(w: unknown): string | null {
  return typeof w === 'string' && w !== '' ? w : null
}

function veldVertalingUit(w: unknown): OverstapVeldVertaling | null {
  if (!w || typeof w !== 'object') return null
  const o = w as Record<string, unknown>
  if (!('naar_id' in o) && !('van_id' in o)) return null
  return {
    van_id: alsTekst(o.van_id),
    van_code: alsTekst(o.van_code),
    van_naam: alsTekst(o.van_naam),
    naar_id: alsTekst(o.naar_id),
    naar_code: alsTekst(o.naar_code),
    naar_naam: alsTekst(o.naar_naam),
    reden: alsTekst(o.reden),
  }
}

/** Server-JSON → gevalideerd spoor; alles wat niet op de contractvorm lijkt telt als "geen spoor". */
export function overstapVertalingUitDto(waarde: unknown): OverstapVertaling | null {
  if (!waarde || typeof waarde !== 'object') return null
  const o = waarde as Record<string, unknown>
  const uit: OverstapVertaling = { op: alsTekst(o.op) }
  let iets = false
  for (const veld of ['grootboek', 'btw', 'project'] as const) {
    const v = veldVertalingUit(o[veld])
    if (v) {
      uit[veld] = v
      iets = true
    }
  }
  return iets ? uit : null
}

const VELD_LABEL: Record<OverstapVeld, string> = { grootboek: 'grootboekrekening', btw: 'btw-tarief', project: 'project' }

function rlzOmschrijving(v: OverstapVeldVertaling): string {
  return [v.van_code, v.van_naam].filter(Boolean).join(' ') || v.van_id || 'onbekend'
}

/** Chip-besluit per veld. `huidigId` = wat nu in het veld staat; `handmatig` = de mens raakte het veld aan. */
export function bepaalOverstapChip(
  vertaling: OverstapVeldVertaling | null | undefined,
  veld: OverstapVeld,
  huidigId: string | null,
  handmatig: boolean,
): RegelChip | null {
  if (!vertaling || handmatig) return null
  if (vertaling.naar_id != null) {
    if (huidigId !== vertaling.naar_id) return null
    const odoo = [vertaling.naar_code, vertaling.naar_naam].filter(Boolean).join(' ') || vertaling.naar_id
    return {
      klasse: 'afwijking',
      tekst: 'vertaald bij overstap',
      titel: `Reeleezee ${rlzOmschrijving(vertaling)} → Odoo ${odoo} — ${VELD_LABEL[veld]} bij de Odoo-overstap via de bevestigde rekening-mapping vertaald; controleer en boek. De harde checks blijven de poort.`,
    }
  }
  if (huidigId) return null
  return {
    klasse: 'blokkerend',
    tekst: 'niet vertaalbaar bij overstap — kies',
    titel: `${vertaling.reden ?? 'Geen Odoo-tegenhanger in de mapping bij de overstap'} — Reeleezee ${VELD_LABEL[veld]} ${rlzOmschrijving(vertaling)} is leeg gelaten; kies de Odoo-${VELD_LABEL[veld]}.`,
  }
}
