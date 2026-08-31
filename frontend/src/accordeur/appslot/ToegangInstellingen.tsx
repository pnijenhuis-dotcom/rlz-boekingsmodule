// Instellingen › Toegang tot de app (mockup app-lock-pincode.html scherm 7): Face ID-switch,
// code wijzigen (huidige code vereist — zelfde foutenteller als het slot), direct vergrendelen
// en toestel ontkoppelen. Alleen bereikbaar in de native schil mét ingesteld slot.

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
import { PincodeInvoer } from './PincodeInvoer'
import { PincodeKiezen } from './PincodeKiezen'

interface Props {
  sluit: () => void
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

  useEffect(() => {
    void biometrieBeschikbaar().then(setBioKan)
    void isBiometrieAan().then(setBioAan)
    void isDirectVergrendelen().then(setDirect)
  }, [])

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
   * gewist (appSlot), de herstart landt op het login-/uitgesloten-pad. */
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
    setMelding(uitkomst === 'ok' ? 'Je code is gewijzigd.' : 'Code wijzigen is niet gelukt — probeer het opnieuw.')
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
      // Ook offline ontkoppelen we lokaal — het kantoor kan het apparaat altijd nog intrekken.
    }
    await wisAppSlotLokaal()
    await uitloggen()
  }

  if (fase === 'code_huidig') {
    return (
      <div className="acc-vol">
        <button className="acc-btn secundair klein" onClick={() => setFase('overzicht')} style={{ alignSelf: 'flex-start' }}>
          ‹ Toegang
        </button>
        <div className="acc-bio">
          <b>Voer je huidige code in</b>
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
          <b>Toestel ontkoppelen?</b>
          <div className="acc-sub">
            Dit logt dit toestel uit en trekt de toegang ervan in. Opnieuw koppelen kan met een
            verse link van het kantoor.
          </div>
        </div>
        <button className="acc-btn afwijs" disabled={bezig} onClick={() => void ontkoppel()}>
          {bezig ? 'Bezig…' : 'Ja, ontkoppel dit toestel'}
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
          <div className="t">Code wijzigen</div>
          <div className="s">Je huidige code is nodig om een nieuwe te kiezen.</div>
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
          <div className="t">Toestel ontkoppelen</div>
          <div className="s">Logt dit toestel uit; opnieuw koppelen kan met een verse link van het kantoor.</div>
        </div>
        <span aria-hidden>›</span>
      </button>
    </div>
  )
}
