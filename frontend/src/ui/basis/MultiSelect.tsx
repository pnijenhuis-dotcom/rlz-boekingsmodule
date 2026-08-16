import * as React from 'react'
import { cn } from './cn'
import { Checkbox } from './Checkbox'

/* Zoekbare MultiSelect — mockup/kantoor-modern.html .ms/.ms-gekozen (scope-kiezer, schaalbaar
 * tot 50+ administraties): zoekveld filtert, aanvinken kiest, gekozen items als chips eronder
 * met een ✕ om los te maken. Alles blijft in de DOM-flow (geen portal) — het patroon leeft in
 * modals en instellingenvelden. */
export interface MultiSelectOptie {
  waarde: string
  label: string
  /** Klein grijs label rechts in de optieregel (bv. rol/soort). */
  sub?: string
}

interface MultiSelectProps {
  opties: MultiSelectOptie[]
  waarden: string[]
  onChange: (waarden: string[]) => void
  zoekPlaceholder?: string
  leegTekst?: string
  className?: string
  disabled?: boolean
}

export function MultiSelect({
  opties,
  waarden,
  onChange,
  zoekPlaceholder = 'Zoek… (typ om te filteren)',
  leegTekst = 'Geen opties gevonden.',
  className,
  disabled,
}: MultiSelectProps) {
  const [zoek, setZoek] = React.useState('')
  const term = zoek.trim().toLowerCase()
  const zichtbaar = term
    ? opties.filter((o) => `${o.label} ${o.sub ?? ''}`.toLowerCase().includes(term))
    : opties
  const perWaarde = React.useMemo(() => new Map(opties.map((o) => [o.waarde, o])), [opties])

  function wissel(waarde: string, aan: boolean) {
    onChange(aan ? [...waarden, waarde] : waarden.filter((w) => w !== waarde))
  }

  return (
    <div className={className}>
      <div className="ms">
        <input
          type="text"
          value={zoek}
          onChange={(e) => setZoek(e.target.value)}
          placeholder={zoekPlaceholder}
          disabled={disabled}
          aria-label={zoekPlaceholder}
        />
        <div className="ms-lijst">
          {zichtbaar.length === 0 && <div className="ms-leeg">{leegTekst}</div>}
          {zichtbaar.map((o) => (
            <label key={o.waarde} className="ms-optie">
              <Checkbox
                checked={waarden.includes(o.waarde)}
                onChange={(e) => wissel(o.waarde, e.target.checked)}
                disabled={disabled}
              />
              {o.label}
              {o.sub && <small>{o.sub}</small>}
            </label>
          ))}
        </div>
      </div>
      {waarden.length > 0 && (
        <div className="ms-gekozen">
          {waarden.map((w) => (
            <span key={w} className={cn('scope-chip')}>
              {perWaarde.get(w)?.label ?? w}
              <button
                type="button"
                aria-label={`${perWaarde.get(w)?.label ?? w} verwijderen`}
                onClick={() => wissel(w, false)}
                disabled={disabled}
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
