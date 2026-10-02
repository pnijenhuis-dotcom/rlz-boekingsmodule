// ⋯-menu voor de verkoop- en omzet-reviewschermen (run D 02-10 blok C). Tot 02-10 droeg dat menu uitsluitend
// "Corrigeren…" (geboekt document); sinds blok C staat er óók "Afwijzen…" op een afwijsbaar document — dezelfde
// dialoog (verplichte reden) en dezelfde route als het inkoop-controlescherm en de bulkbalk. Eén primaire knop + ⋯
// (UX-norm 02-09); een tekstknop in het menu = linkbtn (norm 03-09).
import { useRef, useState } from 'react'
import { AnkerPopup } from '../ui/basis'

export interface ReviewActie {
  sleutel: string
  label: string
  onKies: () => void
  disabled?: boolean
}

export function ReviewActiesMenu({ acties, label = 'Meer acties' }: { acties: ReviewActie[]; label?: string }) {
  const knop = useRef<HTMLButtonElement | null>(null)
  const [open, setOpen] = useState(false)
  if (acties.length === 0) return null
  return (
    <>
      <button
        ref={knop}
        type="button"
        className="icon-btn"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        ⋯
      </button>
      <AnkerPopup
        open={open}
        anker={knop}
        kant="onder"
        uitlijning="eind"
        className="rijmenu"
        role="menu"
        aria-label={label}
        onAnkerUitBeeld={() => setOpen(false)}
      >
        {acties.map((actie) => (
          <button
            key={actie.sleutel}
            type="button"
            className="linkbtn"
            role="menuitem"
            disabled={actie.disabled}
            aria-disabled={actie.disabled}
            onClick={() => {
              setOpen(false)
              actie.onKies()
            }}
          >
            {actie.label}
          </button>
        ))}
      </AnkerPopup>
    </>
  )
}
