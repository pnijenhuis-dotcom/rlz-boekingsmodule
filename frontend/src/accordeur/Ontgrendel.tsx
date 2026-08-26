// App-opening: passkey-assertion (Face ID / Touch ID / Android-biometrie / toestel-pincode —
// de OS-fallbacks zitten in WebAuthn zelf) — éénmaal per opening, geldig tot de app sluit
// (besluit Peter 2026-08-11). 401 op de options = sessie verlopen (ná 7 dagen) → volledige
// login; 409 = geen passkey op dit account → volledige login mét registratie.

import { useEffect, useRef, useState } from 'react'
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

  const start = async (metStub: boolean, opts?: { stil?: boolean }) => {
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
      // Een weggedrukte/gefaalde AUTO-prompt is geen fout van de gebruiker — geen rode
      // melding, de knop staat klaar als herkansing. Een mislukte knop-poging meldt wél.
      if (!opts?.stil) {
        setFout(err instanceof Error ? err.message : 'Ontgrendelen mislukt — probeer het opnieuw.')
      }
    } finally {
      setBezig(false)
    }
  }

  // Klik-klik-principe (besluit Peter 2026-08-17): de passkey-assertion start automatisch
  // zodra het ontgrendelscherm verschijnt — openen → Face ID → binnen, nul onnodige tikken.
  // Eén auto-poging per app-opening (ref overleeft óók StrictMode-double-effects — geen
  // dubbele Face ID-prompt in dev); de dev-stub doet mee voor flow-pariteit in kliktests.
  // Weigert het platform een assertion zonder gebruikersgebaar (ouder iOS-Safari), dan faalt
  // de auto-poging stil en is de knop het gewone pad — 401/409 routeren ook automatisch
  // gewoon naar het login-scherm, identiek aan de knop.
  const autoGestart = useRef(false)
  useEffect(() => {
    if (autoGestart.current) return
    if (echteWebauthn) {
      autoGestart.current = true
      void start(false, { stil: true })
    } else if (devStub) {
      autoGestart.current = true
      void start(true, { stil: true })
    }
  }, [echteWebauthn, devStub])

  return (
    <div className="acc-vol">
      <div className="acc-appnaam">
        Nijenhuis <span>Boekingsmodule</span>
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
        <button className="acc-btn primair" disabled={bezig} onClick={() => void start(false)}>
          {bezig ? 'Bezig…' : 'Ontgrendelen'}
        </button>
      )}
      {!gelukt && !echteWebauthn && devStub && (
        <button className="acc-btn primair" disabled={bezig} onClick={() => void start(true)}>
          {bezig ? 'Bezig…' : 'Ontgrendelen (dev-stub)'}
        </button>
      )}
      {!gelukt && !echteWebauthn && !devStub && (
        <div className="acc-fout">
          Passkeys vereisen een beveiligde verbinding (https of localhost). Open de app via https, of vraag
          de beheerder de dev-stub aan te zetten voor een lokale test.
        </div>
      )}
      {/* Nooduitgang (passkey kwijt/geweigerd, ander account, kill-switch) — bewust een subtiele
          tekstlink, geen tweede knop: "Ontgrendelen" is de enige primaire actie (Peter 14-08). */}
      {!gelukt && (
        <button className="acc-tekstlink" onClick={naarLogin}>
          Opnieuw inloggen
        </button>
      )}
    </div>
  )
}
