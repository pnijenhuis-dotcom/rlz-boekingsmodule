// Activeringsflow externe app-rollen (klant-accordeur + veldrollen) — mobiel-first + ATOMAIR
// (besluit Peter 28-08, mockup/activatie-mobiel.html §2 = bouwnorm). Drie stappen in één
// transactie: 1 wachtwoord kiezen (server parkeert de hash op de link, legt niets vast) →
// 2 passkey aanmaken (server maakt in dezelfde transactie wachtwoord + account definitief en
// verbruikt de link) → 3 "Account actief". Mislukt stap 2, dan is er niets half geregistreerd
// en blijft de link bruikbaar: "Opnieuw proberen" of "meld het kantoor". De voorwaarden +
// privacyverklaring volgen direct hierna (GoedkeurenFlow/UrenFlow tonen het akkoord-scherm
// zolang de server de wachtrij weigert — fail-closed).
//
// Legacy-ingang `passkeySetupToken` (navigation-state, alleen stap 2): blijft bestaan voor de
// nieuwe-apparaat-route en oude deep-links; nieuwe activaties komen mét `uitnodigingToken`.

import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, apiPostJson } from '../api/client'
import type { TokenPaarResponseDto, UitnodigingAccepterenResponseDto } from '../api/types'
import {
  apparaatNaam,
  haalUitnodigingInfo,
  haalWebauthnConfig,
  loginOpties,
  loginVoltooien,
  meldActivatieProbleem,
  ondertekenAssertie,
  registratieOpties,
  registratieVoltooien,
  registreerPasskey,
  webauthnBeschikbaar,
} from './webauthnClient'

interface Props {
  /** Uitnodigings-/herstel-token uit de mail (nieuwe flow, 28-08). */
  uitnodigingToken?: string
  herstel?: boolean
  /** Legacy: passkey_setup-token uit een eerdere wachtwoordstap — begint direct bij stap 2. */
  passkeySetupToken?: string
  naIngelogd: (paar: TokenPaarResponseDto) => void
}

type Stap = 'laden' | 'wachtwoord' | 'passkey' | 'mislukt' | 'klaar' | 'link_ongeldig'

const MIN_WACHTWOORD = 12

