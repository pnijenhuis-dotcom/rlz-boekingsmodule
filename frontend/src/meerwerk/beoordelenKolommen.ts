/** Kolombreedtes van de tabel Beoordelen › Urenstaten (bug 18-09) — zelfde patroon en dezelfde bron-constanten als
 * Gebruikers & toegang (`gebruikers/gebruikersKolommen.ts`, blok 2 vervolgrun 10-09): elke kolom een absolute
 * px-ondergrens, `<col>` in px, `table-layout: fixed`, tabel-`min-width` = de som; boven de som verdelen de kolommen
 * de ruimte evenredig, eronder scrolt de tabel intern in `.tabel-scroll` mét sticky actiekolom — nooit kolom-implosie.
 * Acties: één primaire knop (Goedkeuren) + ⋯ (Afkeuren…, Weekstaat openen). NB jsdom meet geen pixels
 * (`beoordelenKolommen.test.ts` toetst de bron en de render); de échte pixels meet `overflow_sweep.sh` via het
 * werkvoorraad-harnas `?beoordelen=1`. */
import { beschikbareBreedte, type GebruikersKolom } from '../gebruikers/gebruikersKolommen'

export { beschikbareBreedte }

export const BEOORDELEN_KOLOMMEN: readonly GebruikersKolom[] = [
  /** Naam veldwerker (bold) + "ingediend door <detacheerder> (namens)" eronder. */
  { sleutel: 'veldwerker', kop: 'Veldwerker', minPx: 176 },
  /** Projectnaam ("26129 Hilversum, Larenseweg 125 (Huvanco)") — de rest-kolom, wrapt op woordgrenzen. */
  { sleutel: 'project', kop: 'Project', minPx: 240 },
  { sleutel: 'week', kop: 'Week', minPx: 96 },
  { sleutel: 'uren', kop: 'Uren', minPx: 88 },
  { sleutel: 'm2', kop: 'm²', minPx: 88 },
  /** "di 15 sep (wk 38) 09:41" */
  { sleutel: 'ingediend', kop: 'Ingediend op', minPx: 160 },
  /** "Goedkeuren" (klein, ~106 px) + ⋯ (26) + gap 6 + celpadding 16 → 154, afgerond 164 (zelfde maat als Gebruikers). */
  { sleutel: 'acties', kop: '', minPx: 164 },
]

export function minimaleBeoordelenBreedte(): number {
  return BEOORDELEN_KOLOMMEN.reduce((som, k) => som + k.minPx, 0)
}

/** Inline-stijl voor een `<col>`: vaste px-breedte (fixed layout verdeelt extra ruimte evenredig). */
export function colStijl(k: GebruikersKolom): { width: number } {
  return { width: k.minPx }
}
