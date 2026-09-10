// Het ENIGE start-/activatiescherm van de app zonder slot (app-auth zonder passkey en TOTP,
// besluit Peter 08-09-2026, contract §5b). Twee ingangen, één poort: de uitnodigingslink uit de
// mail (universal link → `/accordeur/activeren?uitnodiging=…`, verzilverd pas bij "Dit toestel
// activeren") of de 8-tekens activatiecode uit dezelfde mail. Ná een geslaagde activatie kiest de
// gebruiker een 5-cijferige toegangscode (PincodeKiezen, mockup app-lock-pincode.html schermen 1–2),
// het slot gaat dicht om het toestel-token en de app loopt door naar de flow — mét behoud van een
// `?document=`-deeplink uit de oorspronkelijke URL.
//
// Foutpaden (§5b): 400/409/429 = de servertekst (409 mét de hint "nieuwe uitnodiging via het
// kantoor"), offline = "Geen verbinding — …". Geen account-enumeratie-uitleg (0022): een onbekende
// code en een ongeldige link krijgen van de server dezelfde tekst. Biometrie zit bewust NIET in deze
// flow (standaard uit; alleen de switch in ⚙ Toegang tot de app).

import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { bewaarCredentialId, stelCodeIn } from '../api/appSlot'
import { kaleAuthFetch } from '../api/client'
import { slotModus } from '../api/nativeSessie'
import { zetWebSlotModus } from '../api/webVeiligeOpslag'
import type { TokenPaarResponseDto } from '../api/types'
import { StoreLinks } from '../auth/StoreLinks'
import { ActivatieHulp, activatiePadVanGeplakteLink } from './ActivatieHulp'
import {
  activatieFoutmelding,
  activeerApp,
  formatteerActivatiecode,
  haalAppConfig,
  haalUitnodigingInfo,
  huidigPlatform,
  isVolledigeActivatiecode,
  meldActivatieProbleem,
  meldAppLock,
  normaliseerActivatiecode,
  schrijfAppSlotAudit,
  type AppActiverenResponseDto,
  type AppConfigDto,
} from './appAuthApi'
import { PincodeKiezen } from './appslot/PincodeKiezen'
import { SlotOpslagFout } from './appslot/SlotOpslagFout'

interface Props {
  /** Uitnodigings-/herstel-token uit de universal link; null = het activatiecode-scherm. */
  token?: string | null
  herstel?: boolean
  /** Melding boven het scherm (bv. "Je toegang is verlopen of ingetrokken — …", §5c). */
  melding?: string | null
  /** Slot staat (ontgrendeld) en de sessie is gestart — de app gaat door naar de flow. */
  naGeactiveerd: (paar: TokenPaarResponseDto) => void
}

type Fase = 'code' | 'link_laden' | 'link_klaar' | 'link_ongeldig' | 'bezig' | 'toegangscode' | 'slot_bezig' | 'slot_fout'

export const TOEGANG_VERLOPEN_MELDING =
  'Je toegang is verlopen of ingetrokken — activeer de app opnieuw met een nieuwe uitnodiging van het kantoor.'

