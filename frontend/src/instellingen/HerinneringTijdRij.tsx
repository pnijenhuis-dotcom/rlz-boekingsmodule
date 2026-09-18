/** Instellingen › administratie › Uren & materiaal: tijd van de dag-einde herinnering in de veld-app (run B punt 4, Peter
 * 18-09; mockup uren-uitvoerder-v3.html scherm ⑥). Per administratie, Beheerder-only (server), audit oud→nieuw; leeg =
 * standaard 16:30. Alleen ma–vr en alleen aan veldwerkers zonder uren die dag; de veldwerker kan zelf uitzetten (⚙ Toegang). */
import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { Button } from '../ui/basis'
import { haalHerinneringTijdBeheer, zetHerinneringTijdBeheer } from '../meerwerk/meerwerkApi'
import { InstellingRij } from './AdministratieDetailPagina'

export const STANDAARD_HERINNERING_TIJD = '16:30'

/** Pure validatie (spiegel van de server, contract-afwijking 3): HH:MM tussen 06:00 en 18:59 — de job draait tot 19:00. */
export function valideerHerinneringTijd(tijd: string): string | null {
  const m = /^(\d{2}):(\d{2})$/.exec(tijd.trim())
  if (!m) return 'Gebruik de vorm UU:MM, bijvoorbeeld 16:30.'
  const uur = Number(m[1])
  const min = Number(m[2])
  if (uur < 6 || uur > 18 || min > 59) return 'Kies een tijd tussen 06:00 en 18:59 (de herinnering loopt tot 19:00).'
  return null
}

export function HerinneringTijdRij({ administratieId, administratieNaam }: { administratieId: string; administratieNaam: string }) {
  const [tijd, setTijd] = useState<string | null>(null)
  const [standaard, setStandaard] = useState(true)
  const [invoer, setInvoer] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    haalHerinneringTijdBeheer(administratieId)
      .then((d) => {
        setTijd(d.tijd)
        setStandaard(d.standaard)
        setInvoer(d.tijd)
      })
      .catch((err: unknown) => setFout(err instanceof ApiError ? err.message : 'De herinneringstijd kon niet geladen worden.'))
  }, [administratieId])

  const validatie = invoer === '' ? null : valideerHerinneringTijd(invoer)
  const gewijzigd = tijd !== null && invoer.trim() !== tijd

  async function opslaan(waarde: string | null) {
    setBezig(true)
    setFout(null)
    try {
      const d = await zetHerinneringTijdBeheer(administratieId, waarde)
      setTijd(d.tijd)
      setStandaard(d.standaard)
      setInvoer(d.tijd)
    } catch (err) {
      setFout(err instanceof ApiError ? (err.status === 409 ? `Niet mogelijk: ${err.message}` : err.message) : 'Opslaan mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <InstellingRij
      titel="Herinnering einde werkdag (veld-app)"
      uitleg={`Push "Nog geen uren voor vandaag" aan veldwerkers van ${administratieNaam} die die dag nog niets invulden; alleen ma–vr, één per dag. Leeg = standaard ${STANDAARD_HERINNERING_TIJD}. De veldwerker kan 'm zelf uitzetten in de app.`}
    >
      <div data-testid="herinnering-tijd" style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <input
          type="time"
          aria-label={`Herinneringstijd voor ${administratieNaam}`}
          value={invoer}
          disabled={tijd === null || bezig}
          onChange={(e) => setInvoer(e.target.value)}
          style={{ width: 110, padding: '4px 8px' }}
        />
        {tijd !== null && standaard && !gewijzigd && <span className="chip">standaard</span>}
        {gewijzigd && (
          <Button variant="primair" maat="klein" disabled={bezig || validatie !== null || invoer === ''} onClick={() => void opslaan(invoer.trim())}>
            Opslaan
          </Button>
        )}
        {tijd !== null && !standaard && (
          <button type="button" className="linkbtn" disabled={bezig} onClick={() => void opslaan(null)}>
            terug naar standaard
          </button>
        )}
        {(fout || validatie) && (
          <span role="alert" style={{ color: 'var(--danger)', fontSize: 12 }}>
            {fout ?? validatie}
          </span>
        )}
      </div>
    </InstellingRij>
  )
}
