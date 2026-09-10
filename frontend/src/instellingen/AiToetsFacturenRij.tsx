import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { Switch } from '../ui/basis'
import { BevestigDialog } from './BevestigDialog'
import { haalAiToetsFacturen, zetAiToetsFacturen } from './instellingenApi'

/** Instellingen › Boeken platformbreed — schakelaar "AI-plausibiliteitstoets vóór automatische factuurboekingen"
 * (blok B bundel 10-09, migratie 0129): default AAN, Beheerder-only, audit server-side. De toets is een POORT boven de
 * bestaande autoboek-poorten: een factuur die het systeem automatisch wil boeken krijgt eerst één ja/nee-vraag aan de AI
 * ("is dit voorstel plausibel?"); `twijfel` of een niet-draaiende toets (AVG-gate, API-key, kostengrens) = NIET boeken,
 * zichtbaar in de werkvoorraad en de tellers. Uit = de deterministische poorten alleen (gedrag van vóór 10-09). De AI kiest
 * nooit een rekening — alleen ja/nee op het voorgestelde. Eigen GET/PUT, zelfde blok-opmaak als de noodstop-schakelaars. */
export function AiToetsFacturenRij() {
  const [stand, setStand] = useState<boolean | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [pending, setPending] = useState<boolean | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    let actueel = true
    haalAiToetsFacturen()
      .then((dto) => {
        if (actueel) setStand(dto.ingeschakeld)
      })
      .catch((err: unknown) => {
        if (actueel) setLaadFout(err instanceof ApiError ? err.message : 'Instelling niet beschikbaar.')
      })
    return () => {
      actueel = false
    }
  }, [])

  const bevestigen = async () => {
    if (pending === null) return
    setBezig(true)
    setFout(null)
    try {
      setStand((await zetAiToetsFacturen(pending)).ingeschakeld)
      setPending(null)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Wijzigen mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div
      id="ai-toets"
      data-testid="ai-toets-facturen"
      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginTop: 18, paddingTop: 16, borderTop: '1px solid var(--border)' }}
    >
      <div style={{ minWidth: 0, flex: '1 1 320px' }}>
        <h2 style={{ margin: 0 }}>AI-plausibiliteitstoets vóór automatische factuurboekingen</h2>
        <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
          Standaard <b>aan</b>: vlak vóór het systeem een factuur automatisch boekt, krijgt de AI één ja/nee-vraag over het
          voorstel (rekening, btw, bedrag tegen de historie). Twijfel of een toets die niet kan draaien (AI uit, geen sleutel,
          kostengrens) = <b>niet</b> boeken — de factuur blijft zichtbaar in de werkvoorraad. De AI kiest nooit zelf een rekening.{' '}
          <b>Uit</b> = alleen de deterministische controles; elke automatische factuurboeking krijgt dan het label
          &ldquo;AI-toets uit (platform)&rdquo; en de reconciliatie meldt dagelijks dat de toets uit staat.
        </p>
      </div>
      {laadFout ? (
        <span className="text-[12px] text-orange" role="alert">
          {laadFout}
        </span>
      ) : stand !== null ? (
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, whiteSpace: 'nowrap' }}>
          <Switch aria-label="AI-plausibiliteitstoets vóór automatische factuurboekingen" checked={stand} onChange={(e) => setPending(e.target.checked)} />
          {stand ? 'aan — AI toetst vóór het boeken' : 'uit — alleen de deterministische controles'}
        </label>
      ) : null}
      {pending !== null && (
        <BevestigDialog
          titel={`AI-plausibiliteitstoets ${pending ? 'aanzetten' : 'uitzetten'}?`}
          bericht={
            pending
              ? 'Elke automatische factuurboeking krijgt weer eerst de AI-toets; twijfel = niet boeken, mens beoordeelt. Kost AI-tegoed per toets (binnen de maandlimiet).'
              : 'Automatische factuurboekingen lopen dan alleen nog door de deterministische poorten (harde checks, geheugen, volumerem) — zonder AI-toets vooraf. Geauditeerd.'
          }
          bezig={bezig}
          fout={fout}
          onBevestigen={() => void bevestigen()}
          onAnnuleren={() => {
            setFout(null)
            setPending(null)
          }}
        />
      )}
    </div>
  )
}
