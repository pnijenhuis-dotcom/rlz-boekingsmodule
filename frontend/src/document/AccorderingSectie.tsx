import { useCallback, useEffect, useState } from 'react'
import {
  haalAccorderingVanDocument,
  haalLaatstHerinnerd,
  herinnerAccordeur,
  trekAccorderingIn,
  type AccorderingDto,
  type AccorderingStapDto,
} from '../accordering/accorderingApi'

function formatTijdstip(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'short', timeStyle: 'short' })
}

function stapChip(stap: AccorderingStapDto) {
  if (!stap.vereist) {
    return <span className="chip geboekt">niet vereist (onder drempel)</span>
  }
  if (stap.besluit === 'akkoord') {
    return stap.besluit_bron === 'staande_regel' ? (
      <span className="chip geheugen">automatisch akkoord — staande goedkeuring</span>
    ) : (
      <span className="chip geheugen">akkoord</span>
    )
  }
  if (stap.besluit === 'afgewezen') {
    return <span className="chip vraag">afgewezen</span>
  }
  return stap.aan_de_beurt ? (
    <span className="chip vraag">aan de beurt</span>
  ) : (
    <span className="chip ai">wacht op eerdere laag</span>
  )
}

/** Accorderingshistorie op het controlescherm (mockup #autorisatie): de sequentiële lagen met
 * hun besluit + tijdstip, en — zolang de ronde open staat — de intrekken-actie voor het
 * kantoor. De accordeur zelf werkt straks in de aparte PWA, niet hier. */
export function AccorderingSectie({
  administratieId,
  documentId,
  documentStatus,
  onGewijzigd,
}: {
  administratieId: string
  documentId: string
  documentStatus: string
  onGewijzigd: () => void
}) {
  const [accordering, setAccordering] = useState<AccorderingDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [herinnerBezig, setHerinnerBezig] = useState(false)
  const [laatstHerinnerd, setLaatstHerinnerd] = useState<string | null>(null)

  const laad = useCallback(() => {
    haalAccorderingVanDocument(administratieId, documentId)
      .then(setAccordering)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
    // "Laatst herinnerd" is verrijking — een fout hier blokkeert de sectie niet.
    haalLaatstHerinnerd(administratieId)
      .then((data) => setLaatstHerinnerd(data.laatst_herinnerd[documentId] ?? null))
      .catch(() => undefined)
  }, [administratieId, documentId])

  useEffect(laad, [laad, documentStatus])

  const intrekken = async () => {
    setBezig(true)
    setFout(null)
    try {
      await trekAccorderingIn(administratieId, documentId)
      onGewijzigd()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Intrekken mislukt')
    } finally {
      setBezig(false)
    }
  }

  const herinneren = async () => {
    setHerinnerBezig(true)
    setFout(null)
    try {
      const resultaat = await herinnerAccordeur(administratieId, documentId)
      setLaatstHerinnerd(resultaat.verzonden_op)
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Herinneren mislukt')
    } finally {
      setHerinnerBezig(false)
    }
  }

  if (accordering === null) return null

  return (
    <div className="panel">
      <h2>
        Klant-accordering{' '}
        {accordering.status === 'open' ? (
          <span className="chip geheugen">bij klant</span>
        ) : accordering.status === 'afgerond' ? (
          <span className="chip geboekt">alle lagen akkoord</span>
        ) : accordering.status === 'afgewezen' ? (
          <span className="chip vraag">afgewezen door accordeur</span>
        ) : (
          <span className="chip">ingetrokken</span>
        )}
      </h2>
      <table>
        <thead>
          <tr>
            <th>Laag</th>
            <th>Accordeur</th>
            <th>Voorwaarde</th>
            <th>Status</th>
            <th>Besloten op</th>
          </tr>
        </thead>
        <tbody>
          {accordering.stappen.map((stap) => (
            <tr key={stap.volgnummer}>
              <td>
                <b>{stap.volgnummer}</b>
              </td>
              <td>{stap.accordeur_naam ?? stap.accordeur_gebruiker_id}</td>
              <td>{stap.bedrag_drempel ? `alleen > € ${stap.bedrag_drempel}` : 'alle facturen'}</td>
              <td>
                {stapChip(stap)}
                {stap.reden && <div className="hint">reden: &ldquo;{stap.reden}&rdquo;</div>}
              </td>
              <td>{formatTijdstip(stap.besloten_op)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="hint">
        Aangeboden {formatTijdstip(accordering.aangeboden_op)}
        {accordering.afgerond_op && ` · afgerond ${formatTijdstip(accordering.afgerond_op)}`}
        {laatstHerinnerd && ` · laatst herinnerd ${formatTijdstip(laatstHerinnerd)}`} — na het laatste
        akkoord boekt de motor automatisch, mét alle harde checks opnieuw.
      </div>
      {fout && <div className="fout">{fout}</div>}
      {accordering.status === 'open' && (
        <div className="actions">
          <button type="button" className="btn secondary" disabled={herinnerBezig} onClick={() => void herinneren()}>
            {herinnerBezig ? 'Bezig…' : 'Herinner accordeur'}
          </button>
          <button type="button" className="btn secondary" disabled={bezig} onClick={() => void intrekken()}>
            {bezig ? 'Bezig…' : 'Terughalen uit accordering'}
          </button>
        </div>
      )}
    </div>
  )
}
