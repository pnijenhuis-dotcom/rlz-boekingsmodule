import type { ReactNode } from 'react'

/** Uniforme foutweergave (browserreview 2026-08-07 punt 4): mensentaal + handelingsperspectief
 * vooraan, een "Opnieuw proberen"-knop waar herladen zinvol is, en het technische detail achter
 * een uitklap — nooit een rauwe parser-/statusstring als enige tekst in beeld. */
export function FoutMelding({
  melding,
  detail,
  onOpnieuw,
  children,
}: {
  /** De boodschap in mensentaal, inclusief wat de gebruiker kan doen. */
  melding: string
  /** Technisch detail (API-foutstring, status) — alleen zichtbaar na uitklappen. */
  detail?: string | null
  /** Aanwezig = er verschijnt een "Opnieuw proberen"-knop. */
  onOpnieuw?: () => void
  children?: ReactNode
}) {
  return (
    <div className="fout" role="alert">
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <span>{melding}</span>
        {onOpnieuw && (
          <button type="button" className="btn secondary" style={{ padding: '4px 12px' }} onClick={onOpnieuw}>
            Opnieuw proberen
          </button>
        )}
        {children}
      </div>
      {detail && detail !== melding && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12 }}>Technische details</summary>
          <code style={{ fontSize: 12, wordBreak: 'break-word' }}>{detail}</code>
        </details>
      )}
    </div>
  )
}
