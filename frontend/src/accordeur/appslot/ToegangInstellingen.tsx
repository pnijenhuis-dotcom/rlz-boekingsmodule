// Instellingen › Toegang tot de app (mockup app-lock-pincode.html scherm 7): Face ID-switch
// (optioneel, standaard uit), toegangscode wijzigen (huidige code vereist — zelfde foutenteller als
// het slot; ná succes een audit-event bij de server zónder code + een lokale audit-regel), direct
// vergrendelen en dit toestel loskoppelen. Bereikbaar mét ingesteld, ontgrendeld slot (native én
// PWA — app-auth zonder passkey, besluit Peter 08-09).

import { useEffect, useState } from 'react'
import { QRCodeSVG } from 'qrcode.react'
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
import { ApiError, BackendOnbereikbaarError, apiFetch } from '../../api/client'
import { leesLaatsteSlotfout } from '../../api/slotDiagnose'
import { zetWebSlotModus } from '../../api/webVeiligeOpslag'
import {
  formatteerActivatiecode,
  GEEN_VERBINDING_MELDING,
  huidigPlatform,
  laatsteCodeWijziging,
  maakToestelKoppeling,
  meldToegangscodeGewijzigd,
  normaliseerActivatiecode,
  schrijfAppSlotAudit,
  type ToestelKoppelingDto,
} from '../appAuthApi'
import { diagnoseRegel, leesLaatsteKoudeStart, leesLaatsteVerbindingsfout, nativeAppBuild } from '../koudeStart'
import { bekendeBundelId } from '../ota'
import { PincodeInvoer } from './PincodeInvoer'
import { PincodeKiezen } from './PincodeKiezen'

interface Props {
  sluit: () => void
  /** Loskoppelen afgerond (server-side intrekking geprobeerd, lokaal alles gewist): de shell zet de
   * app terug naar het activatiescherm. */
  uitloggen: () => Promise<void>
}

type Fase = 'overzicht' | 'code_huidig' | 'code_nieuw' | 'ontkoppelen' | 'koppel_code' | 'koppel_bezig' | 'koppel_klaar'

/** Label van de koppel-rij (16-09): vanuit de web-versie koppel je je telefoon/app, vanuit de app "ook op de computer". */
export function koppelLabel(native: boolean): string {
  return native ? 'Ook op de computer gebruiken?' : 'Telefoon/app koppelen'
}

