import type { GeboektInRlzDto } from '../api/types'

/** Blok C 02-09 (Elissen-casus): "Geboekt in RLZ · boekstuk <nr> · <crediteur/debiteur>" mét de
 * vindplaats-hint voor verkoop-/omzetdocumenten (die staan in RLZ níét onder Verkopen → Facturen).
 * De data komt kant-en-klaar van de server (boek-events/kolommen, geen RLZ-call); dit bestand is de
 * enige presentatie ervan: lijst-tooltip, detailkop-chip en de regel op de reviewschermen. */

export function geboektInRlzTooltip(stand: GeboektInRlzDto): string {
  // Odoo-adapter blok E (03-09), additief: de kruisverwijzing van een tegenboeking ("Reversal · RBILL/… ↔
  // BILL/…") als eigen tooltip-regel; slotstuk 04-09 (A2): de verschoven boekdatum idem. Niets verandert voor
  // een RLZ-stand zonder die velden.
  return [stand.regel, stand.kruisverwijzing ?? null, stand.boekdatum_verschoven ?? null, stand.vindplaats_hint].filter(Boolean).join('\n')
}

/** Slotstuk 04-09 (A2): de Odoo-boekdatum is deterministisch naar de eerste dag van de eerstvolgende open periode
 * verschoven omdat de factuurdatum in een afgesloten (aangegeven) periode valt — factuurdatum ongewijzigd. */
function BoekdatumVerschovenChip({ regel }: { regel: string }) {
  return (
    <span className="chip afwijking" data-testid="boekdatum-verschoven-chip" title={regel}>
      boekdatum verschoven
    </span>
  )
}

/** ± € 0,02-btw-cent-override (Odoo-adapter, blok C): draagt zijn bestaande chip óók hier (mockup §3). */
function BtwOverrideChip() {
  return (
    <span className="chip afwijking" data-testid="btw-override-chip" title="Btw per tarief ± € 0,02 bijgesteld zodat het factuurtotaal cent-exact klopt">
      btw-cent-override
    </span>
  )
}

/** Chip in de detailkop, naast de statuschip — de hint als tooltip. */
export function GeboektInRlzChip({ stand }: { stand: GeboektInRlzDto }) {
  return (
    <>
      <span className="chip geheugen" data-testid="geboekt-in-rlz-chip" title={geboektInRlzTooltip(stand)}>
        {stand.regel}
      </span>
      {stand.btw_override && (
        <>
          {' '}
          <BtwOverrideChip />
        </>
      )}
      {stand.boekdatum_verschoven && (
        <>
          {' '}
          <BoekdatumVerschovenChip regel={stand.boekdatum_verschoven} />
        </>
      )}
    </>
  )
}

/** Regel op een reviewscherm (verkoop/omzet/inkoop): één zin + kruisverwijzing + de vindplaats-hint eronder. */
export function GeboektInRlzRegel({ stand }: { stand: GeboektInRlzDto }) {
  return (
    <p className="hint" data-testid="geboekt-in-rlz-regel" style={{ marginTop: 0 }}>
      <b>{stand.regel}</b>
      {stand.btw_override && (
        <>
          {' '}
          <BtwOverrideChip />
        </>
      )}
      {stand.kruisverwijzing && (
        <>
          <br />
          <span data-testid="geboekt-kruisverwijzing">{stand.kruisverwijzing}</span>
        </>
      )}
      {stand.boekdatum_verschoven && (
        <>
          <br />
          <BoekdatumVerschovenChip regel={stand.boekdatum_verschoven} /> <span data-testid="geboekt-boekdatum-verschoven">{stand.boekdatum_verschoven}</span>
        </>
      )}
      {stand.vindplaats_hint && (
        <>
          <br />
          {stand.vindplaats_hint}
        </>
      )}
    </p>
  )
}
