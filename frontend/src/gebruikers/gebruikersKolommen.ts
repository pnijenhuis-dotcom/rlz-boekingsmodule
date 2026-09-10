/** Kolombreedtes van de tabellen op Gebruikers & toegang — ÉÉN bron voor de `<colgroup>`, de
 * `<th>`-minima en de regressietest (blok 2 vervolgrun 10-09 avond, kliktest Peter 10-09).
 *
 * De implosie: auto-layout zonder minima + een actiekolom `white-space: nowrap` met 3–5 tekstknoppen
 * ("E-mail wijzigen", "Blokkeren", "Archiveren", "Opnieuw mailen" + de zelfbeschermings-hint) —
 * de actiekolom pakte op een breed scherm zijn max-content-breedte (~450 px) en Beveiliging/Status
 * kregen wat overbleef: kop "BE…", slot- en sleutel-iconen over elkaar, tabel scrolt intern.
 *
 * Fix (zelfde regel als het controlescherm, `document/boekingsregelsKolommen.ts`): elke kolom een
 * absolute minimumbreedte in px, `<col>`-breedtes in px, `table-layout: fixed` en de tabel een
 * `min-width` = de som — boven de som verdelen de kolommen de extra ruimte evenredig, onder de som
 * scrolt de tabel horizontaal bínnen `.tabel-scroll` (actiekolom sticky, patroon 25-08 3e) in
 * plaats van kolommen kapot te drukken. Koppen zijn `white-space: nowrap`, nooit een ellipsis.
 * Acties volgen de UX-norm "één primaire knop + ⋯" (BESLISSINGEN "UX-PATRONEN ALS NORM").
 *
 * De minima zijn GEMETEN (headless Chrome, harnas `harness-gebruikers.html?breed=1&meet=1`: natuurlijke
 * max-content-breedte per kolom bij de langste namen/e-mails en álle beveiligings-/statuschips aan)
 * en afgerond naar boven; de kop is bij Rechten en Staande goedkeuringen de maat.
 *
 * NB jsdom kent geen layout: `gebruikersKolommen.test.ts` toetst de som tegen de beschikbare breedte
 * uit dezelfde bron en dat élke kolom zijn minimum draagt; de échte pixels meet `overflow_sweep.sh`
 * (harnas ?breed=1) in Chrome. */

/** Shell.css `.sidebar { width: 236px }` (vanaf 1025 px; 180 px op ≤ 1024). */
export const ZIJBALK_PX = 236
/** Shell.css `.content { padding: 26px 34px }` — links + rechts. */
export const CONTENT_PADDING_PX = 34
/** components.css `.panel { padding: 18px 20px }` — de tabel staat in een panel. */
export const PANEL_PADDING_PX = 20
/** `.tabel-scroll` en `table` hebben 1 px rand — verwaarloosbaar, maar wel meegeteld. */
export const TABEL_RAND_PX = 2

/** Netto breedte die de tabel op een viewport tot zijn beschikking heeft (zijbalk, content- en
 * panel-padding eraf). 1170 → 824 px, 1440 → 1094 px. */
export function beschikbareBreedte(viewportPx: number): number {
  return viewportPx - ZIJBALK_PX - 2 * CONTENT_PADDING_PX - 2 * PANEL_PADDING_PX - TABEL_RAND_PX
}

export type GebruikersTab = 'kantoor' | 'veldwerkers' | 'accordeurs'

export interface GebruikersKolom {
  sleutel: string
  /** Kolomkop zoals gerenderd (leeg = actiekolom zonder kop). */
  kop: string
  /** Absolute ondergrens in px (incl. celpadding 2 × 8 px, `.gebruikers-tabel th/td`). */
  minPx: number
}

/** Actiekolom: "Opnieuw mailen" (secundair, klein: ~114 px) of "Herstel-link" + ⋯ (tekstknop ~26 px) + gap 6 + celpadding 16
 * — gemeten 161 px, afgerond 164. */
