// App-lock bij het openen (mockup app-lock-pincode.html schermen 4/5/6). Vervangt in de native
// schil de 24-uurs passkey-assertion: Face ID (of vingerafdruk) is het standaardpad, de code de
// terugval — beide ontgrendelen LOKAAL het anker waarmee het refresh-token leesbaar wordt;
// daarna haalt een gewone stille refresh de sessie op (server-side sliding-TTL en kill-switch
// blijven onverkort de poort). 5 foute codes = slot + sessie lokaal gewist + uitsluiting bij de
// server gemeld; herstel = verse kantoor-link (poortwachter-model, mockup-notitie ④).

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  haalCredentialId,
  isBiometrieAan,
  ontgrendelMetBiometrie,
  ontgrendelMetCode,
  wisAppSlotLokaal,
} from '../../api/appSlot'
import { BackendOnbereikbaarError, kaleAuthFetch } from '../../api/client'
import type { TokenPaarResponseDto } from '../../api/types'
import { PincodeInvoer } from './PincodeInvoer'

interface Props {
  naOntgrendeld: (paar: TokenPaarResponseDto) => void
  /** Sessie server-side dood (verlopen/kill-switch): slot is dan al gewist — door naar login. */
  naarLogin: () => void
}

type Fase = 'biometrie' | 'code' | 'sessie' | 'uitgesloten'

/** Meldt de uitsluiting/hulpvraag bij de server; zonder bekend credential_id (legacy toestel)
 * blijft het bij de lokale wissing — fail-soft, nooit een fout richting de gebruiker. */
async function meldAppLock(pad: '/auth/app-lock/uitgesloten' | '/auth/app-lock/hulp'): Promise<void> {
  const credentialId = await haalCredentialId()
  if (!credentialId) return
  try {
    await kaleAuthFetch(pad, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ credential_id: credentialId }),
    })
  } catch {
    // Offline of backend plat: de lokale wissing is al gebeurd; de kill-switch-melding is
    // best-effort (het kantoor ziet het apparaat sowieso bij de nieuwe-link-vraag).
  }
}

export function AppSlotScherm({ naOntgrendeld, naarLogin }: Props) {
  const [fase, setFase] = useState<Fase>('biometrie')
  const [code, setCode] = useState('')
  const [fout, setFout] = useState(false)
  const [melding, setMelding] = useState<string | null>(null)
  const [hulp, setHulp] = useState<'nee' | 'bezig' | 'ja'>('nee')
  const bioGestart = useRef(false)

  const haalSessie = useCallback(async () => {
    setFase('sessie')
    try {
      let resp = await kaleAuthFetch('/auth/token/vernieuwen', { method: 'POST' })
      if (resp.status === 409) {
        await new Promise((r) => setTimeout(r, 300))
        resp = await kaleAuthFetch('/auth/token/vernieuwen', { method: 'POST' })
      }
      if (resp.ok) {
        naOntgrendeld((await resp.json()) as TokenPaarResponseDto)
        return
      }
      // Sessie server-side dood (7-dagen-TTL verstreken of kill-switch): her-login = e-mail +
      // passkey; daarna kiest de gebruiker opnieuw een code — het oude slot is dan waardeloos.
      await wisAppSlotLokaal()
      naarLogin()
    } catch (err) {
      if (err instanceof BackendOnbereikbaarError) {
        setMelding('Geen verbinding met de server — controleer je internet en probeer het opnieuw.')
        setFase('code')
        return
      }
      await wisAppSlotLokaal()
      naarLogin()
    }
  }, [naOntgrendeld, naarLogin])

  // Standaardpad (scherm 4): Face ID direct bij verschijnen — één poging per opening
  // (StrictMode-dubbel afgevangen); weggetikt of mislukt = stil door naar de code (scherm 5).
  useEffect(() => {
    if (bioGestart.current) return
    bioGestart.current = true
    void (async () => {
      if (await isBiometrieAan()) {
        if (await ontgrendelMetBiometrie()) {
          void haalSessie()
          return
        }
      }
      setFase('code')
    })()
  }, [haalSessie])

  const cijfer = async (c: string) => {
    if (code.length >= 5) return
    setFout(false)
    setMelding(null)
    const nieuw = code + c
    setCode(nieuw)
    if (nieuw.length < 5) return
    const uitkomst = await ontgrendelMetCode(nieuw)
    if (uitkomst === 'ok') {
      void haalSessie()
      return
    }
    setCode('')
    if (uitkomst === 'uitgesloten') {
      setFase('uitgesloten')
      void meldAppLock('/auth/app-lock/uitgesloten')
      return
    }
    setFout(true)
    setMelding('Die code klopt niet.')
  }

  const vraagHulp = async () => {
    setHulp('bezig')
    await meldAppLock('/auth/app-lock/hulp')
    setHulp('ja')
  }

  const kop = (
    <div className="acc-appnaam">
      Nijenhuis <span>Boekingsmodule</span>
    </div>
  )

  if (fase === 'uitgesloten') {
    return (
      <div className="acc-vol">
        {kop}
        <div className="acc-bio">
          <div className="acc-icoon">✕</div>
          <b>Even opnieuw beginnen</b>
          <div className="acc-fout">De code is 5 keer onjuist ingevoerd.</div>
          <div className="acc-sub">
            Uit voorzorg is dit toestel uitgelogd. Vraag het kantoor om een nieuwe activatielink —
            daarna kies je opnieuw een code en werkt alles zoals je gewend bent.
          </div>
        </div>
        {hulp === 'ja' ? (
          <div className="acc-sub acc-vertrouwen">✓ Het kantoor is op de hoogte en stuurt je een nieuwe link.</div>
        ) : (
          <button className="acc-btn primair" disabled={hulp === 'bezig'} onClick={() => void vraagHulp()}>
            {hulp === 'bezig' ? 'Bezig…' : 'Kantoor vragen om nieuwe link'}
          </button>
        )}
      </div>
    )
  }

  if (fase === 'biometrie' || fase === 'sessie') {
    return (
      <div className="acc-vol">
        {kop}
        <div className="acc-bio">
          <b>Welkom terug</b>
          <div className="acc-faceid" />
          <div className="acc-sub">{fase === 'sessie' ? 'Bezig met openen…' : 'Ontgrendelen…'}</div>
        </div>
        {fase === 'biometrie' && (
          <button className="acc-btn secundair" onClick={() => setFase('code')}>
            Code gebruiken
          </button>
        )}
      </div>
    )
  }

  return (
    <div className="acc-vol">
      {kop}
      <div className="acc-bio">
        <b>Voer je code in</b>
        {melding && <div className="acc-fout">{melding}</div>}
      </div>
      <PincodeInvoer code={code} onCijfer={(c) => void cijfer(c)} onWis={() => setCode('')} fout={fout} />
      <div className="acc-pin-hint" />
    </div>
  )
}
