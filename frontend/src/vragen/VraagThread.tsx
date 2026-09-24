import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { VraagDto } from '../api/types'
import { useAuthOptioneel } from '../auth/AuthContext'
import { documentPad } from '../werkvoorraad/format'
import { toegewezeneLabel } from './useMedewerkers'
import { handelVraagAf, heropenVraag, plaatsBericht, trekVraagIn } from './vragenApi'

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

/** Concept-bewaring per vraag (Peter 16-09: nooit stil een getypt bericht verliezen — bij een verbindingsfout blijft
 * het concept lokaal staan, ook ná een herlaad). localStorage kan ontbreken of gooien → dan alleen in het geheugen. */
export const VRAAG_CONCEPT_SLEUTEL = (vraagId: string) => `rlz.vraagconcept.${vraagId}`

function leesConcept(vraagId: string): string {
  try {
    return window.localStorage.getItem(VRAAG_CONCEPT_SLEUTEL(vraagId)) ?? ''
  } catch {
    return ''
  }
}

function bewaarConcept(vraagId: string, tekst: string): void {
  try {
    if (tekst.trim()) window.localStorage.setItem(VRAAG_CONCEPT_SLEUTEL(vraagId), tekst)
    else window.localStorage.removeItem(VRAAG_CONCEPT_SLEUTEL(vraagId))
  } catch {
    // geen opslag: concept leeft alleen in deze pagina-instantie
  }
}

/** Afgeleide stand van de dialoog (Peter 16-09): wie schreef het laatste bericht en wanneer — géén beurt-regel meer,
 * beide kanten kunnen altijd verder typen tot "Afgehandeld". */
