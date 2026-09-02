// Volledige login (eerste gebruik / nieuw apparaat / ná 7 dagen inactiviteit — besluit
// 2026-08-11): wachtwoordstap → passkey-assertion (bekend apparaat) of -registratie (nieuw
// apparaat). Velden ≥16px (iOS-autozoom-les 11-08).

import { useEffect, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { appSlotBeschikbaar, bewaarCredentialId } from '../api/appSlot'
import type { TokenPaarResponseDto } from '../api/types'
import {
  accordeurLogin,
  accordeurPasskeyLoginOpties,
  accordeurPasskeyLoginVoltooien,
  apparaatNaam,
  haalWebauthnConfig,
  loginOpties,
  loginVoltooien,
  ondertekenAssertie,
  registratieOpties,
  registratieVoltooien,
  registreerPasskey,
  webauthnBeschikbaar,
} from './webauthnClient'

interface Props {
  naIngelogd: (paar: TokenPaarResponseDto) => void
}

export function AccordeurLogin({ naIngelogd }: Props) {
  const [eMail, setEMail] = useState('')
  const [wachtwoord, setWachtwoord] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [devStub, setDevStub] = useState(false)
  // Pincode-flow (native, 31-08): her-login = e-mail → passkey-assertion, zonder wachtwoord
  // (een pincode-geactiveerd account hééft geen wachtwoord). De wachtwoordvorm blijft als
  // expliciete terugval bereikbaar voor legacy accounts.
  const [zonderWachtwoord, setZonderWachtwoord] = useState(() => appSlotBeschikbaar())

  useEffect(() => {
    haalWebauthnConfig()
      .then((config) => setDevStub(config.dev_stub))
      .catch(() => setDevStub(false))
  }, [])

  const echteWebauthn = webauthnBeschikbaar()

  const passkeyInzenden = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setFout(null)
    setBezig(true)
    try {
      const opties = await accordeurPasskeyLoginOpties(eMail.trim())
      let paar: TokenPaarResponseDto
      if (opties.opties === null && opties.dev_stub) {
        paar = await accordeurPasskeyLoginVoltooien(eMail.trim(), { dev_stub: true })
      } else if (opties.opties) {
        const credential = await ondertekenAssertie(opties.opties)
        if (typeof credential.rawId === 'string') await bewaarCredentialId(credential.rawId)
        paar = await accordeurPasskeyLoginVoltooien(eMail.trim(), { credential })
      } else {
        throw new Error('Inloggen met passkey is nu niet mogelijk.')
      }
      naIngelogd(paar)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setFout(err.message)
        return
      }
      setFout(err instanceof Error ? err.message : 'Inloggen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (zonderWachtwoord) {
    return (
      <div className="acc-vol">
        <div className="acc-appnaam">
          Nijenhuis <span>Boekingsmodule</span>
        </div>
        <div className="acc-bio">
          <b>Inloggen</b>
          <div className="acc-sub">
            Log in met je e-mailadres en je passkey (Face ID/vingerafdruk). Daarna kies je opnieuw
            een code voor het slot op de app.
          </div>
        </div>
        {fout && <div className="acc-fout">{fout}</div>}
        <form className="acc-form" noValidate onSubmit={(e) => void passkeyInzenden(e)}>
          <label htmlFor="acc-email">E-mailadres</label>
          <input
            id="acc-email"
            type="email"
            autoComplete="username"
            inputMode="email"
            required
            value={eMail}
            onChange={(e) => setEMail(e.target.value)}
          />
          <button className="acc-btn primair" type="submit" disabled={bezig} style={{ marginTop: 6 }}>
            {bezig ? 'Bezig…' : 'Inloggen met passkey'}
          </button>
        </form>
        <button className="acc-btn secundair" onClick={() => setZonderWachtwoord(false)}>
          Inloggen met wachtwoord
        </button>
      </div>
    )
  }

  const inzenden = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    setFout(null)
    setBezig(true)
    try {
      const login = await accordeurLogin(eMail.trim(), wachtwoord)
      const setup = login.passkey_setup_token
      let paar: TokenPaarResponseDto
      if (!echteWebauthn) {
        if (!devStub) {
          setFout(
            'Passkeys vereisen een beveiligde verbinding (https of localhost). Open de app via https, of ' +
              'vraag de beheerder de dev-stub aan te zetten voor een lokale test.',
          )
          return
        }
        // Dev-stub (expliciet gemarkeerd, alleen buiten productie): bestaand stub-apparaat =
        // assertie, anders registratie.
        paar = login.heeft_passkeys
          ? await loginVoltooien(setup, { dev_stub: true })
          : await registratieVoltooien(setup, { dev_stub: true, apparaat_naam: `${apparaatNaam()} (dev-stub)` })
      } else if (login.heeft_passkeys) {
        // Bekend account: assertion als tweede factor. Heeft dít apparaat de passkey niet
        // (bv. tweede toestel), dan laat de authenticator dat zelf falen → registratiepad.
        try {
          const opties = await loginOpties(setup)
          paar = await loginVoltooien(setup, { credential: await ondertekenAssertie(opties) })
        } catch {
          const opties = await registratieOpties(setup)
          paar = await registratieVoltooien(setup, {
            credential: await registreerPasskey(opties),
            apparaat_naam: apparaatNaam(),
          })
        }
      } else {
        const opties = await registratieOpties(setup)
        paar = await registratieVoltooien(setup, {
          credential: await registreerPasskey(opties),
          apparaat_naam: apparaatNaam(),
        })
      }
      naIngelogd(paar)
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Inloggen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div className="acc-vol">
      <div className="acc-appnaam">
        Nijenhuis <span>Boekingsmodule</span>
      </div>
      <div className="acc-bio">
        <b>Inloggen</b>
        <div className="acc-sub">
          Volledig inloggen is alleen nodig bij eerste gebruik, op een nieuw apparaat of na 7 dagen
          inactiviteit — daarna volstaat de ontgrendeling bij het openen.
        </div>
        {!echteWebauthn && devStub && (
          <span className="acc-stub">DEV-STUB actief — geen echte biometrie (LAN-test zonder https)</span>
        )}
      </div>
      {fout && <div className="acc-fout">{fout}</div>}
      <form className="acc-form" noValidate onSubmit={(e) => void inzenden(e)}>
        <label htmlFor="acc-email">E-mailadres</label>
        <input
          id="acc-email"
          type="email"
          autoComplete="username"
          inputMode="email"
          required
          value={eMail}
          onChange={(e) => setEMail(e.target.value)}
        />
        <label htmlFor="acc-wachtwoord">Wachtwoord</label>
        <input
          id="acc-wachtwoord"
          type="password"
          autoComplete="current-password"
          required
          value={wachtwoord}
          onChange={(e) => setWachtwoord(e.target.value)}
        />
        <button className="acc-btn primair" type="submit" disabled={bezig} style={{ marginTop: 6 }}>
          {bezig ? 'Bezig…' : 'Inloggen'}
        </button>
      </form>
    </div>
  )
}
