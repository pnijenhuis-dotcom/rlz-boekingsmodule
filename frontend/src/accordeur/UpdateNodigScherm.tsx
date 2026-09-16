// "Update nodig" (OTA blok C, 16-09): de server gaf 426 — deze schil zit onder de minimumversie. Eén scherm mét winkelknop
// (iOS: App Store-link; Android: Google In-App Update IMMEDIATE als de plugin er is, anders de Play-link). Geen kale fout,
// geen wachtwoordvraag; de web-laag kan dit niet oplossen (native update), dus de knop is de enige weg.
import { useEffect, useState } from 'react'
import type { AppUpdateNodigDetail } from '../api/client'
import { APP_MARKETING_VERSIE } from './appVersie'
import { huidigPlatform } from './appAuthApi'
import { androidInAppUpdate } from './ota'

export function UpdateNodigScherm({ detail }: { detail: AppUpdateNodigDetail }) {
  const platform = huidigPlatform()
  const [inApp, setInApp] = useState<'bezig' | 'gestart' | 'geen' | null>(null)

  useEffect(() => {
    if (platform !== 'android') return
    setInApp('bezig')
    void androidInAppUpdate('immediate').then((r) => setInApp(r === 'gestart' ? 'gestart' : 'geen'))
  }, [platform])

  const winkel = detail.store_url ?? null
  return (
    <div className="acc-vol" role="alert">
      <div className="acc-appnaam">
        Nijenhuis <span>Boekingsmodule</span>
      </div>
      <div className="acc-bio">
        <div className="acc-icoon">⬆</div>
        <b>Update nodig</b>
        <div className="acc-sub">
          Deze versie van de app ({detail.huidige_versie ?? APP_MARKETING_VERSIE}) wordt niet meer ondersteund
          {detail.min_versie ? ` — minimaal versie ${detail.min_versie}` : ''}. Werk de app bij in de {platform === 'android' ? 'Play Store' : 'App Store'} en
          open &lsquo;m opnieuw.
        </div>
        {inApp === 'gestart' && <div className="acc-sub">De update is gestart via Google Play…</div>}
        {winkel ? (
          <a className="acc-knop" href={winkel} target="_blank" rel="noreferrer">
            {platform === 'android' ? 'Naar de Play Store' : 'Naar de App Store'}
          </a>
        ) : (
          <div className="acc-sub">Open de {platform === 'android' ? 'Play Store' : 'App Store'} op dit toestel en zoek &ldquo;Nijenhuis Boekingsmodule&rdquo;.</div>
        )}
      </div>
    </div>
  )
}