export function AccordeurActiveren({ uitnodigingToken, herstel = false, passkeySetupToken, naIngelogd }: Props) {
  const [stap, setStap] = useState<Stap>(uitnodigingToken ? 'laden' : 'passkey')
  const [naam, setNaam] = useState<string | null>(null)
  const [setupToken, setSetupToken] = useState<string | null>(passkeySetupToken ?? null)
  const [wachtwoord, setWachtwoord] = useState('')
  const [herhaal, setHerhaal] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [devStub, setDevStub] = useState(false)
  const [paar, setPaar] = useState<TokenPaarResponseDto | null>(null)
  const [gemeld, setGemeld] = useState<'nee' | 'bezig' | 'ja'>('nee')

  useEffect(() => {
    haalWebauthnConfig()
      .then((config) => setDevStub(config.dev_stub))
      .catch(() => setDevStub(false))
  }, [])

  useEffect(() => {
    if (!uitnodigingToken) return
    let actief = true
    haalUitnodigingInfo(uitnodigingToken)
      .then((info) => {
        if (!actief) return
        setNaam(info.naam)
        setStap('wachtwoord')
      })
      .catch((err: unknown) => {
        if (!actief) return
        setFout(err instanceof ApiError ? err.message : 'De link kon niet worden gecontroleerd.')
        setStap('link_ongeldig')
      })
    return () => {
      actief = false
    }
  }, [uitnodigingToken])

  const echteWebauthn = webauthnBeschikbaar()

  const wachtwoordInzenden = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!uitnodigingToken) return
    setFout(null)
    if (wachtwoord.length < MIN_WACHTWOORD) {
      setFout(`Kies een wachtwoord van minimaal ${MIN_WACHTWOORD} tekens.`)
      return
    }
    if (wachtwoord !== herhaal) {
      setFout('De wachtwoorden komen niet overeen.')
      return
    }
    setBezig(true)
    try {
      const resultaat = await apiPostJson<UitnodigingAccepterenResponseDto>('/auth/uitnodigingen/accepteren', {
        token: uitnodigingToken,
        wachtwoord,
      })
      if (resultaat.soort !== 'passkey' || !resultaat.passkey_setup_token) {
        throw new Error('Deze link hoort bij een kantoor-account — open hem in de webapp.')
      }
      setSetupToken(resultaat.passkey_setup_token)
      setStap('passkey')
    } catch (err) {
      const bericht = err instanceof Error ? err.message : 'Wachtwoord instellen mislukt.'
      if (err instanceof ApiError && err.status === 400 && /gebruikt|verlopen|Ongeldig/i.test(bericht)) {
        setFout(bericht)
        setStap('link_ongeldig')
      } else {
        setFout(bericht)
      }
    } finally {
      setBezig(false)
    }
  }

  const registreer = async (metStub: boolean) => {
    if (!setupToken) return
    setFout(null)
    setBezig(true)
    try {
      let nieuwPaar: TokenPaarResponseDto
      if (metStub) {
        nieuwPaar = await registratieVoltooien(setupToken, {
          dev_stub: true,
          apparaat_naam: `${apparaatNaam()} (dev-stub)`,
        })
      } else {
        const opties = await registratieOpties(setupToken)
        try {
          nieuwPaar = await registratieVoltooien(setupToken, {
            credential: await registreerPasskey(opties),
            apparaat_naam: apparaatNaam(),
          })
        } catch (registratieFout) {
          // Zelfherstel (kliktest Peter 2026-08-15, 2e reproductie): was de registratie
          // server-side al gelukt, dan weigert de authenticator een tweede registratie via
          // excludeCredentials met een NotAllowedError. Diezelfde fout is ook "geannuleerd"
          // (WebAuthn maakt dat bewust ononderscheidbaar), dus de server is de waarheid:
          // een assertion slaagt alléén als dít apparaat al een geregistreerde passkey
          // draagt — dan loggen we daarmee in en schakelt de flow gewoon door.
          if (!(registratieFout instanceof DOMException && registratieFout.name === 'NotAllowedError')) {
            throw registratieFout
          }
          try {
            const assertieOpties = await loginOpties(setupToken)
            nieuwPaar = await loginVoltooien(setupToken, {
              credential: await ondertekenAssertie(assertieOpties),
            })
          } catch {
            throw registratieFout
          }
        }
      }
      setPaar(nieuwPaar)
      if (uitnodigingToken) {
        setStap('klaar')
      } else {
        naIngelogd(nieuwPaar)
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401 && uitnodigingToken) {
        // Setup-token (10 min) verlopen: terug naar stap 1 — de link zelf is nog geldig.
        setSetupToken(null)
        setFout('Dat duurde te lang — kies je wachtwoord opnieuw en maak dan direct de passkey aan.')
        setStap('wachtwoord')
        return
      }
      setFout(err instanceof Error ? err.message : 'Registreren mislukt.')
      setStap(uitnodigingToken ? 'mislukt' : 'passkey')
    } finally {
      setBezig(false)
    }
  }

  const meldKantoor = async () => {
    if (!uitnodigingToken) return
    setGemeld('bezig')
    try {
      await meldActivatieProbleem(uitnodigingToken)
    } catch {
      // Ook als de melding zelf faalt: de gebruiker kan niets meer doen dan het kantoor bellen.
    }
    setGemeld('ja')
  }

  const kop = (
    <div className="acc-appnaam">
      Nijenhuis <span>Boekingsmodule</span>
    </div>
  )
  const totaal = uitnodigingToken ? 3 : null
  const stapTeller = (n: number, extra?: string) =>
    totaal ? (
      <div className="acc-stapteller">
        Stap {n} van {totaal}
        {extra ? ` — ${extra}` : ''}
      </div>
    ) : null

  if (stap === 'laden') {
    return (
      <div className="acc-vol">
        {kop}
        <div className="acc-bio">
          <div className="acc-sub">Link controleren…</div>
        </div>
      </div>
    )
  }

  if (stap === 'link_ongeldig') {
    return (
      <div className="acc-vol">
        {kop}
        <div className="acc-bio">
          <div className="acc-icoon">✕</div>
          <b>{herstel ? 'Herstel-link werkt niet meer' : 'Activatielink werkt niet meer'}</b>
          <div className="acc-sub">{fout ?? 'De link is ongeldig, al gebruikt of verlopen.'}</div>
          <div className="acc-sub">
            Al geactiveerd? Log dan gewoon in. Anders vraagt u het kantoor om een nieuwe link — er is niets
            vastgelegd.
          </div>
        </div>
      </div>
    )
  }

  if (stap === 'wachtwoord') {
    return (
      <div className="acc-vol">
        {kop}
        {stapTeller(1)}
        <div className="acc-bio">
          <b>{herstel ? `Nieuw wachtwoord${naam ? `, ${naam}` : ''}` : `Welkom${naam ? `, ${naam}` : ''}`}</b>
          <div className="acc-sub">
            {herstel
              ? 'Kies een nieuw wachtwoord. Dit is uw terugval — dagelijks ontgrendelt u met gezicht of vingerafdruk.'
              : 'Kies een wachtwoord. Dit is uw terugval — dagelijks ontgrendelt u met gezicht of vingerafdruk.'}
          </div>
        </div>
        {fout && <div className="acc-fout">{fout}</div>}
        <form className="acc-form" noValidate onSubmit={(e) => void wachtwoordInzenden(e)}>
          <label htmlFor="acc-act-wachtwoord">Wachtwoord (minimaal {MIN_WACHTWOORD} tekens)</label>
          <input
            id="acc-act-wachtwoord"
            type="password"
            autoComplete="new-password"
            minLength={MIN_WACHTWOORD}
            required
            value={wachtwoord}
            onChange={(e) => setWachtwoord(e.target.value)}
          />
          <label htmlFor="acc-act-herhaal">Herhaal wachtwoord</label>
          <input
            id="acc-act-herhaal"
            type="password"
            autoComplete="new-password"
            required
            value={herhaal}
            onChange={(e) => setHerhaal(e.target.value)}
          />
          <button className="acc-btn primair" type="submit" disabled={bezig} style={{ marginTop: 6 }}>
            {bezig ? 'Bezig…' : 'Doorgaan'}
          </button>
        </form>
        <div className="acc-sub acc-vertrouwen">🔒 Er is nog niets vastgelegd — dat gebeurt pas samen met de passkey.</div>
      </div>
    )
  }

  if (stap === 'mislukt') {
    return (
      <div className="acc-vol">
        {kop}
        {stapTeller(2, 'mislukt')}
        <div className="acc-bio">
          <div className="acc-icoon">✕</div>
          <b>Dat lukte niet</b>
          <div className="acc-sub">
            De passkey kon niet worden aangemaakt. Uw wachtwoord is niet vastgelegd — er is niets half
            geregistreerd. Probeer het opnieuw; blijft het misgaan, dan neemt het kantoor contact met u op.
          </div>
          {fout && <div className="acc-sub acc-foutdetail">{fout}</div>}
        </div>
        <button
          className="acc-btn primair"
          disabled={bezig}
          onClick={() => {
            setFout(null)
            setStap('passkey')
          }}
        >
          Opnieuw proberen
        </button>
        {gemeld === 'ja' ? (
          <div className="acc-sub acc-vertrouwen">✓ Het kantoor is op de hoogte en neemt contact met u op.</div>
        ) : (
          <button className="acc-btn secundair" disabled={gemeld === 'bezig'} onClick={() => void meldKantoor()}>
            {gemeld === 'bezig' ? 'Bezig…' : 'Ik kom er niet uit — meld het kantoor'}
          </button>
        )}
      </div>
    )
  }

  if (stap === 'klaar' && paar) {
    return (
      <div className="acc-vol">
        {kop}
        {stapTeller(3)}
        <div className="acc-bio">
          <div className="acc-icoon ok">✓</div>
          <b>Account actief</b>
          <div className="acc-sub">
            {herstel
              ? 'Nieuw wachtwoord én passkey staan. Uw eerdere apparaten blijven geregistreerd.'
              : 'Wachtwoord én passkey staan. Hierna leest u de voorwaarden en kunt u aan de slag.'}
          </div>
        </div>
        <button className="acc-btn primair" onClick={() => naIngelogd(paar)}>
          Naar de app
        </button>
      </div>
    )
  }

  // stap === 'passkey'
  return (
    <div className="acc-vol">
      {kop}
      {stapTeller(2)}
      <div className="acc-bio">
        <div className="acc-icoon">☉</div>
        <b>{uitnodigingToken ? 'Beveilig met uw gezicht of vingerafdruk' : 'Dit apparaat registreren'}</b>
        <div className="acc-sub">
          {uitnodigingToken
            ? 'Uw telefoon maakt een passkey aan — daarmee opent u de app voortaan zonder wachtwoord.'
            : 'Je wachtwoord staat. Registreer nu dit apparaat met een passkey (Face ID, Touch ID, vingerafdruk of de toegangscode van je toestel) — daarna log je hier vanzelf mee in.'}
        </div>
        {!echteWebauthn && devStub && (
          <span className="acc-stub">DEV-STUB actief — geen echte biometrie (LAN-test zonder https)</span>
        )}
      </div>
      {fout && <div className="acc-fout">{fout}</div>}
      {echteWebauthn && (
        <button className="acc-btn primair" disabled={bezig} onClick={() => void registreer(false)}>
          {bezig ? 'Bezig…' : 'Passkey aanmaken'}
        </button>
      )}
      {!echteWebauthn && devStub && (
        <button className="acc-btn primair" disabled={bezig} onClick={() => void registreer(true)}>
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
