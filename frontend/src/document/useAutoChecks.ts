import { useEffect, useRef, useState } from 'react'

/** Automatische harde checks op de boek-schermen (blok B 2026-08-10, opdracht Peter): geen
 * losse "Controleren"-knop meer — checks draaien bij het openen (read-only, over het
 * opgeslagen voorstel of de prefill) en gedebounced bij elke wijziging (opslaan + checks,
 * exact wat de knop deed). De server blijft de harde poort: "Boeken in RLZ" herdraait de
 * checks server-side en blokkeert met een pop-up (ChecksPopup) bij een fout.
 *
 * `wijzigingsVersie` begint op 0 (= openen) en wordt door het scherm bij elke relevante
 * invoerwijziging opgehoogd. Een verse wijziging tijdens een lopende run plant gewoon een
 * nieuwe run — het scherm beschermt zichzelf tegen verouderde resultaten door de resultaten
 * pas te tonen als de laatste run klaar is (checksBezig). */
export function useAutoChecks(opties: {
  /** Pas draaien als het scherm er klaar voor is (data geladen, niet read-only/geboekt). */
  actief: boolean
  /** 0 = initieel; elke invoerwijziging verhoogt dit. */
  wijzigingsVersie: number
  /** Run bij openen — read-only checks, zonder opslaan. */
  bijOpenen: () => Promise<void>
  /** Run na een wijziging (gedebounced) — opslaan + checks. */
  bijWijziging: () => Promise<void>
  debounceMs?: number
}): { checksBezig: boolean } {
  const { actief, wijzigingsVersie, bijOpenen, bijWijziging } = opties
  const debounceMs = opties.debounceMs ?? 800
  const [lopende, setLopende] = useState(0)
  // De callbacks wisselen elke render van identiteit — via een ref lezen zodat het effect
  // alleen op (actief, wijzigingsVersie) vuurt en niet op elke render opnieuw.
  const callbacks = useRef({ bijOpenen, bijWijziging })
  callbacks.current = { bijOpenen, bijWijziging }
  const openenGedraaid = useRef(false)

  useEffect(() => {
    if (!actief) return
    const draai = (run: () => Promise<void>) => {
      setLopende((n) => n + 1)
      void run()
        .catch(() => undefined) // fouten toont het scherm zelf (opslaanFout e.d.)
        .finally(() => setLopende((n) => n - 1))
    }
    if (wijzigingsVersie === 0) {
      if (!openenGedraaid.current) {
        openenGedraaid.current = true
        draai(() => callbacks.current.bijOpenen())
      }
      return
    }
    const timer = setTimeout(() => draai(() => callbacks.current.bijWijziging()), debounceMs)
    return () => clearTimeout(timer)
  }, [actief, wijzigingsVersie, debounceMs])

  return { checksBezig: lopende > 0 }
}
