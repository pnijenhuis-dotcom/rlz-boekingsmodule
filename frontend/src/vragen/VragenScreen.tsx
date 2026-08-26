import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import type { VraagDto } from '../api/types'
import { Select, SkeletonPaneel, SkeletonRegels } from '../ui/basis'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { useMedewerkers } from './useMedewerkers'
import { VraagThread } from './VraagThread'
import { haalEigenaarOp, haalVragenOp } from './vragenApi'

function formatBedrag(bedrag: string | null): string | null {
  if (bedrag === null) return null
  const getal = Number(bedrag)
  if (!Number.isFinite(getal)) return null
  return `€ ${getal.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

interface QItemProps {
  vraag: VraagDto
  administratieId: string
  naamVoor: (id: string | null) => string
  eigenaarId: string | null
  onGewijzigd: () => void
}

/** Eén vraag-blok (mockup .q-item) = de dialoog-thread (besluit Peter 25-08) mét de kopregel
 * van de vragen-view: bestandsnaam, bedrag en eigenaar-hint. */
function QItem({ vraag, administratieId, naamVoor, eigenaarId, onGewijzigd }: QItemProps) {
  const bedrag = formatBedrag(vraag.totaalbedrag)
  return (
    <VraagThread
      vraag={vraag}
      administratieId={administratieId}
      naamVoor={naamVoor}
      onGewijzigd={onGewijzigd}
      kop={
        <>
          {' '}
          &nbsp; {vraag.document_bestandsnaam}
          {bedrag && <> · {bedrag}</>}
          {eigenaarId !== null && vraag.toegewezen_aan === eigenaarId && <> · (eigenaar administratie)</>}
        </>
      }
    />
  )
}

/** Openstaande vragen-view (mockup #vragen): open vragen actief bovenaan, beantwoorde en
 * ingetrokken vragen als grijze historie eronder. Via ?document= gefilterd op één document
 * (zo &ldquo;opent&rdquo; een klik op een vraag-regel in de werkvoorraad precies die vraag). */
export function VragenScreen() {
  const { administraties, fout: administratiesFout } = useAdministraties()
  const [searchParams, setSearchParams] = useSearchParams()
  const administratieId = searchParams.get('administratie')
  const documentFilter = searchParams.get('document')
  // Deelscherm-context (IA-verbouwing 15-08): op `/?administratie=…&sectie=vragen` moet elke
  // interne parameterwissel de sectie behouden — anders valt de gebruiker terug op de standen.
  const sectie = searchParams.get('sectie')
  const metSectie = (params: Record<string, string>) => (sectie ? { ...params, sectie } : params)

  const [vragen, setVragen] = useState<VraagDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [eigenaarId, setEigenaarId] = useState<string | null>(null)
  const { naamVoor } = useMedewerkers(administratieId)

  useEffect(() => {
    if (!administratieId && administraties && administraties.length > 0) {
      setSearchParams(
        sectie
          ? { administratie: administraties[0].id, sectie }
          : { administratie: administraties[0].id },
        { replace: true },
      )
    }
  }, [administraties, administratieId, sectie, setSearchParams])

  const laadVragen = useCallback(() => {
    if (!administratieId) return
    setFout(null)
    haalVragenOp(administratieId, documentFilter ? { documentId: documentFilter } : {})
      .then((data) => setVragen(data.vragen))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, documentFilter])

  useEffect(() => {
    setVragen(null)
    laadVragen()
  }, [laadVragen])

  useEffect(() => {
    if (!administratieId) return
    let actief = true
    haalEigenaarOp(administratieId)
      .then((data) => {
        if (actief) setEigenaarId(data.eigenaar_gebruiker_id)
      })
      .catch(() => {
        if (actief) setEigenaarId(null)
      })
    return () => {
      actief = false
    }
  }, [administratieId])

  if (administratiesFout) {
    return <div className="fout">Kon administraties niet laden: {administratiesFout}</div>
  }
  if (!administraties) return <SkeletonPaneel />
  if (administraties.length === 0) return <p className="hint">Geen administraties gekoppeld aan uw account.</p>

  const open = (vragen ?? []).filter((v) => v.status === 'open')
  const historie = (vragen ?? []).filter((v) => v.status !== 'open')

  return (
    <div>
      <div className="topbar">
        <div>
          {sectie && administratieId && (
            <div className="mb-1 text-[12.5px] text-muted">
              <Link to="/" className="text-primary no-underline hover:underline">
                Werkvoorraad
              </Link>{' '}
              <span className="text-faint">›</span>{' '}
              <Link
                to={`/?administratie=${administratieId}`}
                className="text-primary no-underline hover:underline"
              >
                {administraties.find((a) => a.id === administratieId)?.naam ?? 'Klant'}
              </Link>{' '}
              <span className="text-faint">›</span> Vragen
            </div>
          )}
          <h1>Openstaande vragen</h1>
        </div>
        <div className="adm-select">
          <label htmlFor="vragen-administratie-select" style={{ margin: 0 }}>
            Administratie
          </label>
          <Select
            id="vragen-administratie-select"
            value={administratieId ?? ''}
            onChange={(e) => setSearchParams(metSectie({ administratie: e.target.value }))}
          >
            {administraties.map((a) => (
              <option key={a.id} value={a.id}>
                {a.naam}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {documentFilter && (
        <div className="hint" style={{ marginBottom: 12 }}>
          Gefilterd op één document —{' '}
          <button
            type="button"
            className="linkbtn"
            onClick={() => setSearchParams(administratieId ? metSectie({ administratie: administratieId }) : {})}
          >
            toon alle vragen
          </button>
        </div>
      )}

      {fout && <div className="fout">{fout}</div>}
      {vragen === null && !fout && <SkeletonRegels />}
      {vragen !== null && vragen.length === 0 && (
        <p className="hint">Geen vragen voor deze administratie{documentFilter ? ' en dit document' : ''}.</p>
      )}

      {open.map((v) => (
        <QItem
          key={v.id}
          vraag={v}
          administratieId={administratieId ?? ''}
          naamVoor={naamVoor}
          eigenaarId={eigenaarId}
          onGewijzigd={laadVragen}
        />
      ))}
      {historie.map((v) => (
        <QItem
          key={v.id}
          vraag={v}
          administratieId={administratieId ?? ''}
          naamVoor={naamVoor}
          eigenaarId={eigenaarId}
          onGewijzigd={laadVragen}
        />
      ))}

      {vragen !== null && vragen.length > 0 && (
        <div className="hint">
          Een factuur met een openstaande vraag kan niet geboekt worden tot de vraagsteller de vraag als
          afgehandeld markeert (of iemand hem intrekt) — een antwoord alleen deblokkeert niet. De uitkomst wordt
          via de boeking toegevoegd aan het boekingsgeheugen.
        </div>
      )}
    </div>
  )
}
