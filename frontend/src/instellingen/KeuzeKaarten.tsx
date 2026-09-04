import type { ReactNode } from 'react'

/* Keuzekaarten voor een "kies één van twee/drie"-stap in een wizard (fix C1, besluit Peter
 * 04-09). Vóór deze fix stond zo'n keuze als kale `<input type="radio">` in een `<label>` —
 * die erfde de globale `input`-regel uit components.css (width: 100% + padding + border +
 * accent-focus-box) en rendeerde als een uitgerekt vlak met een radiootje erin. Nu: de hele
 * kaart is het klikvlak, geselecteerd = teal rand + accent-vulling (designpass v2: teal =
 * actie), hover = lift, focus = ring.
 *
 * De native radio-semantiek blijft ONGEWIJZIGD: er staat een echte `input type="radio"` in de
 * kaart (visueel verborgen, wél focusbaar en wél aan het label gekoppeld), dus
 * toetsenbordnavigatie, screenreaders en `getByLabelText(...).toBeChecked()` in de tests
 * werken precies zoals daarvoor. */

export interface KeuzeKaartOptie<T extends string> {
  waarde: T
  /** Aria-label op de radio — de handgreep voor screenreaders én voor `getByLabelText` in tests. */
  ariaLabel: string
  /** Kop van de kaart (platformchip, vette titel, …). */
  kop: ReactNode
  /** Eén regel uitleg onder de kop. */
  uitleg: ReactNode
}

interface Props<T extends string> {
  /** Radiogroep-naam (uniek per dialoog). */
  naam: string
  waarde: T
  opties: KeuzeKaartOptie<T>[]
  onKies: (waarde: T) => void
}

export function KeuzeKaarten<T extends string>({ naam, waarde, opties, onKies }: Props<T>) {
  return (
    <div className="keuze-kaarten">
      {opties.map((optie) => {
        const gekozen = optie.waarde === waarde
        return (
          <label
            key={optie.waarde}
            className={`keuze-kaart${gekozen ? ' gekozen' : ''}`}
            data-testid={`keuze-kaart-${optie.waarde}`}
          >
            <input
              className="keuze-kaart-radio"
              type="radio"
              name={naam}
              value={optie.waarde}
              checked={gekozen}
              onChange={() => onKies(optie.waarde)}
              aria-label={optie.ariaLabel}
            />
            <span className="keuze-kaart-kop">{optie.kop}</span>
            <span className="hint keuze-kaart-uitleg">{optie.uitleg}</span>
          </label>
        )
      })}
    </div>
  )
}
