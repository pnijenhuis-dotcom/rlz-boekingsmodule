import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { haalSplitsingUitsluitingenOp, verwijderSplitsingUitsluiting, type SplitsingUitsluitingDto } from '../intake/intakeApi'
import { InstellingRij } from './AdministratieDetailPagina'
import { BevestigDialog } from './BevestigDialog'

function datumNl(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { dateStyle: 'medium' })
}

/** Blok "Intake-regels" op de administratie-detailpagina, tab Algemeen (blok B 04-09): de actieve
 * 'nooit splitsen'-regels van déze administratie — afzender · leverancier · sinds · door — mét
 * "Verwijderen" (= deactiveren mét bevestiging en audit; de server bewaart de rij). Regels ontstaan
 * uitsluitend via "Is één factuur" in de verzamelbak; hier is geen aanmaak-knop (één schrijver). */
export function IntakeRegels({ administratieId }: { administratieId: string }) {
  const [regels, setRegels] = useState<SplitsingUitsluitingDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [teVerwijderen, setTeVerwijderen] = useState<SplitsingUitsluitingDto | null>(null)
  const [bezig, setBezig] = useState(false)
  const [verwijderFout, setVerwijderFout] = useState<string | null>(null)

  const laad = useCallback(() => {
    haalSplitsingUitsluitingenOp(administratieId)
      .then((r) => {
        setRegels(r.regels)
        setFout(null)
      })
      .catch((err: unknown) => setFout(err instanceof ApiError ? err.message : 'Intake-regels niet te laden.'))
  }, [administratieId])
  useEffect(() => {
    laad()
  }, [laad])

  const verwijder = async () => {
    if (!teVerwijderen) return
    setBezig(true)
    setVerwijderFout(null)
    try {
      await verwijderSplitsingUitsluiting(administratieId, teVerwijderen.id)
      setTeVerwijderen(null)
      laad()
    } catch (err) {
      setVerwijderFout(err instanceof ApiError ? err.message : 'Verwijderen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <>
      <h3 className="inst-groep-kop" data-testid="intake-regels-kop">
        Intake-regels
      </h3>
      <InstellingRij
        titel="Nooit splitsen"
        uitleg="Mails van deze afzenders knipt de intake nooit in delen — één factuur mét haar bijlagen (werkbonnen, urenstaten, pakbonnen). Een regel ontstaat via “Is één factuur” in de verzamelbak; handmatig samenvoegen blijft het vangnet."
      >
        <div style={{ display: 'grid', gap: 6, fontSize: 12.5, minWidth: 0 }} data-testid="intake-regels-lijst">
          {fout && <div className="fout">{fout}</div>}
          {regels === null && !fout && <span className="hint" style={{ margin: 0 }}>laden…</span>}
          {regels !== null && regels.length === 0 && (
            <span className="hint" style={{ margin: 0 }}>
              geen regels — kies in de verzamelbak “Is één factuur” mét de vink “Onthoud …” om er een te maken
            </span>
          )}
          {regels?.map((r) => (
            <div key={r.id} style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap' }}>
              <span>
                <b>{r.afzender_adres}</b>
                {r.leverancier_naam ? ` · ${r.leverancier_naam}` : ''}
                <span className="hint" style={{ margin: 0, display: 'inline' }}>
                  {' '}· sinds {datumNl(r.aangemaakt_op)}
                  {r.aangemaakt_door_naam ? ` · door ${r.aangemaakt_door_naam}` : ''}
                </span>
              </span>
              <button type="button" className="linkbtn" onClick={() => setTeVerwijderen(r)} aria-label={`Verwijder regel voor ${r.afzender_adres}`}>
                Verwijderen
              </button>
            </div>
          ))}
        </div>
      </InstellingRij>
      {teVerwijderen && (
        <BevestigDialog
          titel="Regel ‘nooit splitsen’ verwijderen"
          bericht={`Mails van ${teVerwijderen.afzender_adres} gaan hierna weer door de splitsings-AI. De regel wordt gedeactiveerd (niet gewist) en de wijziging komt in het audit-log.`}
          bezig={bezig}
          fout={verwijderFout}
          onBevestigen={() => void verwijder()}
          onAnnuleren={() => {
            setTeVerwijderen(null)
            setVerwijderFout(null)
          }}
        />
      )}
    </>
  )
}
