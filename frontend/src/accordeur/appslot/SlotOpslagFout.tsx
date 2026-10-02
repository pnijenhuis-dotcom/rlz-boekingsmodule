// Eerlijke melding als de EERSTE opslag van de toegangscode mislukt (bugfix 10-09 (2), bundel 10-09 blok F —
// zelfde klasse als de wijzig-bugfix van dezelfde ochtend): `stelCodeIn` zegt met false dat de slot-waarde NIET
// aantoonbaar in de opslag staat (schrijffout, terugleescontrole of ontsleutelcontrole mislukt; de oude stand is
// hersteld). Vroeger liep de activatieflow dan gewoon door naar de wachtrij en kende de volgende koude start geen
// slot — de gebruiker stond buiten zonder te weten waarom. Nu: geen doorgang, één leesbare melding, de lokale
// diagnoseregel (koudeStart.diagnoseRegel incl. de laatste slotfout — handeling + sleutelNAAM + reden, nooit een
// waarde) zodat een screenshot naar het kantoor zegt wat faalde, en "Opnieuw proberen" terug naar de code-kiezen-stap.
// Gedeeld door AppActiveren (activatieflow) en AccordeurApp (legacy-toestel zonder slot). Puur lokaal: de code gaat
// nooit naar de server, ook niet in de diagnose.
//
// Native 1.3 / vc7 (run D 02-10, bug Peter 02-10 foto IMG_2512 "Opslag-verwijderfout: null"): is de laatste slotfout een
// fout van de KLUIS zelf (plugin-reject `Opslag-…fout`/`Keychain-…fout`) én draagt de schil `herstel` (≥ 1.3), dan is
// "neem contact op met het kantoor" het verkeerde advies — de kluis past niet meer bij de Keystore-sleutel en alleen
// opnieuw aanmaken helpt. Dan: kop "App-opslag opnieuw instellen" + knop die `herstelOpslag()` aanroept en daarna de
// activatieflow vervolgt (`opnieuw` = code kiezen op hetzelfde activatieresultaat; in AccordeurApp PincodeKiezen).
// Afwezig-pad (web-adapter, schil < 1.3, of een controle-fout zonder plugin-fout): de melding van 10-09 ongewijzigd.

import { useEffect, useState } from 'react'
import { herstelOpslag, kanOpslagHerstellen } from '../../api/appSlot'
import { isKluisOpslagFout, leesLaatsteSlotfout } from '../../api/slotDiagnose'
import { schrijfAppSlotAudit } from '../appAuthApi'
import { diagnoseRegel, leesLaatsteKoudeStart, leesLaatsteVerbindingsfout, nativeAppBuild } from '../koudeStart'

export const SLOT_OPSLAG_MISLUKT_MELDING =
  'De toegangscode kon niet veilig op dit toestel worden opgeslagen — probeer het opnieuw. Lukt het niet, neem contact op met het kantoor.'

export const APP_OPSLAG_HERSTEL_KOP = 'App-opslag opnieuw instellen'
export const APP_OPSLAG_HERSTEL_MELDING =
  'De beveiligde opslag van de app op dit toestel is onleesbaar geworden (bijvoorbeeld na een back-up, overdracht of systeemupdate). ' +
  'Stel de app-opslag opnieuw in: de app wist de onleesbare opslag en je kiest daarna opnieuw je toegangscode. Je facturen en je toegang blijven bij het kantoor bewaard.'
export const APP_OPSLAG_HERSTEL_MISLUKT_MELDING =
  'Het opnieuw instellen van de app-opslag is niet gelukt. Probeer het nog een keer; lukt het dan niet, neem contact op met het kantoor en stuur de regel hieronder mee.'

interface Props {
  /** Terug naar de code-kiezen-stap; de aanroeper hergebruikt zijn activatieresultaat (geen tweede server-activatie). */
  opnieuw: () => void
}

export function SlotOpslagFout({ opnieuw }: Props) {
  const [diagnose, setDiagnose] = useState(() => diagnoseRegel(leesLaatsteKoudeStart(), null, leesLaatsteVerbindingsfout(), leesLaatsteSlotfout()))
  const [herstelbaar] = useState(() => kanOpslagHerstellen() && isKluisOpslagFout(leesLaatsteSlotfout()))
  const [herstelStand, setHerstelStand] = useState<'idle' | 'bezig' | 'mislukt'>('idle')
  useEffect(() => {
    let actief = true
    void nativeAppBuild().then((build) => {
      if (actief && build) setDiagnose(diagnoseRegel(leesLaatsteKoudeStart(), build, leesLaatsteVerbindingsfout(), leesLaatsteSlotfout()))
    })
    return () => {
      actief = false
    }
  }, [])

  const herstel = async () => {
    setHerstelStand('bezig')
    const uitkomst = await herstelOpslag()
    if (uitkomst === 'hersteld') {
      schrijfAppSlotAudit('app_opslag_hersteld')
      opnieuw()
      return
    }
    setDiagnose(diagnoseRegel(leesLaatsteKoudeStart(), null, leesLaatsteVerbindingsfout(), leesLaatsteSlotfout()))
    setHerstelStand('mislukt')
  }

  if (herstelbaar) {
    return (
      <div className="acc-vol">
        <div className="acc-appnaam">
          Nijenhuis <span>Boekingsmodule</span>
        </div>
        <div className="acc-bio">
          <div className="acc-icoon">✕</div>
          <b>{APP_OPSLAG_HERSTEL_KOP}</b>
          <div className="acc-fout" role="alert">
            {herstelStand === 'mislukt' ? APP_OPSLAG_HERSTEL_MISLUKT_MELDING : APP_OPSLAG_HERSTEL_MELDING}
          </div>
          <div className="acc-sub">De regel hieronder bevat geen code; stuur hem mee als je het kantoor belt.</div>
        </div>
        <code className="acc-diag" data-testid="acc-diagnose">
          {diagnose}
        </code>
        <button className="acc-btn primair" onClick={() => void herstel()} disabled={herstelStand === 'bezig'}>
          {herstelStand === 'bezig' ? 'Bezig…' : 'App-opslag opnieuw instellen'}
        </button>
        <button type="button" className="acc-btn secundair" onClick={opnieuw} disabled={herstelStand === 'bezig'}>
          Opnieuw proberen zonder wissen
        </button>
      </div>
    )
  }

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