export function laatsteBericht(vraag: VraagDto): { door: string; op: string } {
  const laatste = vraag.berichten[vraag.berichten.length - 1]
  return {
    door: vraag.laatste_bericht_door ?? laatste?.auteur_id ?? vraag.gesteld_door,
    op: vraag.laatste_bericht_op ?? laatste?.geplaatst_op ?? vraag.gesteld_op,
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
  /** Blok B5 (26-08): is de gebruiker een klant-accordeur → chip "bij de klant". */
  isKlantAccordeur?: (gebruikerId: string | null) => boolean
}

/** Eén vraag als dialoog (besluit Peter 25-08, punt B; open tot Afgehandeld, Peter 16-09): openingsvraag + berichten
 * chronologisch (nieuwste onderaan), elk met auteur + tijdstip, eigen berichten rechts; iedereen in de scope kan zo
 * vaak reageren als nodig — er is géén beurt-regel. Alleen de vraagsteller ziet "Afgehandeld" (server-side hertoetst),
 * kantoor kan "namens" afhandelen als de vraagsteller afwezig is; ná afhandelen alleen-lezen mét "Heropenen". De
 * vraag blokkeert boeken tot "Afgehandeld", niet al bij het eerste antwoord. Een open vraag op een verwijderd document
 * is een weesvraag: geen acties. */
export function VraagThread({
  vraag,
  administratieId,
  naamVoor,
  isKlantAccordeur,
  onGewijzigd,
  kop,
  metFactuurlink = true,
}: Props) {
  const auth = useAuthOptioneel()
  const mijnId = auth?.gebruikerId ?? null
  const [bericht, setBericht] = useState(() => leesConcept(vraag.id))
  const [intrekkenOpen, setIntrekkenOpen] = useState(false)
  const [intrekReden, setIntrekReden] = useState('')
  const [afhandelenOpen, setAfhandelenOpen] = useState(false)
  const [namensOpen, setNamensOpen] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  // Concept lokaal bewaren zolang het niet verstuurd is.
  useEffect(() => {
    bewaarConcept(vraag.id, bericht)
  }, [vraag.id, bericht])

  const isOpen = vraag.status === 'open'
  const documentVerwijderd = vraag.document_status === 'verwijderd'
  const actief = isOpen && !documentVerwijderd
  const laatste = laatsteBericht(vraag)
  const magNamens = Boolean(vraag.mag_afhandelen_namens) && !vraag.mag_afhandelen
  const magHeropenen = Boolean(vraag.mag_heropenen) && !documentVerwijderd

  async function voerUit(actie: () => Promise<unknown>, foutTekst: string) {
    setBezig(true)
    setFout(null)
    try {
      await actie()
      onGewijzigd()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : `${foutTekst} Je tekst is bewaard — probeer het opnieuw.`)
    } finally {
      setBezig(false)
    }
  }

  const reageren = () =>
    voerUit(async () => {
      await plaatsBericht(administratieId, vraag.id, bericht)
      setBericht('')
      bewaarConcept(vraag.id, '')
    }, 'Reageren mislukt.')
  const afhandelen = (namens: boolean) =>
    voerUit(async () => {
      await handelVraagAf(administratieId, vraag.id, bericht.trim() || null, namens)
      setBericht('')
      bewaarConcept(vraag.id, '')
    }, 'Afhandelen mislukt.')
  const intrekken = () => voerUit(() => trekVraagIn(administratieId, vraag.id, intrekReden.trim() || null), 'Intrekken mislukt.')
  const heropenen = () => voerUit(() => heropenVraag(administratieId, vraag.id), 'Heropenen mislukt.')

  return (
    <div className="q-item" style={actief ? undefined : { opacity: 0.7 }}>
      <div className="meta">
        {vraagStatusChip(vraag.status)}
        {kop}
        {' '}· gesteld door {naamVoor(vraag.gesteld_door)}, {formatVraagDatum(vraag.gesteld_op)} · aan{' '}
        <b>{toegewezeneLabel(naamVoor, vraag.toegewezen_aan)}</b>
        {isOpen && (
          <>
            {' '}
            · <span className="q-laatste" data-testid="laatste-bericht">
              laatste bericht van <b>{naamVoor(laatste.door)}</b> · {formatVraagDatum(laatste.op)}
            </span>
            {' '}
            · aan de beurt: <b>{toegewezeneLabel(naamVoor, vraag.aan_de_beurt)}</b>
            {isKlantAccordeur?.(vraag.aan_de_beurt) && (
              <span className="chip vraag" style={{ marginLeft: 6 }} title="De vraag ligt bij de klant-accordeur; die antwoordt in de app — jij kunt intussen gewoon doortypen">
                bij de klant
              </span>
            )}
          </>
        )}
      </div>
      <ol className="q-thread" aria-label="Dialoog">
        <li className={`q-bericht q-vraag${mijnId && vraag.gesteld_door === mijnId ? ' van-mij' : ''}`}>
          <div className="q-auteur">
            {naamVoor(vraag.gesteld_door)} <span className="q-tijd">{formatVraagDatum(vraag.gesteld_op)}</span>
          </div>
          <div className="vraagtekst">&ldquo;{vraag.vraag_tekst}&rdquo;</div>
        </li>
        {vraag.berichten.map((b) => (
          <li className={`q-bericht${mijnId && b.auteur_id === mijnId ? ' van-mij' : ''}`} key={b.id}>
            <div className="q-auteur">
              {naamVoor(b.auteur_id)} <span className="q-tijd">{formatVraagDatum(b.geplaatst_op)}</span>
            </div>
            <div className="vraagtekst" style={{ whiteSpace: 'pre-wrap' }}>{b.tekst}</div>
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
          <textarea
            placeholder="Reactie typen… (Enter = nieuwe regel, Cmd/Ctrl-Enter = versturen)"
            value={bericht}
            rows={2}
            onChange={(e) => setBericht(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && bericht.trim() && !bezig) {
                e.preventDefault()
                void reageren()
              }
            }}
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
          {magNamens && (
            <button
              type="button"
              className="btn secondary"
              disabled={bezig}
              onClick={() => setNamensOpen((v) => !v)}
              title="De vraagsteller is afwezig: kantoor handelt de vraag namens de vraagsteller af (audit 'afgehandeld namens')"
            >
              Afgehandeld namens vraagsteller…
            </button>
          )}
          {metFactuurlink && (
            // BUG 23-09 (Van Boxtel): de link volgt de SOORT van het document — een kassarapport opent het omzetreview-
            // scherm, nooit meer een leeg inkoopformulier. Verwijst de vraag zelf naar het omzetreview-scherm, dan staat
            // die knop er expliciet bij.
            <Link className="btn secondary" to={documentPad(administratieId, { id: vraag.document_id, soort: vraag.document_soort })}>
              Document bekijken
            </Link>
          )}
          {(vraag.document_soort === 'kassarapport' || /omzetreview/i.test(vraag.vraag_tekst)) && (
            <Link className="btn secondary" to={documentPad(administratieId, { id: vraag.document_id, soort: 'kassarapport' })}>
              Naar omzetreview →
            </Link>
          )}
          <button type="button" className="btn secondary" disabled={bezig} onClick={() => setIntrekkenOpen((v) => !v)}>
            Intrekken…
          </button>
        </div>
      )}
      {actief && afhandelenOpen && vraag.mag_afhandelen && (
        <div className="q-answer">
          <button type="button" className="btn" disabled={bezig} onClick={() => void afhandelen(false)}>
            {bezig ? 'Bezig…' : 'Vraag afgehandeld'}
          </button>
          <span className="hint" style={{ margin: 0, alignSelf: 'center' }}>
            De dialoog sluit; de factuur gaat terug naar de status van vóór de vraag en kan weer geboekt worden.
            {bericht.trim() ? ' Je getypte reactie gaat mee als slotbericht.' : ''}
          </span>
        </div>
      )}
      {actief && namensOpen && magNamens && (
        <div className="q-answer">
          <button type="button" className="btn" disabled={bezig} onClick={() => void afhandelen(true)}>
            {bezig ? 'Bezig…' : `Afgehandeld namens ${naamVoor(vraag.gesteld_door)}`}
          </button>
          <span className="hint" style={{ margin: 0, alignSelf: 'center' }}>
            Alleen als de vraagsteller afwezig is — de handeling staat als &ldquo;afgehandeld namens&rdquo; in de audit.
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
      {!isOpen && magHeropenen && (
        <div className="q-answer">
          <button type="button" className="btn secondary" disabled={bezig} onClick={() => void heropenen()} title="De dialoog gaat weer open en de factuur terug naar 'vraag open' (boeken geblokkeerd tot Afgehandeld)">
            {bezig ? 'Bezig…' : 'Heropenen'}
          </button>
        </div>
      )}
    </div>
  )
}
