import { useState } from 'react'
import { conflictenUniek, type Conflict } from './dagEerst'

/* Conflictenbalk boven het grid (mockup v3 ①, notitie "Conflictenbalk"): dubbel gepland op één dag, afwezig, > 5 op één
 * kaart (besluit C), ZZP'er zonder dossier — élk item klikbaar → springt naar de kaart en licht die op. Nooit blokkerend:
 * kantoor beslist. Oranje = conflict/afwijking (designpass v2). */
export function ConflictenBalk({ conflicten, onSpring }: { conflicten: Conflict[]; onSpring: (sleutel: string) => void }) {
  const [open, setOpen] = useState(false)
  const uniek = conflictenUniek(conflicten)
  if (uniek.length === 0) return null
  const getoond = open ? uniek : uniek.slice(0, 3)
  return (
    <div className="plan-conf" role="status" data-testid="conflictenbalk">
      <b>
        {uniek.length} {uniek.length === 1 ? 'conflict' : 'conflicten'} deze week
      </b>
      {getoond.map((c, i) => (
        <button
          key={`${c.soort}-${c.gebruiker_id ?? ''}-${c.datum}-${c.project_id}-${i}`}
          type="button"
          className="linkbtn"
          style={{ fontSize: 12.5 }}
          title="Toon in grid"
          onClick={() => onSpring(`${c.project_id}|${c.datum}`)}
        >
          {c.tekst}
        </button>
      ))}
      {uniek.length > 3 && (
        <button type="button" className="linkbtn" style={{ fontSize: 12.5, marginLeft: 'auto' }} onClick={() => setOpen((o) => !o)}>
          {open ? 'minder' : `+ ${uniek.length - 3} meer`}
        </button>
      )}
      <span className="hint" style={{ margin: 0, fontSize: 11 }}>nooit blokkerend — kantoor beslist</span>
    </div>
  )
}
