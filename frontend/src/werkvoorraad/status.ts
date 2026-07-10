// Mapping DocumentStatus (backend, app/documenten/models.py) -> label + mockup-chipklasse.
export const STATUS_LABELS: Record<string, string> = {
  ontvangen: 'Ontvangen',
  extractie_bezig: 'Extractie bezig',
  te_controleren: 'Te controleren',
  klaar_om_te_boeken: 'Klaar om te boeken',
  geboekt: 'Geboekt',
  vraag_open: 'Vraag open',
  afgewezen: 'Afgewezen',
  boeken_mislukt: 'Boeken mislukt',
  niet_toegewezen: 'Niet toegewezen',
  handmatig_afmaken: 'Handmatig afmaken',
  verwijderd: 'Verwijderd',
}

export const STATUS_CHIP_KLASSE: Record<string, string> = {
  ontvangen: 'ai',
  extractie_bezig: 'ai',
  te_controleren: 'ai',
  klaar_om_te_boeken: 'klaar',
  geboekt: 'geboekt',
  vraag_open: 'vraag',
  afgewezen: 'vraag',
  boeken_mislukt: 'vraag',
  niet_toegewezen: 'vraag',
  handmatig_afmaken: 'vraag',
  verwijderd: 'geboekt',
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status
}

export function statusChipKlasse(status: string): string {
  return STATUS_CHIP_KLASSE[status] ?? 'geheugen'
}
