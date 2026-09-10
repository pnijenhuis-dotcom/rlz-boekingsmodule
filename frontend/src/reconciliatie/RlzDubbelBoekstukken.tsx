// "Mogelijk dubbel in RLZ" — blok 6 (08-09), reconciliatie-blok `rlz_dubbel` (app/reconciliatie/rlz_dubbel.py).
// Sinds blok 1 vervolgrun 10-09 avond is de bevinding een CLUSTER: N ≥ 2 inkoopfacturen van dezelfde crediteur in
// Reeleezee met dezelfde referentie, waarvan minstens één NIET via de module geboekt is (handmatig ingevoerd). Het
// detail draagt `boekstukken: string[]` (alle exemplaren, op datum) en `waarschijnlijk_dubbel` (twee concepten,
// zelfde dag, zelfde bedrag); oudere bevindingen dragen alleen `boekstuk_a`/`boekstuk_b` — die terugval blijft.
// Er is geen document in de app en geen bekende URL-vorm van de RLZ-web-UI per document, dus de handeling is: alle
// boekstuknummers openen in Reeleezee en dáár beoordelen (de app verwijdert nooit — kernprincipe 3). Accepteren met
// reden blijft de tweede knop (Beheerder) via de generieke rij in ReconciliatieScreen. Tekstknop = linkbtn (kopieert).
import type { BevindingDto } from './reconciliatieApi'

export const RLZ_DUBBEL_SOORT = 'dubbel_in_rlz'

/** Is dit de rij waarop de boekstuk-weergave hoort? (één regel in `actieVoor`, patroon isVerdwenenDocument). */
export function isRlzDubbel(r: BevindingDto): boolean {
  return r.blok === 'rlz_dubbel' && r.detail?.afwijking_soort === RLZ_DUBBEL_SOORT
}

function tekst(d: Record<string, unknown> | null, sleutel: string): string | null {
  const v = d?.[sleutel]
  return typeof v === 'string' && v.trim() !== '' ? v : null
}

/** Alle boekstuknummers van het cluster; terugval op de A/B-velden van een paar-bevinding van vóór 10-09. */
export function rlzDubbelBoekstukken(d: Record<string, unknown> | null): string[] {
  const lijst = d?.boekstukken
  if (Array.isArray(lijst)) {
    const uit = lijst.filter((x): x is string => typeof x === 'string' && x.trim() !== '')
    if (uit.length > 0) return uit
  }
  return [tekst(d, 'boekstuk_a'), tekst(d, 'boekstuk_b')].filter((x): x is string => x !== null)
}

export function RlzDubbelBoekstukken({ bevinding }: { bevinding: BevindingDto }) {
  const boekstukken = rlzDubbelBoekstukken(bevinding.detail)
  const waarschijnlijk = bevinding.detail?.waarschijnlijk_dubbel === true
  const kopieer = (nummer: string) => {
    try {
      void navigator.clipboard?.writeText(nummer)
    } catch {
      /* clipboard niet beschikbaar (bv. http zonder secure context) — de tekst staat gewoon op het scherm */
    }
  }
  return (
    <span className="hint" data-testid="rlz-dubbel-boekstukken" style={{ marginRight: 8 }}>
      {waarschijnlijk && (
        <span className="chip afwijking" data-testid="rlz-dubbel-waarschijnlijk" style={{ marginRight: 6 }}>
          waarschijnlijk dubbel
        </span>
      )}
      Open in Reeleezee:{' '}
      {boekstukken.length === 0 ? (
        <span>boekstuknummers onbekend (zie details)</span>
      ) : (
        boekstukken.map((nummer, i) => (
          <span key={`${nummer}-${i}`}>
            {i > 0 && ' · '}
            <button
              type="button"
              className="linkbtn"
              aria-label={`Boekstuknummer ${nummer} kopiëren`}
              title="Kopieer het boekstuknummer en zoek het op in Reeleezee"
              onClick={() => kopieer(nummer)}
            >
              {nummer}
            </button>
          </span>
        ))
      )}
    </span>
  )
}
