import { useEffect, useRef, useState, type ReactNode } from 'react'
import { AnkerPopup } from '../ui/basis/AnkerPopup'

/** Actiekolom van de gebruikers-tabellen volgens de UX-norm "één primaire knop + ⋯" (BESLISSINGEN
 * "UX-PATRONEN ALS NORM"; blok 2 vervolgrun 10-09 avond, kliktest Peter): hooguit één zichtbare knop
 * per rij (Opnieuw mailen / Herstel-link), álle overige handelingen (E-mail wijzigen, Scope wijzigen,
 * Blokkeren/Heractiveren, Archiveren/Dearchiveren) achter het bestaande ⋯-rijmenu — `icon-btn` +
 * `AnkerPopup className="rijmenu" role="menu"` zoals in ArchiefScreen/DocumentenDeelscherm (portal,
 * dus nooit afgekapt door `.tabel-scroll`). Geen tweede menu-component: dit is de per-rij-wrapper
 * (eigen open-stand + anker-ref) die die twee bouwstenen samenbrengt, plus sluiten op Escape en op
 * een klik buiten menu en knop. */

export interface RijMenuItem {
  label: string
  onClick: () => void
  /** Gevaar-actie (blokkeren): rode tekst in het menu. */
  gevaar?: boolean
  disabled?: boolean
}

export function GebruikerRijMenu({
  naam,
  primair,
  items,
}: {
  /** Voor het toegankelijke label van de ⋯-knop: "Meer acties voor ‹naam›". */
  naam: string
  /** De ene zichtbare knop (of null). */
  primair?: ReactNode
  /** Menu-items; leeg = geen ⋯-knop (bv. de eigen rij zonder toegestane handelingen). */
  items: RijMenuItem[]
}) {
  const [open, setOpen] = useState(false)
  const knop = useRef<HTMLButtonElement | null>(null)
  const menu = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const opToets = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    const opKlik = (e: MouseEvent) => {
      const doel = e.target as Node
      if (knop.current?.contains(doel) || menu.current?.contains(doel)) return
      setOpen(false)
    }
    window.addEventListener('keydown', opToets)
    window.addEventListener('mousedown', opKlik)
    return () => {
      window.removeEventListener('keydown', opToets)
      window.removeEventListener('mousedown', opKlik)
    }
  }, [open])

  return (
    <div className="rij-acties">
      {primair}
      {items.length > 0 && (
        <>
          <button
            ref={knop}
            type="button"
            className="linkbtn rij-meer"
            aria-label={`Meer acties voor ${naam}`}
            aria-haspopup="menu"
            aria-expanded={open}
            onClick={(e) => {
              e.stopPropagation()
              setOpen((h) => !h)
            }}
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
            aria-label={`Acties voor ${naam}`}
            onAnkerUitBeeld={() => setOpen(false)}
            onClick={(e) => e.stopPropagation()}
          >
            <div ref={menu}>
              {items.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  className="linkbtn"
                  role="menuitem"
                  disabled={item.disabled}
                  style={item.gevaar ? { color: 'var(--danger)' } : undefined}
                  onClick={() => {
                    setOpen(false)
                    item.onClick()
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </AnkerPopup>
        </>
      )}
    </div>
  )
}
