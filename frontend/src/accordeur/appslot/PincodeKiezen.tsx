// Code kiezen + bevestigen (mockup app-lock-pincode.html schermen 1–2). Puur lokaal: de code
// verlaat dit component alleen via onGekozen — nooit richting server. Zwakke reeksen (12345,
// 00000 …) worden vriendelijk geweigerd (mockup-notitie ⑥).

import { useState } from 'react'
import { CODE_LENGTE, isZwakkeCode } from '../../api/appSlot'
import { PincodeInvoer } from './PincodeInvoer'

interface Props {
  /** "Welkom, Jan" bij activatie; null = neutrale kop (code wijzigen / her-instellen). */
  naam?: string | null
  /** Stappenbalk-inhoud boven de kop (activatieflow) — het component zelf kent geen stappen. */
  boven?: React.ReactNode
  onGekozen: (code: string) => void
  onTerug?: () => void
}

export function PincodeKiezen({ naam = null, boven, onGekozen, onTerug }: Props) {
  const [stap, setStap] = useState<'kiezen' | 'bevestigen'>('kiezen')
  const [eerste, setEerste] = useState('')
  const [code, setCode] = useState('')
  const [melding, setMelding] = useState<string | null>(null)
  const [fout, setFout] = useState(false)

  const cijfer = (c: string) => {
    if (code.length >= CODE_LENGTE) return
    setFout(false)
    setMelding(null)
    const nieuw = code + c
    setCode(nieuw)
    if (nieuw.length < CODE_LENGTE) return
    if (stap === 'kiezen') {
      if (isZwakkeCode(nieuw)) {
        setCode('')
        setFout(true)
        setMelding('Die code is te makkelijk te raden — kies geen reeks als 12345 of 00000.')
        return
      }
      setEerste(nieuw)
      setCode('')
      setStap('bevestigen')
      return
    }
    if (nieuw !== eerste) {
      setCode('')
      setFout(true)
      setMelding('De codes komen niet overeen — probeer het nog een keer.')
      return
    }
    onGekozen(nieuw)
  }

  const terugNaarKiezen = () => {
    setStap('kiezen')
    setEerste('')
    setCode('')
    setMelding(null)
    setFout(false)
  }

  return (
    <div className="acc-vol">
      {boven}
      <div className="acc-appnaam">
        Nijenhuis <span>Boekingsmodule</span>
      </div>
      <div className="acc-bio">
        <b>
          {stap === 'kiezen'
            ? naam
              ? `Welkom, ${naam}`
              : 'Kies een code'
            : 'Nog één keer'}
        </b>
        <div className="acc-sub">
          {stap === 'kiezen'
            ? `Kies een code van ${CODE_LENGTE} cijfers. Hiermee open je voortaan de app.`
            : 'Voer dezelfde code nog een keer in.'}
        </div>
      </div>
      <PincodeInvoer
        code={code}
        onCijfer={cijfer}
        onWis={() => setCode('')}
        fout={fout}
        linksKnop={
          stap === 'bevestigen'
            ? { label: '‹ Terug', onClick: terugNaarKiezen }
            : onTerug
              ? { label: '‹ Terug', onClick: onTerug }
              : undefined
        }
      />
      <div className="acc-pin-hint">{melding ?? (stap === 'kiezen' ? 'Geen reeks als 12345 of 00000.' : '')}</div>
    </div>
  )
}
