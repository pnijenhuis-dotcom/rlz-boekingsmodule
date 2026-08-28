import { useCallback, useEffect, useState } from 'react'
import { apiFetch } from '../api/client'
import {
  haalAccorderingVanDocument,
  haalLaatstHerinnerd,
  herinnerAccordeur,
  trekAccorderingIn,
  type AccorderingDto,
  type AccorderingStapDto,
} from '../accordering/accorderingApi'
import { herinnerTijdLabel, isVandaagHerinnerd } from '../accordering/herinnerDag'

function formatTijdstip(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'short', timeStyle: 'short' })
}

/** 409/403/429-antwoorden van de boek-route leesbaar maken (string-detail of {message, checks}). */
function foutTekst(body: unknown, status: number): string {
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object') {
      const d = detail as { message?: string; checks?: { resultaten?: { ok: boolean; melding: string }[] } }
      const rood = d.checks?.resultaten?.filter((r) => !r.ok).map((r) => r.melding) ?? []
      return [d.message, ...rood].filter(Boolean).join(' — ')
    }
  }
  return `Boeken mislukt (HTTP ${status})`
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
  const [boekenBezig, setBoekenBezig] = useState(false)
  const [boekenFout, setBoekenFout] = useState<string | null>(null)

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

  /** Bugfix-run 28-08: alle lagen akkoord maar het boeken ná het laatste akkoord faalde (of het
   * document hing nog op de oude stille terugval) — het kantoor boekt opnieuw via de gewone
   * boek-route; de server-poort laat dat toe omdat de laatste ronde afgerond is. */
  const opnieuwBoeken = async () => {
    setBoekenBezig(true)
    setBoekenFout(null)
    try {
      const resp = await apiFetch(`/administraties/${administratieId}/documenten/${documentId}/boeken`, { method: 'POST' })
      if (!resp.ok) {
        const body: unknown = await resp.json().catch(() => null)
        setBoekenFout(foutTekst(body, resp.status))
        onGewijzigd()
        return
      }
      onGewijzigd()
    } catch (err) {
      setBoekenFout(err instanceof Error ? err.message : 'Boeken mislukt')
    } finally {
      setBoekenBezig(false)
    }
  }

  if (accordering === null) return null

  // Zelfde statussen als de herstelroute (app/accordering/herstel.py::HERSTELBARE_STATUSSEN):
  // vraag_open ná akkoord (boeken wacht op de open vraag) en de tegenboek-herboeking vallen er
  // bewust buiten — daar is niets "mislukt".
  const akkoordMaarNietGeboekt =
    accordering.status === 'afgerond' && ['ter_accordering', 'klaar_om_te_boeken', 'boeken_mislukt'].includes(documentStatus)
  const terughaalbaar = accordering.status === 'open' || (akkoordMaarNietGeboekt && documentStatus === 'ter_accordering')

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
        ) : accordering.status === 'vervallen' ? (
          <span className="chip vraag">vervallen</span>
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
      {akkoordMaarNietGeboekt && (
        <div className="fout" role="alert" style={{ marginTop: 8 }}>
          <b>Boeken ná het laatste akkoord is niet gelukt</b>
          {accordering.boek_fout ? (
            <>
              {' — '}
              {accordering.boek_fout}
              {accordering.boek_fout_op && (
                <span style={{ color: 'var(--muted)' }}> ({formatTijdstip(accordering.boek_fout_op)})</span>
              )}
            </>
          ) : (
            ' — het document staat nog niet geboekt (zie de tijdlijn voor de reden).'
          )}
          <div className="hint" style={{ marginTop: 4 }}>
            Los de oorzaak op en boek opnieuw — het klant-akkoord blijft geldig zolang het bedrag ongewijzigd is.
            Voorstel aanpassen? Haal het document dan terug uit de accordering en bied het opnieuw aan.
          </div>
          {boekenFout && (
            <div className="hint" style={{ marginTop: 4, color: 'var(--red)' }}>
              {boekenFout}
            </div>
          )}
          <div className="actions" style={{ marginTop: 6 }}>
            <button type="button" className="btn primary" disabled={boekenBezig} onClick={() => void opnieuwBoeken()}>
              {boekenBezig ? 'Bezig…' : 'Opnieuw boeken (klant-akkoord compleet)'}
            </button>
          </div>
        </div>
      )}
      {terughaalbaar && (
        <div className="actions">
          {/* Dagrem gespiegeld (max 1 per document per dag, Europe/Amsterdam): vandaag al
              verzonden = knop disabled mét tijdstip i.p.v. fout-ná-klik. Een mislukte
              poging zit niet in laatst_herinnerd → knop blijft actief (herkansing). */}
          {accordering.status === 'open' && (
            <button
              type="button"
              className="btn secondary"
              disabled={herinnerBezig || isVandaagHerinnerd(laatstHerinnerd)}
              onClick={() => void herinneren()}
            >
              {herinnerBezig
                ? 'Bezig…'
                : isVandaagHerinnerd(laatstHerinnerd) && laatstHerinnerd
                  ? `Vandaag al herinnerd om ${herinnerTijdLabel(laatstHerinnerd)}`
                  : 'Herinner accordeur'}
            </button>
          )}
          <button type="button" className="btn secondary" disabled={bezig} onClick={() => void intrekken()}>
            {bezig ? 'Bezig…' : 'Terughalen uit accordering'}
          </button>
        </div>
      )}
    </div>
  )
}
