// Eerlijke melding als de EERSTE opslag van de toegangscode mislukt (bugfix 10-09 (2), bundel 10-09 blok F —
// zelfde klasse als de wijzig-bugfix van dezelfde ochtend): `stelCodeIn` zegt met false dat de slot-waarde NIET
// aantoonbaar in de opslag staat (schrijffout, terugleescontrole of ontsleutelcontrole mislukt; de oude stand is
// hersteld). Vroeger liep de activatieflow dan gewoon door naar de wachtrij en kende de volgende koude start geen
// slot — de gebruiker stond buiten zonder te weten waarom. Nu: geen doorgang, één leesbare melding, de lokale
// diagnoseregel (koudeStart.diagnoseRegel incl. de laatste slotfout — handeling + sleutelNAAM + reden, nooit een
// waarde) zodat een screenshot naar het kantoor zegt wat faalde, en "Opnieuw proberen" terug naar de code-kiezen-stap.
// Gedeeld door AppActiveren (activatieflow) en AccordeurApp (legacy-toestel zonder slot). Puur lokaal: de code gaat
// nooit naar de server, ook niet in de diagnose.

import { useEffect, useState } from 'react'
import { leesLaatsteSlotfout } from '../../api/slotDiagnose'
import { diagnoseRegel, leesLaatsteKoudeStart, leesLaatsteVerbindingsfout, nativeAppBuild } from '../koudeStart'

export const SLOT_OPSLAG_MISLUKT_MELDING =
  'De toegangscode kon niet veilig op dit toestel worden opgeslagen — probeer het opnieuw. Lukt het niet, neem contact op met het kantoor.'

interface Props {
  /** Terug naar de code-kiezen-stap; de aanroeper hergebruikt zijn activatieresultaat (geen tweede server-activatie). */
  opnieuw: () => void
}

export function SlotOpslagFout({ opnieuw }: Props) {
  const [diagnose, setDiagnose] = useState(() => diagnoseRegel(leesLaatsteKoudeStart(), null, leesLaatsteVerbindingsfout(), leesLaatsteSlotfout()))
  useEffect(() => {
    let actief = true
    void nativeAppBuild().then((build) => {
      if (actief && build) setDiagnose(diagnoseRegel(leesLaatsteKoudeStart(), build, leesLaatsteVerbindingsfout(), leesLaatsteSlotfout()))
    })
    return () => {
      actief = false
    }
  }, [])
  return (
    <div className="acc-vol">
      <div className="acc-appnaam">
        Nijenhuis <span>Boekingsmodule</span>
      </div>
      <div className="acc-bio">
        <div className="acc-icoon">✕</div>
        <b>Toegangscode niet opgeslagen</b>
        <div className="acc-fout" role="alert">
          {SLOT_OPSLAG_MISLUKT_MELDING}
        </div>
        <div className="acc-sub">Stuur een screenshot van de regel hieronder mee als je het kantoor belt — hij bevat geen code.</div>
      </div>
      <code className="acc-diag" data-testid="acc-diagnose">
        {diagnose}
      </code>
      <button className="acc-btn primair" onClick={opnieuw}>
        Opnieuw proberen
      </button>
    </div>
  )
}
