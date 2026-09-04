// Mapping DocumentStatus (backend, app/documenten/models.py) -> label + mockup-chipklasse.
export const STATUS_LABELS: Record<string, string> = {
  ontvangen: 'Ontvangen',
  extractie_wachtrij: 'In wachtrij (extractie)',
  extractie_bezig: 'Extractie bezig',
  te_controleren: 'Te controleren',
  klaar_om_te_boeken: 'Klaar om te boeken',
  geboekt: 'Geboekt',
  vraag_open: 'Vraag open',
  // Mockup werkvoorraad: de afgewezen-chip draagt de ter-controle-lading expliciet.
  afgewezen: 'Afgewezen — ter controle',
  boeken_mislukt: 'Boeken mislukt',
  niet_toegewezen: 'Niet toegewezen',
  handmatig_afmaken: 'Handmatig afmaken',
  // IBAN-wissel vier-ogen-accordering (PART B 2026-07-15, chip-tekst conform de goedgekeurde
  // flow).
  wacht_op_iban_accordering: 'IBAN-wissel — wacht op accordering',
  // Klant-accorderingsflow (migratie 0033): mockup-kolom "Bij klant".
  ter_accordering: 'Bij klant — ter accordering',
  verwijderd: 'Verwijderd',
  // Nabundel-nazorg dubbelparen (03-09): een UBL-exemplaar dat in het PDF-document van dezelfde
  // factuur is opgenomen — terminaal, leeft door in het leidende document.
  samengevoegd: 'Samengevoegd',
  gesplitst: 'Gesplitst',
  // Verplichtingen (blok B 04-09): eindstand ná het laatste klant-akkoord — er wordt niets
  // geboekt, het akkoord (wie/wanneer/welk bedrag) ís het resultaat.
  geaccordeerd: 'Geaccordeerd',
}

/** Statuslabels die per DOCUMENTSOORT afwijken (blok B 04-09): een verplichting wordt niet
 * geboekt, dus "Klaar om te boeken" heet daar "Klaar voor accordering" — puur een label, de
 * status en de statusmachine zijn ongewijzigd. */
export const STATUS_LABELS_PER_SOORT: Record<string, Record<string, string>> = {
  verplichting: {
    klaar_om_te_boeken: 'Klaar voor accordering',
  },
}

export const STATUS_CHIP_KLASSE: Record<string, string> = {
  ontvangen: 'ai',
  extractie_wachtrij: 'ai',
  extractie_bezig: 'ai',
  te_controleren: 'ai',
  klaar_om_te_boeken: 'klaar',
  geboekt: 'geboekt',
  vraag_open: 'vraag',
  afgewezen: 'vraag',
  boeken_mislukt: 'vraag',
  niet_toegewezen: 'vraag',
  handmatig_afmaken: 'vraag',
  wacht_op_iban_accordering: 'vraag',
  ter_accordering: 'geheugen',
  verwijderd: 'geboekt',
  samengevoegd: 'geboekt',
  gesplitst: 'geboekt',
  // Statusgroen (--ok), net als geboekt: het akkoord is een afgeronde stand, geen actie.
  geaccordeerd: 'geboekt',
}

/** Statussen waarin de achtergrondextractie nog loopt (async extractie): werkvoorraad en
 * detailscherm pollen dan tot de worker klaar is — nooit een blokkerende spinner. */
export function extractieActief(status: string): boolean {
  return status === 'extractie_wachtrij' || status === 'extractie_bezig'
}

/** Statuslabel, optioneel soort-bewust (blok B 04-09) — zonder `soort` blijft het gedrag exact
 * zoals het was, zodat alle bestaande aanroepen ongewijzigd werken. */
export function statusLabel(status: string, soort?: string | null): string {
  if (soort) {
    const perSoort = STATUS_LABELS_PER_SOORT[soort]?.[status]
    if (perSoort) return perSoort
  }
  return STATUS_LABELS[status] ?? status
}

export function statusChipKlasse(status: string): string {
  return STATUS_CHIP_KLASSE[status] ?? 'geheugen'
}
