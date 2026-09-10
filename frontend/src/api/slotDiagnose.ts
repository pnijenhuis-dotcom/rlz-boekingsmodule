// Laatste opslagfout van het app-slot (bugfix 10-09 "toegangscode wijzigen faalt op Android"): welke brug-
// aanroep (lees/schrijf/verwijder/wijzig) op welke opslagsleutel om welke reden mislukte. Puur lokaal
// (localStorage), nooit naar de server, en NOOIT een waarde — geen code, geen salt, geen wrap, geen token;
// alleen de sleutelNAAM en de afgekapte foutmelding van de plugin/adapter. Wordt als staart in de
// diagnoseregel van Instellingen › Toegang getoond (koudeStart.ts::diagnoseRegel), zodat een screenshot van
// een ZTE zegt wat er op dat toestel misging.

export const SLOTFOUT_OPSLAG_SLEUTEL = 'accordeur-laatste-slotfout'

export type SlotHandeling = 'lees' | 'schrijf' | 'verwijder' | 'wijzig' | 'instellen'

export interface BewaardeSlotfout {
  versie: 1
  /** ISO-tijdstip van de fout. */
  tijdstip: string
  handeling: SlotHandeling
  /** Naam van de opslagsleutel (bv. `appslot_slot`) — nooit de waarde. */
  sleutel: string
  /** Afgekapte reden (reject-tekst van de plugin of de eigen controle-uitkomst). */
  reden: string
}

export function bewaarLaatsteSlotfout(fout: { handeling: SlotHandeling; sleutel: string; reden: unknown }): void {
  const record: BewaardeSlotfout = {
    versie: 1,
    tijdstip: new Date().toISOString(),
    handeling: fout.handeling,
    sleutel: fout.sleutel,
    reden: String(fout.reden ?? 'onbekend').slice(0, 120),
  }
  try {
    localStorage.setItem(SLOTFOUT_OPSLAG_SLEUTEL, JSON.stringify(record))
  } catch {
    // opslag vol/geblokkeerd — diagnostiek mag nooit de app raken
  }
}

export function leesLaatsteSlotfout(): BewaardeSlotfout | null {
  try {
    const ruw = localStorage.getItem(SLOTFOUT_OPSLAG_SLEUTEL)
    if (!ruw) return null
    const record = JSON.parse(ruw) as Partial<BewaardeSlotfout>
    if (record.versie !== 1 || typeof record.tijdstip !== 'string' || typeof record.handeling !== 'string') return null
    return record as BewaardeSlotfout
  } catch {
    return null
  }
}

export function wisLaatsteSlotfout(): void {
  try {
    localStorage.removeItem(SLOTFOUT_OPSLAG_SLEUTEL)
  } catch {
    // zie boven
  }
}
