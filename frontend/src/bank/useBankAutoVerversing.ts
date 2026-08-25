import { useEffect, useRef, useState } from 'react'
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

  useEffect(() => {
    if (!administratieId) return
    let actief = true
    let timer: ReturnType<typeof setTimeout> | null = null
    setRun(null)
    setFout(null)
    setBezig(false)

    const verwerk = (nieuw: BankSyncRunDto) => {
      if (!actief) return
      setRun(nieuw)
      if (isLopend(nieuw)) {
        setBezig(true)
        timer = setTimeout(() => void poll(), POLL_INTERVAL_MS)
        return
      }
      setBezig(false)
      if (nieuw.status === 'klaar') onKlaarRef.current(nieuw)
    }

    const meldFout = (err: unknown) => {
      if (!actief) return
      setBezig(false)
      setFout(err instanceof Error ? err.message : 'Verversen uit Reeleezee mislukt')
    }

    const poll = async () => {
      if (!actief) return
      try {
        verwerk(await haalBankSyncAchtergrondStatus(administratieId))
      } catch (err) {
        meldFout(err)
      }
    }

    startBankSyncAchtergrond(administratieId).then(verwerk).catch(meldFout)

    return () => {
      actief = false
      if (timer) clearTimeout(timer)
    }
  }, [administratieId])

  return { run, bezig, fout }
}