const ACTIES: GebruikersKolom = { sleutel: 'acties', kop: '', minPx: 164 }

export const GEBRUIKERS_KOLOMMEN: Record<GebruikersTab, readonly GebruikersKolom[]> = {
  kantoor: [
    /** Naam (bold 13) + e-mail (11, ellipsis mét title boven de ondergrens) — de rest-kolom, groeit als eerste mee. */
    { sleutel: 'gebruiker', kop: 'Gebruiker', minPx: 172 },
    /** Rol-select ("Boekhouding + Projecten") óf rol-badge, daaronder de scope-badge ("N administraties" /
     * "alle administraties"); scope wijzigen zit in het ⋯-menu. */
    { sleutel: 'rol', kop: 'Rol · scope', minPx: 196 },
    /** Twee module-rechten als gelabelde switches onder elkaar ("Meerwerk & urenstaten", "Veldwerkerbeheer"). */
    { sleutel: 'rechten', kop: 'Rechten', minPx: 186 },
    /** "🔑 2 passkeys" + "🔐 TOTP" óf "geen TOTP" + "geen passkey" — op één regel. */
    { sleutel: 'beveiliging', kop: 'Beveiliging', minPx: 196 },
    /** Één statusbadge ("actief", "geblokkeerd", "uitgenodigd", "activatie onderbroken") + detailregel eronder. */
    { sleutel: 'status', kop: 'Status', minPx: 166 },
    ACTIES,
  ],
  veldwerkers: [
    { sleutel: 'veldwerker', kop: 'Veldwerker', minPx: 180 },
    /** Rol-badge ("Detacheerder"). */
    { sleutel: 'rol', kop: 'Rol', minPx: 112 },
    /** Projecttoegang / ZZP'ers / crediteur-badges + linkbtns — wrapt binnen de kolom, de rest-kolom. */
    { sleutel: 'koppelingen', kop: 'Koppelingen', minPx: 280 },
    /** Statusbadge + "half geactiveerd — geen toestel" + dossier-badge op één regel (gemeten uitvoerder-rij: chips ≈ 332 px
     * + celpadding 16); herstel-/⚠-details eronder. */
    { sleutel: 'status', kop: 'Status', minPx: 348 },
    ACTIES,
  ],
  accordeurs: [
    /** Naam + statuschips op één regel + e-mail. */
    { sleutel: 'accordeur', kop: 'Accordeur', minPx: 236 },
    /** Tot twee administratie-badges of "N administraties" + linkbtn "beheren". */
    { sleutel: 'administraties', kop: 'Administraties', minPx: 196 },
    /** Per apparaat: chip "📱 Toestel · naam (platform)" (ellipsis mét title) + linkbtn Kill-switch, detailregel eronder. */
    { sleutel: 'apparaten', kop: 'Apparaten', minPx: 256 },
    /** De kop is de maat ("STAANDE GOEDKEURINGEN", 10,5 px kapitaal + letterspatiëring). */
    { sleutel: 'goedkeuringen', kop: 'Staande goedkeuringen', minPx: 180 },
    ACTIES,
  ],
}

/** Som van de kolomminima = de `min-width` van de tabel; daaronder scrolt `.tabel-scroll`. */
export function minimaleTabelbreedte(tab: GebruikersTab): number {
  return GEBRUIKERS_KOLOMMEN[tab].reduce((som, k) => som + k.minPx, 0)
}

/** Inline-stijl voor een `<col>`: vaste px-breedte (fixed layout verdeelt extra ruimte evenredig). */
export function kolomStijl(k: GebruikersKolom): { width: number } {
  return { width: k.minPx }
}

/** Inline-stijl voor de `<th>`: het minimum als `minWidth` (leesbaar voor de regressietest; in fixed
 * layout bepaalt de `<col>` de breedte, dit is de gordel bij de broek). */
export function kopStijl(k: GebruikersKolom): { minWidth: number } {
  return { minWidth: k.minPx }
}
