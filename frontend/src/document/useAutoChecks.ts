import { useEffect, useRef, useState } from 'react'

/** Automatische harde checks op de boek-schermen (blok B 2026-08-10, opdracht Peter): geen
 * losse "Controleren"-knop meer — checks draaien bij het openen (read-only, over het
 * opgeslagen voorstel of de prefill) en gedebounced bij elke wijziging (opslaan + checks,
 * exact wat de knop deed). De server blijft de harde poort: "Boeken in RLZ" herdraait de
 * checks server-side en blokkeert met een pop-up (ChecksPopup) bij een fout.
 *
 * Boeken sneller (Peter 18-09, stap 1.5): de checks zijn LOKAAL (direct, < 300 ms — opslaan + lokale
 * checks, externe rijen uit de cache) en EXTERN (IBAN-seed, RLZ-/Odoo-duplicaatquery — alleen als de
 * EXTERNE VINGERAFDRUK verandert: crediteur, referentie, factuurdatum, totaal). Omschrijving, grootboek,
 * project of btw-code wijzigen start dus géén externe run meer. `checksBezig` splitst in `lokaalBezig`
 * en `externBezig`; de knop Boeken mag groen zodra alles wat wél moet groen is én de externe uitkomst
 * vers is (het rapport zegt dat zelf: `extern_nog_niet`).
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
  /** Run bij openen — read-only checks, zonder opslaan (lokaal + extern in één; extern uit de cache als geldig). */
  bijOpenen: () => Promise<void>
  /** Run na een wijziging (gedebounced) — opslaan + LOKALE checks (externe rijen uit de cache). */
  bijWijziging: () => Promise<void>
  /** Externe run — alleen als `externeVingerafdruk` sinds de vorige externe run veranderd is. Zonder
   * `bijExtern` gedraagt de hook zich exact als vóór 18-09 (één run per wijziging). */
  bijExtern?: () => Promise<void>
  /** Hash/samenvoeging van de velden die de externe checks raken (crediteur, referentie, datum, totaal). */
  externeVingerafdruk?: string
  debounceMs?: number
}): { checksBezig: boolean; lokaalBezig: boolean; externBezig: boolean } {
  const { actief, wijzigingsVersie, bijOpenen, bijWijziging, bijExtern, externeVingerafdruk } = opties
  const debounceMs = opties.debounceMs ?? 400
  const [lokaalLopend, setLokaalLopend] = useState(0)
  const [externLopend, setExternLopend] = useState(0)
  // De callbacks wisselen elke render van identiteit — via een ref lezen zodat het effect
  // alleen op (actief, wijzigingsVersie) vuurt en niet op elke render opnieuw.
  const callbacks = useRef({ bijOpenen, bijWijziging, bijExtern })
  callbacks.current = { bijOpenen, bijWijziging, bijExtern }
  const vingerafdruk = useRef(externeVingerafdruk)
  vingerafdruk.current = externeVingerafdruk
  const openenGedraaid = useRef(false)
  // De vingerafdruk waarvoor de externe uitkomst het laatst is opgehaald (open-run of externe run).
  const laatsteExterneVingerafdruk = useRef<string | undefined>(undefined)

  useEffect(() => {
    if (!actief) return
    const draai = (run: () => Promise<void>, zet: (f: (n: number) => number) => void) => {
      zet((n) => n + 1)
      return run()
        .catch(() => undefined) // fouten toont het scherm zelf (opslaanFout e.d.)
        .finally(() => zet((n) => n - 1))
    }
    if (wijzigingsVersie === 0) {
      if (!openenGedraaid.current) {
        openenGedraaid.current = true
        laatsteExterneVingerafdruk.current = vingerafdruk.current
        void draai(() => callbacks.current.bijOpenen(), setLokaalLopend)
      }
      return
    }
    const timer = setTimeout(() => {
      void draai(() => callbacks.current.bijWijziging(), setLokaalLopend).then(() => {
        const extern = callbacks.current.bijExtern
        if (!extern) return
        const huidig = vingerafdruk.current
        if (huidig === laatsteExterneVingerafdruk.current) return
        laatsteExterneVingerafdruk.current = huidig
        void draai(extern, setExternLopend)
      })
    }, debounceMs)
    return () => clearTimeout(timer)
  }, [actief, wijzigingsVersie, debounceMs])

  return { checksBezig: lokaalLopend > 0 || externLopend > 0, lokaalBezig: lokaalLopend > 0, externBezig: externLopend > 0 }
}
