import * as React from 'react'
import { cn } from './cn'

/* Toast — mockup/kantoor-modern.html .toasts/.toast: korte bevestiging rechtsonder, verdwijnt
 * vanzelf. Voor blijvende fouten blijft FoutMelding het patroon — een toast is nooit het enige
 * spoor van iets dat misging (kernprincipe "niets verdwijnt stil"). */
export type ToastSoort = 'ok' | 'warn'

interface ToastItem {
  id: number
  tekst: string
  soort: ToastSoort
}

interface ToastContextWaarde {
  meld: (tekst: string, soort?: ToastSoort) => void
}

const ToastContext = React.createContext<ToastContextWaarde | null>(null)

export function useToast(): ToastContextWaarde {
  const ctx = React.useContext(ToastContext)
  if (!ctx) throw new Error('useToast vereist een <ToastProvider> (Shell/App-niveau)')
  return ctx
}

const TOON_MS = 3600

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = React.useState<ToastItem[]>([])
  const volgende = React.useRef(1)

  const meld = React.useCallback((tekst: string, soort: ToastSoort = 'ok') => {
    const id = volgende.current++
    setItems((huidig) => [...huidig, { id, tekst, soort }])
    setTimeout(() => setItems((huidig) => huidig.filter((t) => t.id !== id)), TOON_MS)
  }, [])

  const waarde = React.useMemo(() => ({ meld }), [meld])

  return (
    <ToastContext.Provider value={waarde}>
      {children}
      <div className="fixed right-[22px] bottom-[22px] z-80 flex flex-col gap-2" role="status" aria-live="polite">
        {items.map((t) => (
          <div
            key={t.id}
            className={cn(
              'flex items-center gap-[9px] rounded-[10px] border border-border border-l-[3px] bg-panel px-4 py-[11px] text-[12.5px] text-text shadow-zweef',
              t.soort === 'warn' ? 'border-l-warn' : 'border-l-ok',
            )}
          >
            {t.tekst}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
