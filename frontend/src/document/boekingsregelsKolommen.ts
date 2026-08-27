/** Kolombreedtes van de boekingsregels-tabel op het controlescherm — ÉÉN bron voor de
 * `<colgroup>` in BoekvoorstelPanel én de regressietest (addendum kantoor-run 27-08 punt 4,
 * screenshot Peter ARVUM/Port of Rotterdam).
 *
 * De implosie: `table-layout: fixed` + procentuele kolommen + één vaste `min-width: 560px` gaf in
 * een smal rechterpaneel een omschrijving-kolom (de rest-kolom) van ~26 px bij projectplicht —
 * en `overflow-wrap: anywhere` brak elk woord dan per LETTER af; de zoekvelden (grootboek/btw/
 * project) krompen tot 22%/17%/14% van 560 px = onbruikbaar.
 *
 * Fix: elke kolom een absolute minimumbreedte in px, de omschrijving een eigen ondergrens, en de
 * tabel een `min-width` = de som daarvan (inline style, uit deze constanten) zodat een té smal
 * paneel overgaat in horizontale tabel-scroll bínnen `.tabel-scroll` (bestaand patroon) in plaats
 * van kolommen kapot te drukken. Boven die som krijgt de omschrijving de resterende ruimte.
 *
 * NB de overflow-sweep meet pagina-overflow en vangt kolom-implosie principieel niet (dezelfde
 * les-klasse als AnkerPopup) — daarom bewaakt `boekingsregelsKolommen.test.ts` deze waarden en
 * `BoekvoorstelPanel.test.tsx` de gerenderde `<col>`-breedtes + tabel-min-width. */

export const KOLOM_PX = {
  /** Zoek-combobox grootboek: "4699 · Diverse kosten" leesbaar tot ~18 tekens; de listbox is altijd
   * ≥ 280 px (SearchableCombobox.MIN_LEESBARE_BREEDTE) dus de volledige naam blijft bereikbaar. */
  grootboek: 150,
  /** Zoek-combobox btw-code: "21% · NL Hoog" past. */
  btw: 116,
  /** Zoek-combobox project (alleen bij projectplicht): "26127 Tilburg (…)" — de code blijft zichtbaar. */
  project: 136,
  /** Geld altijd volledig leesbaar: 104 px past "123.456,78" incl. input- en celpadding. */
  netto: 104,
  btwBedrag: 104,
  /** De ×-knop (regel verwijderen). */
  verwijder: 30,
} as const

/** Ondergrens voor de omschrijving-kolom: ~24 tekens op 12,5 px — genoeg om op WOORDgrenzen te
 * wrappen; alleen één onafbreekbaar token langer dan deze breedte breekt nog binnen het woord
 * (`overflow-wrap: break-word`, nooit `anywhere`/`break-all`). */
export const OMSCHRIJVING_MIN_PX = 168

/** Som van alle kolomminima = de `min-width` van de tabel; daaronder scrollt `.tabel-scroll`. */
export function minimaleTabelbreedte(metProject: boolean): number {
  const vast =
    KOLOM_PX.grootboek + KOLOM_PX.btw + KOLOM_PX.netto + KOLOM_PX.btwBedrag + KOLOM_PX.verwijder + OMSCHRIJVING_MIN_PX
  return vast + (metProject ? KOLOM_PX.project : 0)
}
