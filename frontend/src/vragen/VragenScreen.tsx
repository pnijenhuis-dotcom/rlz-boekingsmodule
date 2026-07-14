import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { VraagDto } from '../api/types'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { useMedewerkers } from './useMedewerkers'
import { beantwoordVraag, haalEigenaarOp, haalVragenOp, trekVraagIn } from './vragenApi'

function formatDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

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

/** Eén vraag-blok (mockup .q-item): open = actief met antwoord-invoer/intrekken/factuurlink,
 * beantwoord of ingetrokken = grijze historie. Een open vraag op een verwijderd document is een
 * weesvraag: niet actief tonen — geen acties, geen klikbare factuurlink. */
function QItem({ vraag, administratieId, naamVoor, eigenaarId, onGewijzigd }: QItemProps) {
  const [antwoord, setAntwoord] = useState('')
  const [intrekkenOpen, setIntrekkenOpen] = useState(false)
  const [intrekReden, setIntrekReden] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const isOpen = vraag.status === 'open'
  const documentVerwijderd = vraag.document_status === 'verwijderd'
  const actief = isOpen && !documentVerwijderd

  const beantwoorden = async () => {
    setBezig(true)
    setFout(null)
    try {
      await beantwoordVraag(administratieId, vraag.id, antwoord)
      onGewijzigd()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Beantwoorden mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const intrekken = async () => {
    setBezig(true)
    setFout(null)
    try {
      await trekVraagIn(administratieId, vraag.id, intrekReden.trim() || null)
      onGewijzigd()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Intrekken mislukt.')
    } finally {
      setBezig(false)
    }
  }

  const bedrag = formatBedrag(vraag.totaalbedrag)
  const chip = isOpen ? (
    <span className="chip vraag">Open</span>
  ) : vraag.status === 'beantwoord' ? (
    <span className="chip geboekt">Beantwoord</span>
  ) : (
    <span className="chip geheugen">Ingetrokken</span>
  )

  return (
    <div className="q-item" style={actief ? undefined : { opacity: 0.6 }}>
      <div className="meta">
        {chip} &nbsp; {vraag.document_bestandsnaam}
        {bedrag && <> · {bedrag}</>} · gesteld door {naamVoor(vraag.gesteld_door)}, {formatDatum(vraag.gesteld_op)} ·
        toegewezen aan <b>{naamVoor(vraag.toegewezen_aan)}</b>
        {eigenaarId !== null && vraag.toegewezen_aan === eigenaarId && <> (eigenaar administratie)</>}
      </div>
      <div className="vraagtekst" style={isOpen ? undefined : { background: 'var(--panel2, #eef0f3)' }}>
        &ldquo;{vraag.vraag_tekst}&rdquo;
        {vraag.antwoord_tekst && (
          <>
            {' '}
            → <b>&ldquo;{vraag.antwoord_tekst}&rdquo;</b>
          </>
        )}
      </div>
      {vraag.status === 'beantwoord' && (
        <div className="meta">
          beantwoord door {naamVoor(vraag.beantwoord_door)}
          {vraag.beantwoord_op ? `, ${formatDatum(vraag.beantwoord_op)}` : ''}
        </div>
      )}
      {vraag.status === 'ingetrokken' && (
        <div className="meta">
          ingetrokken door {naamVoor(vraag.ingetrokken_door)}
          {vraag.ingetrokken_op ? `, ${formatDatum(vraag.ingetrokken_op)}` : ''}
          {vraag.ingetrokken_reden ? ` — “${vraag.ingetrokken_reden}”` : ''}
        </div>
      )}
      {isOpen && documentVerwijderd && (
        <div className="meta" style={{ color: 'var(--orange)' }}>
          Het document is verwijderd — deze vraag kan pas beantwoord of ingetrokken worden nadat het document is
          hersteld (werkvoorraad → &ldquo;toon verwijderde documenten&rdquo;).
        </div>
      )}
      {fout && <div className="fout">{fout}</div>}
      {actief && (
        <div className="q-answer">
          <input
            placeholder="Antwoord typen…"
            value={antwoord}
            onChange={(e) => setAntwoord(e.target.value)}
            aria-label="Antwoord"
          />
          <button
            type="button"
            className="btn"
            disabled={bezig || antwoord.trim() === ''}
            onClick={() => void beantwoorden()}
          >
            {bezig ? 'Bezig…' : 'Beantwoorden'}
          </button>
          <Link className="btn secondary" to={`/documenten/${administratieId}/${vraag.document_id}`}>
            Factuur bekijken
          </Link>
          <button type="button" className="btn secondary" disabled={bezig} onClick={() => setIntrekkenOpen((v) => !v)}>
            Intrekken…
          </button>
        </div>
      )}
      {actief && intrekkenOpen && (
        <div className="q-answer">
          <input
            placeholder="Reden (optioneel)"
            value={intrekReden}
            onChange={(e) => setIntrekReden(e.target.value)}
            aria-label="Reden van intrekken"
          />
          <button type="button" className="btn warn" disabled={bezig} onClick={() => void intrekken()}>
            {bezig ? 'Bezig…' : 'Vraag intrekken'}
          </button>
          <span className="hint" style={{ margin: 0, alignSelf: 'center' }}>
            De factuur gaat terug naar de status van vóór de vraag; de vraag blijft als historie zichtbaar.
          </span>
        </div>
      )}
    </div>
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

  const [vragen, setVragen] = useState<VraagDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [eigenaarId, setEigenaarId] = useState<string | null>(null)
  const { naamVoor } = useMedewerkers(administratieId)

  useEffect(() => {
    if (!administratieId && administraties && administraties.length > 0) {
      setSearchParams({ administratie: administraties[0].id }, { replace: true })
    }
  }, [administraties, administratieId, setSearchParams])

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
  if (!administraties) return <p className="hint">Laden…</p>
  if (administraties.length === 0) return <p className="hint">Geen administraties gekoppeld aan uw account.</p>

  const open = (vragen ?? []).filter((v) => v.status === 'open')
  const historie = (vragen ?? []).filter((v) => v.status !== 'open')

  return (
    <div>
      <div className="topbar">
        <h1>Openstaande vragen</h1>
        <div className="adm-select">
          <label htmlFor="vragen-administratie-select" style={{ margin: 0 }}>
            Administratie
          </label>
          <select
            id="vragen-administratie-select"
            value={administratieId ?? ''}
            onChange={(e) => setSearchParams({ administratie: e.target.value })}
          >
            {administraties.map((a) => (
              <option key={a.id} value={a.id}>
                {a.naam}
              </option>
            ))}
          </select>
        </div>
      </div>

      {documentFilter && (
        <div className="hint" style={{ marginBottom: 12 }}>
          Gefilterd op één document —{' '}
          <button
            type="button"
            className="linkbtn"
            onClick={() => setSearchParams(administratieId ? { administratie: administratieId } : {})}
          >
            toon alle vragen
          </button>
        </div>
      )}

      {fout && <div className="fout">{fout}</div>}
      {vragen === null && !fout && <p className="hint">Laden…</p>}
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
          Een factuur met een openstaande vraag kan niet geboekt worden tot de vraag beantwoord (of ingetrokken)
          is. Het antwoord wordt via de boeking toegevoegd aan het boekingsgeheugen.
        </div>
      )}
    </div>
  )
}
