import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { VraagDto } from '../api/types'
import { handelVraagAf, plaatsBericht, trekVraagIn } from './vragenApi'

export function formatVraagDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

export function vraagStatusChip(status: VraagDto['status']) {
  switch (status) {
    case 'open':
      return <span className="chip vraag">Open</span>
    case 'afgehandeld':
      return <span className="chip geboekt">Afgehandeld</span>
    case 'beantwoord':
      return <span className="chip geboekt">Beantwoord</span>
    default:
      return <span className="chip geheugen">Ingetrokken</span>
  }
}

interface Props {
  vraag: VraagDto
  administratieId: string
  naamVoor: (id: string | null) => string
  onGewijzigd: () => void
  /** Kopregel (bestandsnaam, bedrag, eigenaar-hint) — de vragen-view toont die, het
   * Opmerkingen-tabblad op het controlescherm niet (daar staat het document al). */
  kop?: React.ReactNode
  /** Link naar het controlescherm tonen (niet vanuit het controlescherm zelf). */
  metFactuurlink?: boolean
}

/** Eén vraag als dialoog (besluit Peter 25-08, punt B): openingsvraag + berichten chronologisch
 * (nieuwste onderaan), elk met auteur + tijdstip; iedereen in de scope kan reageren, alleen de
 * vraagsteller ziet "Afgehandeld" (server-side hertoetst — `mag_afhandelen` is de UI-hint). De
 * vraag blokkeert boeken tot "Afgehandeld", niet al bij het eerste antwoord. Een open vraag op
 * een verwijderd document is een weesvraag: geen acties. */
export function VraagThread({ vraag, administratieId, naamVoor, onGewijzigd, kop, metFactuurlink = true }: Props) {
  const [bericht, setBericht] = useState('')
  const [intrekkenOpen, setIntrekkenOpen] = useState(false)
  const [intrekReden, setIntrekReden] = useState('')
  const [afhandelenOpen, setAfhandelenOpen] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const isOpen = vraag.status === 'open'
  const documentVerwijderd = vraag.document_status === 'verwijderd'
  const actief = isOpen && !documentVerwijderd

  async function voerUit(actie: () => Promise<unknown>, foutTekst: string) {
    setBezig(true)
    setFout(null)
    try {
      await actie()
      onGewijzigd()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : foutTekst)
    } finally {
      setBezig(false)
    }
  }

  const reageren = () =>
    voerUit(async () => {
      await plaatsBericht(administratieId, vraag.id, bericht)
      setBericht('')
    }, 'Reageren mislukt.')
  const afhandelen = () =>
    voerUit(() => handelVraagAf(administratieId, vraag.id, bericht.trim() || null), 'Afhandelen mislukt.')
  const intrekken = () => voerUit(() => trekVraagIn(administratieId, vraag.id, intrekReden.trim() || null), 'Intrekken mislukt.')

  return (
    <div className="q-item" style={actief ? undefined : { opacity: 0.7 }}>
      <div className="meta">
        {vraagStatusChip(vraag.status)}
        {kop}
        {' '}· gesteld door {naamVoor(vraag.gesteld_door)}, {formatVraagDatum(vraag.gesteld_op)} · aan{' '}
        <b>{naamVoor(vraag.toegewezen_aan)}</b>
        {isOpen && (
          <>
            {' '}
            · aan de beurt: <b>{naamVoor(vraag.aan_de_beurt)}</b>
          </>
        )}
      </div>
      <ol className="q-thread" aria-label="Dialoog">
        <li className="q-bericht q-vraag">
          <div className="q-auteur">
            {naamVoor(vraag.gesteld_door)} <span className="q-tijd">{formatVraagDatum(vraag.gesteld_op)}</span>
          </div>
          <div className="vraagtekst">&ldquo;{vraag.vraag_tekst}&rdquo;</div>
        </li>
        {vraag.berichten.map((b) => (
          <li className="q-bericht" key={b.id}>
            <div className="q-auteur">
              {naamVoor(b.auteur_id)} <span className="q-tijd">{formatVraagDatum(b.geplaatst_op)}</span>
            </div>
            <div className="vraagtekst">{b.tekst}</div>
          </li>
        ))}
      </ol>
      {vraag.status === 'afgehandeld' && (
        <div className="meta">
          afgehandeld door {naamVoor(vraag.afgehandeld_door)}
          {vraag.afgehandeld_op ? `, ${formatVraagDatum(vraag.afgehandeld_op)}` : ''} — het document is terug in de
          werkvoorraad
        </div>
      )}
      {vraag.status === 'beantwoord' && (
        <div className="meta">
          beantwoord door {naamVoor(vraag.beantwoord_door)}
          {vraag.beantwoord_op ? `, ${formatVraagDatum(vraag.beantwoord_op)}` : ''}
        </div>
      )}
      {vraag.status === 'ingetrokken' && (
        <div className="meta">
          ingetrokken door {naamVoor(vraag.ingetrokken_door)}
          {vraag.ingetrokken_op ? `, ${formatVraagDatum(vraag.ingetrokken_op)}` : ''}
          {vraag.ingetrokken_reden ? ` — “${vraag.ingetrokken_reden}”` : ''}
        </div>
      )}
      {isOpen && documentVerwijderd && (
        <div className="meta" style={{ color: 'var(--orange)' }}>
          Het document is verwijderd — deze vraag kan pas verder behandeld of ingetrokken worden nadat het document
          is hersteld (werkvoorraad → &ldquo;toon verwijderde documenten&rdquo;).
        </div>
      )}
      {fout && <div className="fout">{fout}</div>}
      {actief && (
        <div className="q-answer">
          <input
            placeholder="Reactie typen…"
            value={bericht}
            onChange={(e) => setBericht(e.target.value)}
            aria-label="Reactie"
          />
          <button type="button" className="btn" disabled={bezig || bericht.trim() === ''} onClick={() => void reageren()}>
            {bezig ? 'Bezig…' : 'Reageren'}
          </button>
          {vraag.mag_afhandelen && (
            <button
              type="button"
              className="btn secondary"
              disabled={bezig}
              onClick={() => setAfhandelenOpen((v) => !v)}
              title="Alleen de vraagsteller kan de vraag afhandelen; pas dan is boeken weer mogelijk"
            >
              Afgehandeld…
            </button>
          )}
          {metFactuurlink && (
            <Link className="btn secondary" to={`/documenten/${administratieId}/${vraag.document_id}`}>
              Factuur bekijken
            </Link>
          )}
          <button type="button" className="btn secondary" disabled={bezig} onClick={() => setIntrekkenOpen((v) => !v)}>
            Intrekken…
          </button>
        </div>
      )}
      {actief && afhandelenOpen && vraag.mag_afhandelen && (
        <div className="q-answer">
          <button type="button" className="btn" disabled={bezig} onClick={() => void afhandelen()}>
            {bezig ? 'Bezig…' : 'Vraag afgehandeld'}
          </button>
          <span className="hint" style={{ margin: 0, alignSelf: 'center' }}>
            De dialoog sluit; de factuur gaat terug naar de status van vóór de vraag en kan weer geboekt worden.
            {bericht.trim() ? ' Je getypte reactie gaat mee als slotbericht.' : ''}
          </span>
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
