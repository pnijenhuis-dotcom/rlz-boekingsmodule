import type { GeboektInRlzDto } from '../api/types'

/** Blok C 02-09 (Elissen-casus): "Geboekt in RLZ · boekstuk <nr> · <crediteur/debiteur>" mét de
 * vindplaats-hint voor verkoop-/omzetdocumenten (die staan in RLZ níét onder Verkopen → Facturen).
 * De data komt kant-en-klaar van de server (boek-events/kolommen, geen RLZ-call); dit bestand is de
 * enige presentatie ervan: lijst-tooltip, detailkop-chip en de regel op de reviewschermen. */

export function geboektInRlzTooltip(stand: GeboektInRlzDto): string {
  return stand.vindplaats_hint ? `${stand.regel}\n${stand.vindplaats_hint}` : stand.regel
}

/** Chip in de detailkop, naast de statuschip — de hint als tooltip. */
export function GeboektInRlzChip({ stand }: { stand: GeboektInRlzDto }) {
  return (
    <span className="chip geheugen" data-testid="geboekt-in-rlz-chip" title={geboektInRlzTooltip(stand)}>
      {stand.regel}
    </span>
  )
}

/** Regel op een reviewscherm (verkoop/omzet/inkoop): één zin + de vindplaats-hint eronder. */
export function GeboektInRlzRegel({ stand }: { stand: GeboektInRlzDto }) {
  return (
    <p className="hint" data-testid="geboekt-in-rlz-regel" style={{ marginTop: 0 }}>
      <b>{stand.regel}</b>
      {stand.vindplaats_hint && (
        <>
          <br />
          {stand.vindplaats_hint}
        </>
      )}
    </p>
  )
}
