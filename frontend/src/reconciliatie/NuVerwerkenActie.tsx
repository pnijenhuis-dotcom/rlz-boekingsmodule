// "Nu verwerken" op de postvak-bevinding `intake_postvak_verschil` (Inzicht › Reconciliatie, blok Postvak; Peter 22-09
// "er zijn facturen gemaild die niet in onze module staan"). De rij zegt hoeveel berichten sinds gisteren in het postvak
// (INBOX + Spam, gelezen én ongelezen) staan zonder verwerking, mét de Message-ID's in de details; de knop start de
// intake-job van het kanaal opnieuw (server: POST /reconciliatie/intake/{kanaal}/nu-verwerken, 202) — idempotent op
// Message-ID, dus nooit dubbel. Signalering zonder handeling is niet af.
import { useState } from 'react'
import { ApiError } from '../api/client'
import { Button } from '../ui/basis'
import { isIntakePostvakVerschil, nuVerwerkenPostvak, type BevindingDto, type IntakeNuVerwerkenDto } from './reconciliatieApi'

export { isIntakePostvakVerschil }

export function nuVerwerkenMelding(r: IntakeNuVerwerkenDto): string {
  const adres = r.postvak_adres ?? r.kanaal
  return r.voertuig === 'cloud_run_job'
    ? `Intake-job voor ${adres} gestart — de uitkomst staat binnen enkele minuten in de werkvoorraad en bij de volgende reconciliatie-run.`
    : `Intake voor ${adres} gestart (achtergrond).`
}

export function NuVerwerkenActie({
  bevinding,
  onGelukt,
}: {
  bevinding: BevindingDto
  onGelukt: (melding: string) => void
}) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [klaar, setKlaar] = useState<IntakeNuVerwerkenDto | null>(null)
  const kanaal = String(bevinding.detail?.kanaal ?? '')
  const adres = typeof bevinding.detail?.postvak_adres === 'string' ? (bevinding.detail.postvak_adres as string) : kanaal
  const aantal = typeof bevinding.detail?.aantal === 'number' ? (bevinding.detail.aantal as number) : null

  const uitvoeren = async () => {
    if (!kanaal) return
    setBezig(true)
    setFout(null)
    try {
      const r = await nuVerwerkenPostvak(kanaal)
      setKlaar(r)
      onGelukt(nuVerwerkenMelding(r))
    } catch (err) {
      // 502 = de job kon niet gestart worden (IAM/resource) — zichtbaar op de rij, nooit stil.
      setFout(err instanceof ApiError ? err.message : 'Nu verwerken mislukt.')
    } finally {
      setBezig(false)
    }
  }

  if (klaar) {
    return <span className="hint">intake gestart — wacht op de volgende run</span>
  }
  return (
    <>
      <Button
        variant="primair"
        maat="klein"
        onClick={() => void uitvoeren()}
        disabled={!kanaal || bezig}
        aria-label={`Postvak ${adres} nu verwerken${aantal !== null ? ` (${aantal} bericht(en))` : ''}`}
      >
        {bezig ? 'Bezig…' : 'Nu verwerken'}
      </Button>
      {fout && (
        <>
          {' '}
          <span className="hint" style={{ color: 'var(--red)' }}>
            {fout}
          </span>
        </>
      )}
    </>
  )
}
