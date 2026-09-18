/** ⚙ Toegang › Herinneringen (run B punt 4, Peter 18-09; mockup uren-uitvoerder-v3.html scherm ⑥): schakelaar "Herinnering
 * einde werkdag" — opt-out PER GEBRUIKER (beslispunt: de herinnering hoort bij de persoon, niet bij één toestel), via
 * `GET/PUT /uren/zzp/herinnering`. De tijd stelt het kantoor per administratie in (default 16:30); de app toont 'm alleen. */
import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { haalHerinnering, zetHerinnering, type HerinneringInstellingDto } from '../../uren/urenApi'

export function HerinneringSchakelaar() {
  const [stand, setStand] = useState<HerinneringInstellingDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)

  useEffect(() => {
    haalHerinnering()
      .then(setStand)
      .catch((err: unknown) => setFout(err instanceof ApiError ? err.message : 'De herinnering-instelling kon niet geladen worden.'))
  }, [])

  const wissel = async () => {
    if (!stand || bezig) return
    setBezig(true)
    setFout(null)
    try {
      setStand(await zetHerinnering(!stand.uit))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan is niet gelukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const aan = stand ? !stand.uit : false
  const tijd = stand?.tijd ?? '16:30'
  return (
    <>
      <div className="acc-toegang-kop">Herinneringen</div>
      <div className="acc-toegang-rij" style={{ cursor: 'default' }} data-testid="acc-herinnering-rij">
        <div>
          <div className="t">Herinnering einde werkdag</div>
          <div className="s">
            Om {tijd} een melding &quot;Nog geen uren voor vandaag&quot; — alleen op werkdagen en alleen als je die dag nog niets hebt
            ingevuld. De tijd stelt het kantoor in.
          </div>
          {fout && (
            <div className="s" role="alert" style={{ color: 'var(--acc-orange)' }}>
              {fout}
            </div>
          )}
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={aan}
          aria-label="Herinnering einde werkdag"
          disabled={stand === null || bezig}
          className={aan ? 'acc-slot-switch aan' : 'acc-slot-switch'}
          onClick={() => void wissel()}
        />
      </div>
    </>
  )
}
