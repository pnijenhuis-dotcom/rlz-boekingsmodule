// Activeringsflow accordeur, stap 2 (blok 3): ná het wachtwoord (gezet in het gedeelde
// /activeren-scherm) registreert dit scherm de passkey van dít apparaat en logt meteen in.
// De voorwaarden + privacyverklaring volgen direct hierna (GoedkeurenFlow toont het
// akkoord-scherm zolang de server de wachtrij weigert — fail-closed).

import { useEffect, useState } from 'react'
import type { TokenPaarResponseDto } from '../api/types'
import {
  apparaatNaam,
  haalWebauthnConfig,
  registratieOpties,
  registratieVoltooien,
  registreerPasskey,
  webauthnBeschikbaar,
} from './webauthnClient'

interface Props {
  passkeySetupToken: string
  naIngelogd: (paar: TokenPaarResponseDto) => void
}

export function AccordeurActiveren({ passkeySetupToken, naIngelogd }: Props) {
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [devStub, setDevStub] = useState(false)

  useEffect(() => {
    haalWebauthnConfig()
      .then((config) => setDevStub(config.dev_stub))
      .catch(() => setDevStub(false))
  }, [])

  const echteWebauthn = webauthnBeschikbaar()

  const registreer = async (metStub: boolean) => {
    setFout(null)
    setBezig(true)
    try {
      let paar: TokenPaarResponseDto
      if (metStub) {
        paar = await registratieVoltooien(passkeySetupToken, {
          dev_stub: true,
          apparaat_naam: `${apparaatNaam()} (dev-stub)`,
        })
      } else {
        const opties = await registratieOpties(passkeySetupToken)
        paar = await registratieVoltooien(passkeySetupToken, {
          credential: await registreerPasskey(opties),
          apparaat_naam: apparaatNaam(),
        })
      }
      naIngelogd(paar)
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Registreren mislukt.')
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
        <div className="acc-icoon">☉</div>
        <b>Dit apparaat registreren</b>
        <div className="acc-sub">
          Je wachtwoord staat. Registreer nu dit apparaat met een passkey (Face ID, Touch ID,
          vingerafdruk of de toegangscode van je toestel) — daarna log je hier vanzelf mee in.
        </div>
        {!echteWebauthn && devStub && (
          <span className="acc-stub">DEV-STUB actief — geen echte biometrie (LAN-test zonder https)</span>
        )}
      </div>
      {fout && <div className="acc-fout">{fout}</div>}
      {echteWebauthn && (
        <button className="acc-btn groen" disabled={bezig} onClick={() => void registreer(false)}>
          {bezig ? 'Bezig…' : 'Passkey aanmaken'}
        </button>
      )}
      {!echteWebauthn && devStub && (
        <button className="acc-btn groen" disabled={bezig} onClick={() => void registreer(true)}>
          {bezig ? 'Bezig…' : 'Registreren (dev-stub)'}
        </button>
      )}
      {!echteWebauthn && !devStub && (
        <div className="acc-fout">
          Passkeys vereisen een beveiligde verbinding (https of localhost). Open de activatielink via https,
          of vraag de beheerder de dev-stub aan te zetten voor een lokale test.
        </div>
      )}
    </div>
  )
}
