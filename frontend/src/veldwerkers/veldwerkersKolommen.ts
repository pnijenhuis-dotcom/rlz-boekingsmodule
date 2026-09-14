/** Kolombreedtes van de tabel op /veldwerkers — ÉÉN bron voor de `<colgroup>`, de `<th>`-minima en de
 * regressietest (veldwerkers-run 14-09, besluiten Peter 14-09 punt 1+2; zelfde regel als
 * `gebruikers/gebruikersKolommen.ts` en `document/boekingsregelsKolommen.ts`).
 *
 * Elke kolom een absolute minimumbreedte in px, `<col>`-breedtes in px, `table-layout: fixed` en de tabel een
 * `min-width` = de som — boven de som verdelen de kolommen de extra ruimte evenredig, onder de som scrolt de tabel
 * horizontaal bínnen `.tabel-scroll` (actiekolom sticky). Koppen `white-space: nowrap`, nooit een ellipsis.
 * Acties volgen de UX-norm "één primaire knop + ⋯" (BESLISSINGEN "UX-PATRONEN ALS NORM").
 *
 * De minima komen uit de gemeten Veldwerkers-tab van 10-09 (harnas `harness-gebruikers.html?breed=1&meet=1`) — de
 * Koppelingen- en Status-kolom zijn hier gesplitst in Koppelingen · Dossier · Status; de échte pixels meet
 * `overflow_sweep.sh` (harnas `harness-veldwerkers.html`). NB jsdom kent geen layout: `veldwerkersKolommen.test.ts`
 * toetst de som tegen de beschikbare breedte uit `gebruikersKolommen.beschikbareBreedte`. */

import type { GebruikersKolom } from '../gebruikers/gebruikersKolommen'

export type VeldwerkersKolom = GebruikersKolom

/** Actiekolom: primaire knop "Dossier" (secundair, klein ≈ 72 px) + ⋯ (≈ 26 px) + gap 6 + celpadding 16. */
const ACTIES: VeldwerkersKolom = { sleutel: 'acties', kop: '', minPx: 150 }

export const VELDWERKERS_KOLOMMEN: readonly VeldwerkersKolom[] = [
  /** Naam (bold 13) + e-mail (11, ellipsis mét title) — de rest-kolom, groeit als eerste mee. */
  { sleutel: 'veldwerker', kop: 'Veldwerker', minPx: 180 },
  /** Rol-badge ("Detacheerder"). */
  { sleutel: 'rol', kop: 'Rol', minPx: 112 },
  /** Projecttoegang / ZZP'ers / crediteur-badges — wrapt binnen de kolom. */
  { sleutel: 'koppelingen', kop: 'Koppelingen', minPx: 280 },
  /** Dossier-stand uit de bestaande DTO: "compleet" / "2 ontbreken" / "verlopen" / "1 ter controle" / "—". */
  { sleutel: 'dossier', kop: 'Dossier', minPx: 168 },
  /** Statusbadge + "half geactiveerd" op één regel; ⚠-correcties eronder. */
  { sleutel: 'status', kop: 'Status', minPx: 204 },
  ACTIES,
]

export function minimaleVeldwerkersTabelbreedte(): number {
  return VELDWERKERS_KOLOMMEN.reduce((som, k) => som + k.minPx, 0)
}