function tijdKort(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function ToegangInstellingen({ sluit, uitloggen }: Props) {
  const [fase, setFase] = useState<Fase>('overzicht')
  const [bioKan, setBioKan] = useState(false)
  const [bioAan, setBioAan] = useState(false)
  const [direct, setDirect] = useState(false)
  const [huidig, setHuidig] = useState('')
  // Stap 1 (huidige code) is de verificatie — daarna her-wrapt wijzigCode direct op het anker in geheugen.
  const [huidigGeverifieerd, setHuidigGeverifieerd] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [melding, setMelding] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  // Diagnose (blok 12a 07-09): laatste koude-start-meting uit de lokale opslag + bundelversie(s);
  // puur lokaal, nooit naar de server — bedoeld voor een screenshot naar het kantoor.
  const [appBuild, setAppBuild] = useState<string | null>(null)
  const [diagnose, setDiagnose] = useState(() => diagnoseRegel(leesLaatsteKoudeStart(), null, leesLaatsteVerbindingsfout(), leesLaatsteSlotfout(), bekendeBundelId()))
  const ververDiagnose = (build: string | null) =>
    setDiagnose(diagnoseRegel(leesLaatsteKoudeStart(), build, leesLaatsteVerbindingsfout(), leesLaatsteSlotfout(), bekendeBundelId()))
  const [gekopieerd, setGekopieerd] = useState(false)
  // Lokale audit (§5d): "Laatste wijziging: dd-mm HH:MM" onder de rij — uit localStorage, geen code.
  const [laatsteWijziging, setLaatsteWijziging] = useState<string | null>(() => laatsteCodeWijziging())
  // Zelfservice tweede toestel (Peter 16-09, blok B): eerst de toegangscode opnieuw (lokale verificatie), dan de
  // koppeling bij de server (15 min, eenmalig) → QR + code op het scherm.
  const native = huidigPlatform() !== 'web'
  const [koppeling, setKoppeling] = useState<ToestelKoppelingDto | null>(null)
  const [koppelFout, setKoppelFout] = useState<string | null>(null)

  useEffect(() => {
    void biometrieBeschikbaar().then(setBioKan)
    void isBiometrieAan().then(setBioAan)
    void isDirectVergrendelen().then(setDirect)
    void nativeAppBuild().then((build) => {
      if (build) {
        setAppBuild(build)
        ververDiagnose(build)
      }
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
      setHuidigGeverifieerd(true)
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

  /** Stap 2: her-wrappen op het anker dat stap 1 al in het geheugen zette — geen tweede verificatie
   * (bugfix 10-09). 'ok' komt alleen ná bewezen opslag; 'fout' laat de oude code gelden;
   * 'niet_ontgrendeld' (slot tussendoor dicht) = terug naar stap 1, telt niet als foute code. */
  const nieuweCodeGekozen = async (code: string) => {
    if (!huidigGeverifieerd) return
    const uitkomst = await wijzigCode(code)
    setHuidigGeverifieerd(false)
    if (uitkomst === 'niet_ontgrendeld') {
      setFase('code_huidig')
      setFout('De app is tussendoor vergrendeld — voer je huidige code opnieuw in.')
      return
    }
    setFase('overzicht')
    setMelding(
      uitkomst === 'ok'
        ? 'Je toegangscode is gewijzigd.'
        : 'Toegangscode wijzigen is niet gelukt — je oude code blijft gelden. Probeer het opnieuw.',
    )
    if (uitkomst === 'fout') ververDiagnose(appBuild)
    if (uitkomst === 'ok') {
      // Audit (§4b/§5d): server-event zonder code (best-effort) + lokale regel voor "Laatste wijziging".
      schrijfAppSlotAudit('toegangscode_gewijzigd')
      setLaatsteWijziging(laatsteCodeWijziging())
      void meldToegangscodeGewijzigd()
    }
    if (uitkomst === 'ok' && bioAan) {
      // De biometrie-kopie draagt hetzelfde anker — her-wrappen raakt hem niet, maar we schrijven 'm
      // defensief opnieuw zodat kopie en wrap nooit uiteen kunnen lopen; pas ná de bewezen opslag.
      await zetBiometrieAan()
    }
  }

  /** Stap 1 van het koppelen: huidige toegangscode als verificatie (zelfde teller als het slot). */
  const koppelCijfer = async (c: string) => {
    if (huidig.length >= 5) return
    setFout(null)
    const nieuw = huidig + c
    setHuidig(nieuw)
    if (nieuw.length < 5) return
    const uitkomst = await ontgrendelMetCode(nieuw)
    setHuidig('')
    if (uitkomst === 'ok') {
      await maakKoppeling()
      return
    }
    if (uitkomst === 'uitgesloten') {
      void naUitgesloten()
      return
    }
    setFout('Die code klopt niet.')
  }

  const maakKoppeling = async () => {
    setFase('koppel_bezig')
    setKoppelFout(null)
    try {
      setKoppeling(await maakToestelKoppeling())
    } catch (err) {
      setKoppeling(null)
      if (err instanceof BackendOnbereikbaarError) setKoppelFout(GEEN_VERBINDING_MELDING)
      else if (err instanceof ApiError) setKoppelFout(err.message)
      else setKoppelFout('Koppelen is niet gelukt — probeer het opnieuw.')
    }
    setFase('koppel_klaar')
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

  if (fase === 'koppel_code') {
    return (
      <div className="acc-vol">
        <button className="acc-btn secundair klein" onClick={() => setFase('overzicht')} style={{ alignSelf: 'flex-start' }}>
          ‹ Toegang
        </button>
        <div className="acc-bio">
          <b>Voer je toegangscode in</b>
          <div className="acc-sub">Daarna krijg je een code en QR waarmee je een ander toestel aan je account koppelt.</div>
          {fout && <div className="acc-fout">{fout}</div>}
        </div>
        <PincodeInvoer code={huidig} onCijfer={(c) => void koppelCijfer(c)} onWis={() => setHuidig('')} fout={fout !== null} />
        <div className="acc-pin-hint" />
      </div>
    )
  }

  if (fase === 'koppel_bezig') {
    return (
      <div className="acc-vol">
        <div className="acc-bio">
          <div className="acc-sub">Koppeling aanmaken…</div>
        </div>
      </div>
    )
  }

  if (fase === 'koppel_klaar') {
    return (
      <div className="acc-vol" data-testid="acc-koppeling">
        <button className="acc-btn secundair klein" onClick={() => setFase('overzicht')} style={{ alignSelf: 'flex-start' }}>
          ‹ Toegang
        </button>
        <div className="acc-bio">
          <b>{koppelLabel(native)}</b>
          {koppeling ? (
            <div className="acc-sub">
              {native
                ? 'Open op de computer de web-versie en voer daar de activatiecode in, of scan de QR.'
                : 'Scan de QR met de camera van je telefoon (of open de link daar) — de app neemt de activatie over. Zonder camera: voer in de app de activatiecode in.'}
            </div>
          ) : (
            <div className="acc-fout" role="alert">
              {koppelFout ?? 'Koppelen is niet gelukt.'}
            </div>
          )}
        </div>
        {koppeling && (
          <>
            <div role="img" aria-label="QR-code met de koppelingslink" style={{ background: '#fff', padding: 12, borderRadius: 8 }}>
              <QRCodeSVG value={koppeling.link} size={180} />
            </div>
            <div className="acc-activatiecode" data-testid="acc-koppelcode" style={{ fontSize: 26, letterSpacing: 4 }}>
              {formatteerActivatiecode(normaliseerActivatiecode(koppeling.activatiecode))}
            </div>
            <div className="acc-sub acc-vertrouwen">
              Eenmalig, geldig tot {tijdKort(koppeling.verloopt_op)}. Je huidige toestellen blijven gekoppeld (
              {koppeling.actieve_toestellen + 1} van {koppeling.max_toestellen} ná dit toestel).
            </div>
          </>
        )}
        {!koppeling && (
          <button className="acc-btn secundair" onClick={() => void maakKoppeling()}>
            Opnieuw proberen
          </button>
        )}
      </div>
    )
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
      <div className="acc-toegang-kop">Andere toestellen</div>
      <button
        type="button"
        className="acc-toegang-rij"
        data-testid="acc-koppel-rij"
        onClick={() => {
          setFout(null)
          setHuidig('')
          setFase('koppel_code')
        }}
      >
        <div>
          <div className="t">{koppelLabel(native)}</div>
          <div className="s">
            {native
              ? 'Gebruik je account óók in de web-versie op een computer: je krijgt een code en QR (15 minuten geldig).'
              : 'Koppel je telefoon met de app aan dit account: je krijgt een code en QR (15 minuten geldig). Dit toestel blijft gekoppeld.'}
          </div>
        </div>
        <span aria-hidden>›</span>
      </button>
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
