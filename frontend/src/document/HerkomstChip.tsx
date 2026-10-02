/** Rustig controlescherm (punt 2, Peter 02-10): de herkomst-chips van een blok (crediteur / kopgegevens /
 * boekingsregels) staan achter één `linkbtn` "Herkomst tonen" per blok; een AFWIJKING blijft altijd zichtbaar.
 * Beslislogica: `herkomstZichtbaarheid.ts` (puur). Buiten een `HerkomstBlokProvider` (default `true`) gedraagt
 * `HerkomstChip` zich als de kale `<span className="chip …">` van vóór 02-10 — niets wordt weggegooid, alleen verborgen. */

import { createContext, useContext, type CSSProperties, type ReactNode } from 'react'
import { chipZichtbaar, type HerkomstBlok } from './herkomstZichtbaarheid'

const HerkomstContext = createContext<boolean>(true)

export function HerkomstBlokProvider({ tonen, children }: { tonen: boolean; children: ReactNode }) {
  return <HerkomstContext.Provider value={tonen}>{children}</HerkomstContext.Provider>
}

/** Staat het omringende blok op "Herkomst tonen"? (voor losse tekstregels die geen chip zijn maar wél herkomst) */
export function useHerkomstTonen(): boolean {
  return useContext(HerkomstContext)
}

interface HerkomstChipProps {
  /** Klasse(n) naast `chip`: 'ok' | 'afwijking' | 'handmatig' | 'geheugen' | 'stil' | 'blokkerend' | 'vraag' | ''. */
  klasse: string
  /** Inhoudelijke afwijking ondanks een rustige klasse (aanname-periode, btw in kosten, samenvoegen niet mogelijk). */
  altijdTonen?: boolean
  /** Omhulling die mét de chip verdwijnt: 'div' = `<div style={{marginTop:4}}>`, 'regel' = `<div className="regel-herkomst">`. */
  omhulling?: 'div' | 'regel' | 'regel-rechts'
  title?: string
  style?: CSSProperties
  'data-testid'?: string
  'data-bron'?: string
  children: ReactNode
}

export function HerkomstChip({ klasse, altijdTonen = false, omhulling, title, style, children, ...rest }: HerkomstChipProps) {
  const tonen = useContext(HerkomstContext)
  if (!chipZichtbaar(klasse, tonen, altijdTonen)) return null
  const span = (
    <span className={`chip ${klasse}`.trim()} title={title} style={style} {...rest}>
      {children}
    </span>
  )
  if (omhulling === 'div') return <div style={{ marginTop: 4 }}>{span}</div>
  if (omhulling === 'regel') return <div className="regel-herkomst">{span}</div>
  if (omhulling === 'regel-rechts')
    return (
      <div className="regel-herkomst" style={{ textAlign: 'right' }}>
        {span}
      </div>
    )
  return span
}

/** Blok-kop mét de `linkbtn` "Herkomst tonen" / "Herkomst verbergen" (één per blok, niet in de alleen-lezen stand). */
export function HerkomstBlokKop({
  titel,
  blok,
  tonen,
  onWissel,
  verborgen = false,
}: {
  titel: string
  blok: HerkomstBlok
  tonen: boolean
  onWissel: (blok: HerkomstBlok, aan: boolean) => void
  verborgen?: boolean
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
      <h2 style={{ marginRight: 'auto' }}>{titel}</h2>
      {!verborgen && (
        <button
          type="button"
          className="linkbtn"
          data-testid={`herkomst-tonen-${blok}`}
          aria-pressed={tonen}
          title="Toont of verbergt de herkomst van de automatisch ingevulde velden in dit blok (AI-zekerheid, geheugen, factuur, template). Een afwijking blijft altijd zichtbaar."
          onClick={() => onWissel(blok, !tonen)}
        >
          {tonen ? 'Herkomst verbergen' : 'Herkomst tonen'}
        </button>
      )}
    </div>
  )
}
