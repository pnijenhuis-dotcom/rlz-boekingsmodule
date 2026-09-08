// "Mogelijk dubbel in RLZ" — blok 6 (08-09), reconciliatie-blok `rlz_dubbel` (app/reconciliatie/rlz_dubbel.py).
// Twee inkoopfacturen van dezelfde crediteur in Reeleezee met dezelfde referentie en/of hetzelfde bedrag op dezelfde
// datum, waarvan minstens één NIET via de module geboekt is (handmatig ingevoerd). Er is geen document in de app en
// geen bekende URL-vorm van de RLZ-web-UI per document, dus de handeling is: beide boekstuknummers openen in
// Reeleezee en dáár beoordelen (de app verwijdert nooit — kernprincipe 3). Accepteren met reden blijft de tweede knop
// (Beheerder) via de generieke rij in ReconciliatieScreen. Tekstknop = linkbtn (kopieert het boekstuknummer).
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

export function RlzDubbelBoekstukken({ bevinding }: { bevinding: BevindingDto }) {
  const boekstukken = [tekst(bevinding.detail, 'boekstuk_a'), tekst(bevinding.detail, 'boekstuk_b')].filter(
    (x): x is string => x !== null,
  )
  const kopieer = (nummer: string) => {
    try {
      void navigator.clipboard?.writeText(nummer)
    } catch {
      /* clipboard niet beschikbaar (bv. http zonder secure context) — de tekst staat gewoon op het scherm */
    }
  }
  return (
    <span className="hint" data-testid="rlz-dubbel-boekstukken" style={{ marginRight: 8 }}>
      Open in Reeleezee:{' '}
      {boekstukken.length === 0 ? (
        <span>boekstuknummers onbekend (zie details)</span>
      ) : (
        boekstukken.map((nummer, i) => (
          <span key={nummer}>
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
