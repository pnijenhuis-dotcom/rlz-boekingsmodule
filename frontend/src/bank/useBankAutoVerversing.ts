import { useCallback, useEffect, useRef, useState } from 'react'
import { haalBankSyncAchtergrondStatus, startBankSyncAchtergrond, type BankSyncRunDto } from './bankApi'

/** Poll-cadans op de status-route zolang de achtergrondronde loopt. */
export const POLL_INTERVAL_MS = 2500

export interface BankAutoVerversingStaat {
  /** Laatst bekende run-status (null tot de POST heeft geantwoord). */
  run: BankSyncRunDto | null
  /** true = de achtergrondronde loopt nog (wachtrij/bezig) en we pollen. */
  bezig: boolean
  /** Netwerk-/API-fout bij het starten of pollen — zichtbaar, nooit stil. */
  fout: string | null
  /** Blok E2 (01/02-09): het ⟳-icoon — zelfde endpoint, mét `forceer` (slaat de 5-min-drempel over);
   * de verificatie van wachtende afletteropdrachten lift in élke ronde mee (blok E3). */
  herstart: () => void
}

function isLopend(run: BankSyncRunDto): boolean {
  return run.status === 'wachtrij' || run.status === 'bezig'
}

/** Auto-verversing bij het openen van het bankscherm (besluit Peter 25-08, deel 4 punt 2):
 * éénmaal per administratie (niet per rekening-wissel) een achtergrond-sync aanvragen; de cache
 * blijft direct zichtbaar. `overgeslagen` = actueel (laatste sync < drempel), `wachtrij`/`bezig`
 * → pollen tot klaar/fout/geen; bij `klaar` vuurt `onKlaar` precies één keer (de aanroeper
 * herlaadt dan rekeningen + mutaties). Unmount-guard: timers en late antwoorden worden genegeerd
 * zodra het scherm weg is of de administratie wisselt. */
export function useBankAutoVerversing(
  administratieId: string | undefined,
  onKlaar: (run: BankSyncRunDto) => void,
): BankAutoVerversingStaat {
  const [run, setRun] = useState<BankSyncRunDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  // Callback in een ref: een nieuwe closure per render mag de lopende ronde niet herstarten.
  const onKlaarRef = useRef(onKlaar)
  onKlaarRef.current = onKlaar

  // Eén lopende "ronde-context" per administratie: de effect-start én de handmatige herstart delen
  // dezelfde unmount-/wissel-guard via deze ref (late antwoorden van een vorige context worden genegeerd).
  const contextRef = useRef<{ administratieId: string; actief: boolean; timer: ReturnType<typeof setTimeout> | null } | null>(null)

  const startRonde = useCallback((administratieIdVoor: string, forceer: boolean) => {
    const context = contextRef.current
    if (!context || context.administratieId !== administratieIdVoor) return
    setFout(null)
    const verwerk = (nieuw: BankSyncRunDto) => {
      if (!context.actief) return
      setRun(nieuw)
      if (isLopend(nieuw)) {
        setBezig(true)
        context.timer = setTimeout(() => void poll(), POLL_INTERVAL_MS)
        return
      }
      setBezig(false)
      if (nieuw.status === 'klaar') onKlaarRef.current(nieuw)
    }
    const meldFout = (err: unknown) => {
      if (!context.actief) return
      setBezig(false)
      setFout(err instanceof Error ? err.message : 'Verversen uit Reeleezee mislukt')
    }
    const poll = async () => {
      if (!context.actief) return
      try {
        verwerk(await haalBankSyncAchtergrondStatus(administratieIdVoor))
      } catch (err) {
        meldFout(err)
      }
    }
    startBankSyncAchtergrond(administratieIdVoor, forceer).then(verwerk).catch(meldFout)
  }, [])

  useEffect(() => {
    if (!administratieId) return
    const context = { administratieId, actief: true, timer: null as ReturnType<typeof setTimeout> | null }
    contextRef.current = context
    setRun(null)
    setFout(null)
    setBezig(false)
    startRonde(administratieId, false)
    return () => {
      context.actief = false
      if (context.timer) clearTimeout(context.timer)
      if (contextRef.current === context) contextRef.current = null
    }
  }, [administratieId, startRonde])

  const herstart = useCallback(() => {
    const context = contextRef.current
    if (!administratieId || !context) return
    startRonde(administratieId, true)
  }, [administratieId, startRonde])

  return { run, bezig, fout, herstart }
}
