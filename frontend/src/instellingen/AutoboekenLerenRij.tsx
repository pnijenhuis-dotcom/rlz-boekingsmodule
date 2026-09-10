import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import type { AutoboekenLerenStandDto } from '../api/types'
import { Switch } from '../ui/basis'
import { InstellingRij } from './AdministratieDetailPagina'
import { BevestigDialog } from './BevestigDialog'
import { AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST, haalAutoboekenLeren, zetAutoboekenLeren } from './instellingenApi'

/** Schakelaar "Autoboeken (leren en boeken)" per administratie (blok A bundel 10-09, besluit Peter 10-09, migratie 0128;
 * herziet "kandidaten → mens klikt aan" 01-09): default UIT, Beheerder-only. Aan = het systeem activeert een leverancier
 * zelf ná ≥ 3 (drempel) identieke mens-boekingen op rij (telling herzien 10-09 avond, blok 3: de eerste boeking telt
 * mee — drie identieke boekingen = actief) en boekt daarna automatisch achter alle bestaande poorten;
 * de per-leverancier-lijst eronder wordt een UITZONDERINGENLIJST. Kempen-regel: een doorbelastende administratie kan
 * niet aan — de server geeft 409 mét uitleg, de switch staat disabled mét die tekst als rode hint. Eigen GET/PUT
 * (patroon BtwDefaultRij) mét de bestaande bevestigingsdialoog; ná een geslaagde wijziging herlaadt de pagina de
 * administratie-lijst (chip in de tabel + `administratieLerenAan` van de leverancierslijst volgen). */
export function AutoboekenLerenRij({
  administratieId,
  naam,
  uitgeschakeld = false,
  onGewijzigd,
}: {
  administratieId: string
  naam: string
  uitgeschakeld?: boolean
  onGewijzigd?: (stand: AutoboekenLerenStandDto) => void
}) {
  const [stand, setStand] = useState<AutoboekenLerenStandDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [pending, setPending] = useState<boolean | null>(null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  // 409 (Kempen-regel) ná een PUT: rode hint onder de switch, ook als de GET nog `toegestaan: true` zei.
  const [geweigerd, setGeweigerd] = useState<string | null>(null)

  const laad = useCallback(async () => {
    setLaadFout(null)
    try {
      setStand(await haalAutoboekenLeren(administratieId))
    } catch (err) {
      setStand(null)
      setLaadFout(err instanceof ApiError ? err.message : 'Instelling niet beschikbaar.')
    }
  }, [administratieId])

  useEffect(() => {
    void laad()
  }, [laad])

  const bevestigen = async () => {
    if (pending === null) return
    setBezig(true)
    setFout(null)
    try {
      const nieuw = await zetAutoboekenLeren(administratieId, pending)
      setStand(nieuw)
      setGeweigerd(null)
      setPending(null)
      onGewijzigd?.(nieuw)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Niet toegestaan (doorbelasting): dialoog dicht, uitleg blijft als rode hint op de rij staan.
        setGeweigerd(err.message)
        setStand((huidig) => (huidig ? { ...huidig, toegestaan: false, reden_niet_toegestaan: err.message } : huidig))
        setPending(null)
      } else {
        setFout(err instanceof ApiError ? err.message : 'Wijzigen mislukt — probeer het opnieuw.')
      }
    } finally {
      setBezig(false)
    }
  }

  const nietToegestaan = stand !== null && !stand.toegestaan
  const hint = geweigerd ?? (nietToegestaan ? stand?.reden_niet_toegestaan ?? AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST : null)

  return (
    <div id="autoboeken-leren">
      <InstellingRij
        titel="Autoboeken (leren en boeken)"
        uitleg="Het systeem activeert een leverancier ná 3 identieke boekingen op rij; hieronder alleen uitzonderingen."
      >
        {laadFout ? (
          <span className="text-[12px] text-orange" role="alert">
            {laadFout}
          </span>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
            <label className="inst-switch-label">
              <Switch
                aria-label={`Autoboeken (leren en boeken) voor ${naam}`}
                checked={Boolean(stand?.ingeschakeld)}
                disabled={!stand || uitgeschakeld || (nietToegestaan && !stand.ingeschakeld)}
                onChange={(e) => setPending(e.target.checked)}
              />
              {stand?.ingeschakeld ? 'aan' : 'uit'}
            </label>
            {hint && (
              <span className="text-[12px] text-red" role="alert" data-testid="autoboeken-leren-hint" style={{ maxWidth: 360, textAlign: 'right' }}>
                {hint}
              </span>
            )}
          </div>
        )}
      </InstellingRij>
      {pending !== null && (
        <BevestigDialog
          titel={`Autoboeken (leren en boeken) ${pending ? 'aanzetten' : 'uitzetten'}?`}
          bericht={
            pending
              ? `Voor ${naam} activeert het systeem voortaan zelf leveranciers zodra een mens 3 op rij exact hetzelfde boekt ` +
                '(grootboek, btw en project). Daarna boeken hun facturen automatisch — alleen als álle harde checks groen zijn; een ' +
                'storno of correctie zet de leverancier terug op leren. Leveranciers die je hieronder uitzondert doen nooit mee.'
              : `Autoboeken (leren en boeken) gaat uit voor ${naam}: het systeem activeert geen leveranciers meer. Al actieve ` +
                'opt-ins blijven staan zoals ze zijn (de per-leverancier-schakelaars verschijnen weer).'
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
