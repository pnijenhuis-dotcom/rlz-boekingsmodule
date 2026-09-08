// Instellingen › Toegang tot de app (mockup app-lock-pincode.html scherm 7): Face ID-switch
// (optioneel, standaard uit), toegangscode wijzigen (huidige code vereist — zelfde foutenteller als
// het slot; ná succes een audit-event bij de server zónder code + een lokale audit-regel), direct
// vergrendelen en dit toestel loskoppelen. Bereikbaar mét ingesteld, ontgrendeld slot (native én
// PWA — app-auth zonder passkey, besluit Peter 08-09).

import { useEffect, useState } from 'react'
import {
  biometrieBeschikbaar,
  isBiometrieAan,
  isDirectVergrendelen,
  ontgrendelMetCode,
  wijzigCode,
  wisAppSlotLokaal,
  zetBiometrieAan,
  zetBiometrieUit,
  zetDirectVergrendelen,
} from '../../api/appSlot'
import { apiFetch } from '../../api/client'
import { zetWebSlotModus } from '../../api/webVeiligeOpslag'
import { laatsteCodeWijziging, meldToegangscodeGewijzigd, schrijfAppSlotAudit } from '../appAuthApi'
import { diagnoseRegel, leesLaatsteKoudeStart, leesLaatsteVerbindingsfout } from '../koudeStart'
import { PincodeInvoer } from './PincodeInvoer'
import { PincodeKiezen } from './PincodeKiezen'

/** Native "versie (build)" uit Capacitor's App-plugin (`@capacitor/app`, sinds E1 06-09 gebundeld);
 * null buiten de schil of zonder plugin — dan toont de regel alleen de web-bundelversie. */
async function nativeAppBuild(): Promise<string | null> {
  try {
    const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean; Plugins?: { App?: { getInfo?: () => Promise<{ version?: string; build?: string }> } } } })
      .Capacitor
    if (!cap?.isNativePlatform?.() || typeof cap.Plugins?.App?.getInfo !== 'function') return null
    const info = await cap.Plugins.App.getInfo()
    if (!info?.version && !info?.build) return null
    return `${info.version ?? '?'} (${info.build ?? '?'})`
  } catch {
    return null
  }
}

interface Props {
  sluit: () => void
  /** Loskoppelen afgerond (server-side intrekking geprobeerd, lokaal alles gewist): de shell zet de
   * app terug naar het activatiescherm. */
  uitloggen: () => Promise<void>
}

type Fase = 'overzicht' | 'code_huidig' | 'code_nieuw' | 'ontkoppelen'

