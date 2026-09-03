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
}

/** Statussen waarin de achtergrondextractie nog loopt (async extractie): werkvoorraad en
 * detailscherm pollen dan tot de worker klaar is — nooit een blokkerende spinner. */
export function extractieActief(status: string): boolean {
  return status === 'extractie_wachtrij' || status === 'extractie_bezig'
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

export function statusChipKlasse(status: string): string {
  return STATUS_CHIP_KLASSE[status] ?? 'geheugen'
}
