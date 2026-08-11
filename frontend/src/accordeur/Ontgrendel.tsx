// App-opening: passkey-assertion (Face ID / Touch ID / Android-biometrie / toestel-pincode —
// de OS-fallbacks zitten in WebAuthn zelf) — éénmaal per opening, geldig tot de app sluit
// (besluit Peter 2026-08-11). 401 op de options = sessie verlopen (ná 7 dagen) → volledige
// login; 409 = geen passkey op dit account → volledige login mét registratie.

import { useEffect, useState } from 'react'
import type { TokenPaarResponseDto } from '../api/types'
import {
  haalWebauthnConfig,
  ondertekenAssertie,
  ontgrendelen,
  ontgrendelOpties,
  webauthnBeschikbaar,
} from './webauthnClient'

interface Props {
  naOntgrendeld: (paar: TokenPaarResponseDto) => void
  naarLogin: () => void
}

export function Ontgrendel({ naOntgrendeld, naarLogin }: Props) {
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [gelukt, setGelukt] = useState(false)
  const [devStub, setDevStub] = useState(false)

  useEffect(() => {
    haalWebauthnConfig()
      .then((config) => setDevStub(config.dev_stub))
      .catch(() => setDevStub(false))
  }, [])

  const echteWebauthn = webauthnBeschikbaar()

  const start = async (metStub: boolean) => {
    setFout(null)
    setBezig(true)
    try {
      let paar: TokenPaarResponseDto
      if (metStub) {
        paar = await ontgrendelen({ dev_stub: true })
      } else {
        const opties = await ontgrendelOpties()
        if (opties.status === 401) {
          naarLogin()
          return
        }
        if (opties.status === 409 || opties.opties === null) {
          naarLogin()
          return
        }
        const credential = await ondertekenAssertie(opties.opties)
        paar = await ontgrendelen({ credential })
      }
      setGelukt(true)
      setTimeout(() => naOntgrendeld(paar), 450)
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Ontgrendelen mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div className="acc-vol">
      <div className="acc-appnaam">
        RLZ <span>Goedkeuren</span>
      </div>
      <div className="acc-bio">
        <div className={gelukt ? 'acc-icoon ok' : 'acc-icoon'}>{gelukt ? '✓' : '☉'}</div>
        <b>{gelukt ? 'Ontgrendeld' : 'Ontgrendel de app'}</b>
        <div className="acc-sub">
          Één keer bij het openen van de app — daarna werkt alles direct, ook de akkoord-knop. Sluit je de
          app helemaal, dan ontgrendel je bij de volgende start opnieuw.
        </div>
        {!echteWebauthn && devStub && (
          <span className="acc-stub">
            DEV-STUB — geen echte biometrie (LAN-test zonder https); echte passkeys op https/localhost
          </span>
        )}
      </div>
      {fout && <div className="acc-fout">{fout}</div>}
      {!gelukt && echteWebauthn && (
        <button className="acc-btn groen" disabled={bezig} onClick={() => void start(false)}>
          {bezig ? 'Bezig…' : 'Ontgrendelen'}
        </button>
      )}
      {!gelukt && !echteWebauthn && devStub && (
        <button className="acc-btn groen" disabled={bezig} onClick={() => void start(true)}>
          {bezig ? 'Bezig…' : 'Ontgrendelen (dev-stub)'}
        </button>
      )}
      {!gelukt && !echteWebauthn && !devStub && (
        <div className="acc-fout">
          Passkeys vereisen een beveiligde verbinding (https of localhost). Open de app via https, of vraag
          de beheerder de dev-stub aan te zetten voor een lokale test.
        </div>
      )}
      {!gelukt && (
        <button className="acc-btn secundair" onClick={naarLogin}>
          Opnieuw inloggen
        </button>
      )}
    </div>
  )
}