export function ToegangInstellingen({ sluit, uitloggen }: Props) {
  const [fase, setFase] = useState<Fase>('overzicht')
  const [bioKan, setBioKan] = useState(false)
  const [bioAan, setBioAan] = useState(false)
  const [direct, setDirect] = useState(false)
  const [huidig, setHuidig] = useState('')
  const [huidigOk, setHuidigOk] = useState<string | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [melding, setMelding] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  // Diagnose (blok 12a 07-09): laatste koude-start-meting uit de lokale opslag + bundelversie(s);
  // puur lokaal, nooit naar de server — bedoeld voor een screenshot naar het kantoor.
  const [diagnose, setDiagnose] = useState(() => diagnoseRegel(leesLaatsteKoudeStart(), null, leesLaatsteVerbindingsfout()))
  const [gekopieerd, setGekopieerd] = useState(false)
  // Lokale audit (§5d): "Laatste wijziging: dd-mm HH:MM" onder de rij — uit localStorage, geen code.
  const [laatsteWijziging, setLaatsteWijziging] = useState<string | null>(() => laatsteCodeWijziging())

  useEffect(() => {
    void biometrieBeschikbaar().then(setBioKan)
    void isBiometrieAan().then(setBioAan)
    void isDirectVergrendelen().then(setDirect)
    void nativeAppBuild().then((appBuild) => {
      if (appBuild) setDiagnose(diagnoseRegel(leesLaatsteKoudeStart(), appBuild, leesLaatsteVerbindingsfout()))
    })
  }, [])

  const kopieerDiagnose = async () => {
    try {
      await navigator.clipboard.writeText(diagnose)
      setGekopieerd(true)
      setTimeout(() => setGekopieerd(false), 2000)
    } catch {
      // geen clipboard-toegang (oudere webview) — de regel is selecteerbaar, screenshot werkt altijd
    }
  }

  const wisselBiometrie = async () => {
    if (bioAan) {
      await zetBiometrieUit()
      setBioAan(false)
      return
    }
    setBioAan(await zetBiometrieAan())
  }

  const wisselDirect = async () => {
    await zetDirectVergrendelen(!direct)
    setDirect(!direct)
  }

  /** 5× fout tijdens het wijzigen = zelfde uitsluiting als op het slot: lokaal is alles al
   * gewist (appSlot), de herstart landt op het activatiescherm. */
  const naUitgesloten = async () => {
    await uitloggen()
    window.location.assign('/accordeur')
  }

  const huidigCijfer = async (c: string) => {
    if (huidig.length >= 5) return
    setFout(null)
    const nieuw = huidig + c
    setHuidig(nieuw)
    if (nieuw.length < 5) return
    // Verifieert tegen de wrap (en reset de teller); het echte her-wrappen gebeurt in stap 2.
    const uitkomst = await ontgrendelMetCode(nieuw)
    if (uitkomst === 'ok') {
      setHuidigOk(nieuw)
      setHuidig('')
      setFase('code_nieuw')
      return
    }
    setHuidig('')
    if (uitkomst === 'uitgesloten') {
      void naUitgesloten()
      return
    }
    setFout('Die code klopt niet.')
  }

  const nieuweCodeGekozen = async (code: string) => {
    if (!huidigOk) return
    const uitkomst = await wijzigCode(huidigOk, code)
    setHuidigOk(null)
    setFase('overzicht')
    setMelding(uitkomst === 'ok' ? 'Je toegangscode is gewijzigd.' : 'Toegangscode wijzigen is niet gelukt — probeer het opnieuw.')
    if (uitkomst === 'ok') {
      // Audit (§4b/§5d): server-event zonder code (best-effort) + lokale regel voor "Laatste wijziging".
      schrijfAppSlotAudit('toegangscode_gewijzigd')
      setLaatsteWijziging(laatsteCodeWijziging())
      void meldToegangscodeGewijzigd()
    }
    if (uitkomst === 'ok' && bioAan) {
      // De biometrie-kopie draagt hetzelfde anker — her-wrappen raakt hem niet, maar we
      // schrijven 'm defensief opnieuw zodat kopie en wrap nooit uiteen kunnen lopen.
      await zetBiometrieAan()
    }
  }

  const ontkoppel = async () => {
    setBezig(true)
    try {
      await apiFetch('/auth/app-lock/ontkoppelen', { method: 'POST' })
    } catch {
      // Ook offline koppelen we lokaal los — het kantoor kan het toestel altijd nog intrekken.
    }
    await wisAppSlotLokaal()
    zetWebSlotModus(false)
    await uitloggen()
  }

  if (fase === 'code_huidig') {
    return (
      <div className="acc-vol">
        <button className="acc-btn secundair klein" onClick={() => setFase('overzicht')} style={{ alignSelf: 'flex-start' }}>
          ‹ Toegang
        </button>
        <div className="acc-bio">
          <b>Voer je huidige toegangscode in</b>
          {fout && <div className="acc-fout">{fout}</div>}
        </div>
        <PincodeInvoer code={huidig} onCijfer={(c) => void huidigCijfer(c)} onWis={() => setHuidig('')} fout={fout !== null} />
        <div className="acc-pin-hint" />
      </div>
    )
  }

  if (fase === 'code_nieuw') {
    return <PincodeKiezen onGekozen={(code) => void nieuweCodeGekozen(code)} onTerug={() => setFase('overzicht')} />
  }

  if (fase === 'ontkoppelen') {
    return (
      <div className="acc-vol">
        <div className="acc-bio">
          <div className="acc-icoon">✕</div>
          <b>Dit toestel loskoppelen?</b>
          <div className="acc-sub">
            Wist de toegang op dit toestel en trekt het toestel bij het kantoor in. Opnieuw koppelen
            kan met een nieuwe uitnodiging.
          </div>
        </div>
        <button className="acc-btn afwijs" disabled={bezig} onClick={() => void ontkoppel()}>
          {bezig ? 'Bezig…' : 'Ja, koppel dit toestel los'}
        </button>
        <button className="acc-btn secundair" disabled={bezig} onClick={() => setFase('overzicht')}>
          Annuleren
        </button>
      </div>
    )
  }

  return (
    <div className="acc-vol" style={{ justifyContent: 'flex-start' }}>
      <button className="acc-btn secundair klein" onClick={sluit} style={{ alignSelf: 'flex-start' }}>
        ‹ Instellingen
      </button>
      <b style={{ fontSize: 20, alignSelf: 'flex-start', marginTop: 10 }}>Toegang tot de app</b>
      {melding && <div className="acc-sub acc-vertrouwen">{melding}</div>}
      <div className="acc-toegang-kop">Slot op de app</div>
      {bioKan && (
        <div className="acc-toegang-rij" style={{ cursor: 'default' }}>
          <div>
            <div className="t">Face ID gebruiken</div>
            <div className="s">Open de app met gezichtsherkenning. Op Android: vingerafdruk of gezicht.</div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={bioAan}
            aria-label="Face ID gebruiken"
            className={bioAan ? 'acc-slot-switch aan' : 'acc-slot-switch'}
            onClick={() => void wisselBiometrie()}
          />
        </div>
      )}
      <button type="button" className="acc-toegang-rij" onClick={() => setFase('code_huidig')}>
        <div>
          <div className="t">Toegangscode wijzigen</div>
          <div className="s">Je huidige code is nodig om een nieuwe te kiezen.</div>
          {laatsteWijziging && (
            <div className="s" data-testid="acc-laatste-wijziging">
              Laatste wijziging: {laatsteWijziging}
            </div>
          )}
        </div>
        <span aria-hidden>›</span>
      </button>
      <div className="acc-toegang-rij" style={{ cursor: 'default' }}>
        <div>
          <div className="t">Direct vergrendelen</div>
          <div className="s">Vraag het slot meteen bij het wisselen van app. Uit: pas na 5 minuten.</div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={direct}
          aria-label="Direct vergrendelen"
          className={direct ? 'acc-slot-switch aan' : 'acc-slot-switch'}
          onClick={() => void wisselDirect()}
        />
      </div>
      <div className="acc-toegang-kop">Dit toestel</div>
      <button type="button" className="acc-toegang-rij" onClick={() => setFase('ontkoppelen')}>
        <div>
          <div className="t">Dit toestel loskoppelen</div>
          <div className="s">
            Wist de toegang op dit toestel en trekt het toestel bij het kantoor in. Opnieuw koppelen kan met een nieuwe
            uitnodiging.
          </div>
        </div>
        <span aria-hidden>›</span>
      </button>
      <div className="acc-toegang-kop">Diagnose</div>
      <div className="acc-toegang-rij" style={{ cursor: 'default', flexDirection: 'column', alignItems: 'stretch' }}>
        <div>
          <div className="t">Laatste koude start</div>
          <div className="s" style={{ maxWidth: 'none' }}>
            Tijden in ms sinds het openen van de app, plus de laatste verbindingsfout van het slot; blijft
            op dit toestel. Stuur een screenshot of kopie naar het kantoor als de app traag start of geen
            verbinding krijgt.
          </div>
        </div>
        <code className="acc-diag" data-testid="acc-diagnose">
          {diagnose}
        </code>
        <button className="acc-btn secundair klein" style={{ alignSelf: 'flex-end', marginTop: 8 }} onClick={() => void kopieerDiagnose()}>
          {gekopieerd ? 'Gekopieerd' : 'Kopiëren'}
        </button>
      </div>
    </div>
  )
}