export function AppActiveren({ token = null, herstel = false, melding = null, naGeactiveerd }: Props) {
  const navigate = useNavigate()
  const native = huidigPlatform() !== 'web'
  const [fase, setFase] = useState<Fase>(token ? 'link_laden' : 'code')
  const [code, setCode] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [naam, setNaam] = useState<string | null>(null)
  const [resultaat, setResultaat] = useState<AppActiverenResponseDto | null>(null)
  const [toonHulp, setToonHulp] = useState(false)
  const [plakOpen, setPlakOpen] = useState(false)
  const [link, setLink] = useState('')
  const [linkFout, setLinkFout] = useState<string | null>(null)
  const [gemeld, setGemeld] = useState<'nee' | 'bezig' | 'ja'>('nee')
  const [hulp, setHulp] = useState<'nee' | 'bezig' | 'ja'>('nee')
  // Web-fallback van een universal link (app niet geïnstalleerd): store-links zodra gevuld.
  const [storeConfig, setStoreConfig] = useState<AppConfigDto | null>(null)

  useEffect(() => {
    if (native) return
    haalAppConfig()
      .then(setStoreConfig)
      .catch(() => setStoreConfig(null))
  }, [native])

  // Link-pad (§5b): eerst "Welkom {naam}, activeer dit toestel" — de link wordt pas verzilverd
  // bij de knop, zodat een per ongeluk geopende link niets vastlegt.
  useEffect(() => {
    if (!token) return
    let actief = true
    setFase('link_laden')
    haalUitnodigingInfo(token)
      .then((info) => {
        if (!actief) return
        setNaam(info.naam)
        setFase('link_klaar')
      })
      .catch((err: unknown) => {
        if (!actief) return
        setFout(activatieFoutmelding(err))
        setFase('link_ongeldig')
      })
    return () => {
      actief = false
    }
  }, [token])

  const activeer = async (invoer: { token?: string | null; activatiecode?: string | null }) => {
    setFout(null)
    setFase('bezig')
    try {
      const uit = await activeerApp(invoer)
      setResultaat(uit)
      setNaam(uit.naam)
      setFase('toegangscode')
    } catch (err) {
      setFout(activatieFoutmelding(err))
      setToonHulp(true)
      setFase(invoer.token ? 'link_klaar' : 'code')
    }
  }

  const codeInzenden = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!isVolledigeActivatiecode(code)) {
      setFout('Voer de volledige activatiecode van 8 tekens in.')
      return
    }
    void activeer({ activatiecode: code })
  }

  /** Ná de toegangscode: toestel-id bewaren → slot instellen (anker + code-wrap) → sessie starten
   * (AuthContext bewaart het refresh-token versleuteld) → voorwaarden-akkoord best-effort → door.
   *
   * Bugfix 10-09 (2): `stelCodeIn` geeft false als de slot-waarde NIET aantoonbaar in de opslag staat (de oude
   * stand is dan hersteld, de slot-diagnose gevuld). Dan GEEN `naGeactiveerd` en geen wachtrij — fase `slot_fout`
   * met de melding + diagnoseregel; "Opnieuw proberen" gaat terug naar de code-kiezen-stap op HETZELFDE
   * `resultaat`. Dat moet: de server-activatie is niet idempotent (de uitnodiging/activatiecode is éénmalig —
   * een tweede POST /auth/app/activeren geeft 409 "al op een ander toestel gebruikt"), maar het toestel-token in
   * `resultaat` is al uitgegeven en blijft geldig zolang het niet aan de server is gemeld als sessie. Er is nog
   * niets lokaal vastgelegd waar een sessie op rust (het refresh-token gaat pas bij `naGeactiveerd` de opslag in). */
  const toegangscodeGekozen = async (toegangscode: string) => {
    if (!resultaat) return
    setFase('slot_bezig')
    if (slotModus() === 'web') zetWebSlotModus(true)
    await bewaarCredentialId(resultaat.apparaat_credential_id)
    if (!(await stelCodeIn(toegangscode))) {
      schrijfAppSlotAudit('toegangscode_opslag_mislukt')
      setFase('slot_fout')
      return
    }
    try {
      await kaleAuthFetch('/auth/accordeur/voorwaarden-akkoord', {
        method: 'POST',
        headers: { Authorization: `Bearer ${resultaat.access_token}` },
      })
    } catch {
      // Fail-soft: GoedkeurenFlow/UrenFlow tonen het akkoord-scherm alsnog als dit niet lukte.
    }
    naGeactiveerd({ access_token: resultaat.access_token, token_type: resultaat.token_type, refresh_token: resultaat.refresh_token })
  }

  const naarGeplakteLink = () => {
    const uitkomst = activatiePadVanGeplakteLink(link)
    if ('fout' in uitkomst) {
      setLinkFout(uitkomst.fout)
      return
    }
    setLinkFout(null)
    void navigate(uitkomst.pad)
  }

  const meldKantoor = async () => {
    if (!token) return
    setGemeld('bezig')
    try {
      await meldActivatieProbleem(token)
    } catch {
      // Ook als de melding zelf faalt: de gebruiker kan niets meer doen dan het kantoor bellen.
    }
    setGemeld('ja')
  }

  const vraagNieuweUitnodiging = async () => {
    setHulp('bezig')
    await meldAppLock('/auth/app-lock/hulp')
    setHulp('ja')
  }

  const kop = (
    <div className="acc-appnaam">
      Nijenhuis <span>Boekingsmodule</span>
    </div>
  )

  if (fase === 'slot_fout' && resultaat) {
    return <SlotOpslagFout opnieuw={() => setFase('toegangscode')} />
  }

  if (fase === 'toegangscode' && resultaat) {
    return <PincodeKiezen naam={herstel || resultaat.herstel ? null : resultaat.naam} onGekozen={(c) => void toegangscodeGekozen(c)} />
  }

  if (fase === 'slot_bezig' || fase === 'link_laden' || fase === 'bezig') {
    return (
      <div className="acc-vol">
        {kop}
        <div className="acc-bio">
          <div className="acc-sub">{fase === 'link_laden' ? 'Uitnodiging controleren…' : fase === 'bezig' ? 'Toestel activeren…' : 'Bezig met openen…'}</div>
        </div>
      </div>
    )
  }

  if (fase === 'link_ongeldig') {
    return (
      <div className="acc-vol">
        {kop}
        <div className="acc-bio">
          <div className="acc-icoon">✕</div>
          <b>{herstel ? 'Deze herstel-link werkt niet meer' : 'Deze uitnodiging werkt niet meer'}</b>
          <div className="acc-sub">{fout ?? 'De link is ongeldig, al gebruikt of verlopen.'}</div>
          <div className="acc-sub">Vraag het kantoor om een nieuwe uitnodiging — er is niets vastgelegd.</div>
        </div>
        <button
          className="acc-btn secundair"
          onClick={() => {
            setFout(null)
            void navigate('/accordeur', { replace: true })
          }}
        >
          Activatiecode invoeren
        </button>
      </div>
    )
  }

  if (fase === 'link_klaar' && token) {
    return (
      <div className="acc-vol">
        {kop}
        <div className="acc-bio">
          <div className="acc-icoon">☉</div>
          <b>{herstel ? 'Toestel opnieuw koppelen' : `Welkom${naam ? `, ${naam}` : ''}`}</b>
          <div className="acc-sub">
            {herstel
              ? `${naam ? `${naam}, ` : ''}koppel dit toestel opnieuw aan je account. Daarna kies je een nieuwe code van 5 cijfers waarmee je de app opent.`
              : 'Activeer dit toestel voor de Nijenhuis Boekingsmodule. Daarna kies je een code van 5 cijfers waarmee je de app voortaan opent.'}
          </div>
        </div>
        {!native && <StoreLinks config={storeConfig} variant="fallback" />}
        {fout && <div className="acc-fout">{fout}</div>}
        <button className="acc-btn primair" onClick={() => void activeer({ token })}>
          Dit toestel activeren
        </button>
        {fout &&
          (gemeld === 'ja' ? (
            <div className="acc-sub acc-vertrouwen">✓ Het kantoor is op de hoogte en neemt contact met je op.</div>
          ) : (
            <button className="acc-btn secundair" disabled={gemeld === 'bezig'} onClick={() => void meldKantoor()}>
              {gemeld === 'bezig' ? 'Bezig…' : 'Ik kom er niet uit — meld het kantoor'}
            </button>
          ))}
      </div>
    )
  }

  // fase === 'code': het activatiecode-scherm (de standaard startstaat zonder slot).
  return (
    <div className="acc-vol">
      {kop}
      <div className="acc-bio">
        <b>Activatiecode invoeren</b>
        <div className="acc-sub">Je vindt de code in de uitnodigingsmail van het kantoor.</div>
      </div>
      {melding && (
        <div className="acc-fout" role="status">
          {melding}
        </div>
      )}
      {melding &&
        (hulp === 'ja' ? (
          <div className="acc-sub acc-vertrouwen">✓ Het kantoor is op de hoogte en stuurt je een nieuwe uitnodiging.</div>
        ) : (
          <button className="acc-btn secundair" disabled={hulp === 'bezig'} onClick={() => void vraagNieuweUitnodiging()}>
            {hulp === 'bezig' ? 'Bezig…' : 'Kantoor vragen om nieuwe uitnodiging'}
          </button>
        ))}
      {fout && <div className="acc-fout">{fout}</div>}
      <form className="acc-form" noValidate onSubmit={codeInzenden}>
        <label htmlFor="acc-activatiecode">Activatiecode</label>
        <input
          id="acc-activatiecode"
          className="acc-activatiecode"
          type="text"
          inputMode="text"
          autoCapitalize="characters"
          autoComplete="one-time-code"
          autoCorrect="off"
          spellCheck={false}
          placeholder="XXXX-XXXX"
          maxLength={9}
          value={formatteerActivatiecode(code)}
          onChange={(e) => {
            setFout(null)
            setCode(normaliseerActivatiecode(e.target.value))
          }}
        />
        <button className="acc-btn primair" type="submit" style={{ marginTop: 6 }}>
          Activeren
        </button>
      </form>
      <div className="acc-sub acc-vertrouwen">Link uit de uitnodiging ontvangen? Tik erop — de app opent dan vanzelf.</div>
      {native && !plakOpen && (
        <button type="button" className="acc-btn secundair" onClick={() => setPlakOpen(true)}>
          Link plakken
        </button>
      )}
      {native && plakOpen && (
        <div className="acc-form" style={{ width: '100%' }}>
          <label htmlFor="acc-plaklink">Uitnodigingslink uit de e-mail</label>
          <input
            id="acc-plaklink"
            type="url"
            inputMode="url"
            autoComplete="off"
            placeholder="https://app.…/activeren?token=…"
            value={link}
            onChange={(e) => {
              setLink(e.target.value)
              setLinkFout(null)
            }}
          />
          {linkFout && <div className="acc-fout">{linkFout}</div>}
          <button type="button" className="acc-btn primair" disabled={link.trim() === ''} onClick={naarGeplakteLink}>
            Naar de activatie
          </button>
        </div>
      )}
      {!native && <StoreLinks config={storeConfig} variant="fallback" />}
      <ActivatieHulp open={toonHulp} onToggle={() => setToonHulp((v) => !v)} />
    </div>
  )
}
