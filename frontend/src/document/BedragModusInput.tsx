import { useEffect, useState } from 'react'
import { bedragAlsGetal } from './bedrag'
import { evalueerBedragExpressie, formatBedragInvoer, isExpressie } from './bedragExpressie'
import { type BedragModus, rekenOm } from './bedragModus'

function formatInvoer(waarde: number): string {
  return waarde.toFixed(2).replace('.', ',')
}

/** Bedragveld dat in de gekozen modus (netto/bruto) getoond én getypt wordt terwijl de opgeslagen waarde in de
 * `bron`-modus blijft (inkoopregels: netto; kassaregels: bruto). Tijdens het typen blijft de tekst van de gebruiker
 * staan (geen heen-en-weer-afronding); ná blur of een externe wijziging volgt de tekst de opgeslagen waarde. Zonder
 * percentage (geen btw-code) is omrekenen onmogelijk: het veld blijft in de bron-modus mét tooltip. */
export function BedragModusInput({
  waarde,
  bron,
  modus,
  percentage,
  onWijzig,
  ariaLabel,
  disabled,
  className,
  title,
  style,
}: {
  /** Opgeslagen waarde als tekst in de `bron`-modus (NL-invoer toegestaan). */
  waarde: string
  bron: BedragModus
  modus: BedragModus
  percentage: number | undefined
  /** Nieuwe waarde in de `bron`-modus (genormaliseerd naar "1234,56" bij omrekening, anders de getypte tekst). */
  onWijzig: (waardeInBronModus: string) => void
  ariaLabel: string
  disabled?: boolean
  className?: string
  title?: string
  style?: React.CSSProperties
}) {
  const omrekenbaar = percentage !== undefined && modus !== bron
  const toonModus: BedragModus = omrekenbaar ? modus : bron
  const afgeleid = (): string => {
    if (!omrekenbaar) return waarde
    const getal = bedragAlsGetal(waarde)
    return getal === null ? waarde : formatInvoer(rekenOm(getal, bron, modus, percentage))
  }
  const [tekst, setTekst] = useState<string>(afgeleid)
  const [focus, setFocus] = useState(false)
  // FV-08 (feedbackrun A 25-09): de laatst uitgerekende expressie ("20+30") blijft als chip naast het veld staan tot de
  // volgende wijziging — zodat de controleur ziet waar het bedrag vandaan komt.
  const [expressie, setExpressie] = useState<string | null>(null)
  useEffect(() => {
    if (!focus) setTekst(afgeleid())
    // eslint-disable-next-line react-hooks/exhaustive-deps -- alleen hersynchroniseren als de bron/modus verandert
  }, [waarde, modus, percentage, bron, focus])

  const label = toonModus === 'netto' ? 'Netto' : 'Bruto'
  /** FV-08: bij blur/Enter een rekenexpressie ("20+30", "1.250,50*2") deterministisch uitrekenen — eigen parser, geen
   * eval. Het resultaat is een bedrag in de getoonde modus en gaat via de gewone omrekening naar de bron-modus. */
  const rekenUit = () => {
    if (!isExpressie(tekst)) return
    const uitkomst = evalueerBedragExpressie(tekst)
    if (uitkomst === null) return
    const getoond = formatBedragInvoer(uitkomst)
    setExpressie(tekst.trim())
    setTekst(getoond)
    onWijzig(omrekenbaar ? formatInvoer(rekenOm(uitkomst, modus, bron, percentage)) : getoond)
  }
  const tip =
    !omrekenbaar && modus !== bron
      ? `Geen btw-code op deze regel — omrekenen naar ${modus} kan niet, het veld blijft ${bron}`
      : title
  return (
    <>
    <input
      aria-label={`${label} ${ariaLabel}`.trim()}
      inputMode="decimal"
      title={tip ?? 'Bijvoorbeeld 1234,56 — of een berekening zoals 20+30 of 1.250,50*2 (uitgerekend bij het verlaten van het veld)'}
      className={className}
      style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', ...style }}
      value={tekst}
      disabled={disabled}
      onFocus={() => setFocus(true)}
      onBlur={() => {
        rekenUit()
        setFocus(false)
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && isExpressie(tekst)) {
          e.preventDefault()
          rekenUit()
        }
      }}
      onChange={(e) => {
        const nieuw = e.target.value
        setTekst(nieuw)
        setExpressie(null)
        if (isExpressie(nieuw)) return // FV-08: pas uitrekenen bij blur/Enter — tussentijds niets wegschrijven
        if (!omrekenbaar) {
          onWijzig(nieuw)
          return
        }
        const getal = bedragAlsGetal(nieuw)
        if (getal === null) {
          if (nieuw.trim() === '') onWijzig('')
          return
        }
        onWijzig(formatInvoer(rekenOm(getal, modus, bron, percentage)))
      }}
    />
    {expressie !== null && (
      <span
        className="chip stil"
        data-testid="bedrag-expressie-chip"
        title="Uitgerekend uit deze invoer (code, geen AI); wijzig het veld om de berekening los te laten"
        style={{ display: 'inline-block', marginTop: 2, fontVariantNumeric: 'tabular-nums' }}
      >
        = {expressie}
      </span>
    )}
    </>
  )
}
