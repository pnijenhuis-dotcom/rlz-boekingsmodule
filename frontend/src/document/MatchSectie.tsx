/** Match-sectie controlescherm (factuurmatch fase 3, BESLISSINGEN "FACTUURMATCH
 * ZZP-/BUREAUFACTUREN"): chip per uitkomst, verschil-per-week-uitsplitsing uit de opgeslagen
 * match-details, periode-keuze/herberekenen mét expliciete weekstaat-selectie (endpoint
 * valideert hard) en de concept-mail bij een afwijking (MatchMailPaneel). De sectie is een
 * signaal bovenop de normale flow (besluit 3 — geen status); boeken-ondanks-afwijking loopt
 * via de bevestigings-pop-up in het boekvoorstel (MatchAfwijkingPopup). */
import { useEffect, useState } from 'react'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type { FactuurmatchDto } from '../api/types'
import { formatBedrag } from '../werkvoorraad/format'
import { MatchMailPaneel } from './MatchMailPaneel'

interface KandidaatStaatDto {
  weekstaat_id: string
  gebruiker_id: string
  gebruiker_naam: string | null
  project_naam: string | null
  jaar: number
  weeknummer: number
  uren: string
  in_match: boolean
}

interface DetailsStaat {
  weekstaat_id: string
  gebruiker_id: string
  project_naam: string | null
  jaar: number
  weeknummer: number
  uren: string
}

interface DetailsLid {
  gebruiker_id: string
  naam: string | null
  uren: string
  uurtarief: string | null
  bedrag: string | null
}

function uitkomstChip(match: FactuurmatchDto): { klasse: string; label: string } {
  switch (match.uitkomst) {
    case 'match':
      return { klasse: 'ok', label: 'match — uren en bedrag sluiten' }
    case 'match_alleen_uren':
      return { klasse: 'geheugen', label: 'alleen uren getoetst — geen tarief bekend' }
    case 'afwijking':
      return { klasse: 'vraag', label: 'wijkt af — bevestiging vereist bij boeken' }
    default:
      return { klasse: 'geheugen', label: 'niet toetsbaar' }
  }
}

function uren(waarde: string): string {
  return `${Number(waarde).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} u`
}

export function MatchSectie({
  administratieId,
  documentId,
  match,
  onGewijzigd,
}: {
  administratieId: string
  documentId: string
  match: FactuurmatchDto
  onGewijzigd: () => void
}) {
  const [periodeOpen, setPeriodeOpen] = useState(false)
  const chip = uitkomstChip(match)
  const staten = ((match.details?.staten as DetailsStaat[] | undefined) ?? []).slice()
  const leden = (match.details?.leden as DetailsLid[] | undefined) ?? []
  const meerdereLeden = leden.length > 1

  return (
    <div className="panel">
      <h2>
        Urenmatch <span className={`chip ${chip.klasse}`}>{chip.label}</span>
      </h2>
      <p className="hint" style={{ marginTop: 0 }}>
        {match.veldwerker_naam && (
          <>
            Veldwerker: <b>{match.veldwerker_naam}</b> ·{' '}
          </>
        )}
        weekstaten {uren(match.staten_som_uren)}
        {match.staten_som_bedrag && ` (${formatBedrag(match.staten_som_bedrag)})`} · factuur{' '}
        {match.factuur_bedrag ? formatBedrag(match.factuur_bedrag) : 'bedrag onbekend'}
        {match.verschil_bedrag && (
          <>
            {' '}
            · verschil <b>{formatBedrag(match.verschil_bedrag)}</b>
          </>
        )}
        {match.verschil_uren && (
          <>
            {' '}
            · verschil uren <b>{uren(match.verschil_uren)}</b>
          </>
        )}
        {match.afwijking_bevestigd && (
          <>
            {' '}
            · <span className="chip geheugen">afwijking bevestigd</span>
          </>
        )}
      </p>

      {meerdereLeden && (
        <table style={{ marginBottom: 8 }}>
          <tbody>
            <tr>
              <th>ZZP'er (bureau-tarief)</th>
              <th>Uren</th>
              <th>Tarief</th>
              <th>Bedrag</th>
            </tr>
            {leden.map((lid) => (
              <tr key={lid.gebruiker_id}>
                <td>{lid.naam ?? lid.gebruiker_id}</td>
                <td>{uren(lid.uren)}</td>
                <td>{lid.uurtarief ? formatBedrag(lid.uurtarief) : 'geen tarief'}</td>
                <td>{lid.bedrag ? formatBedrag(lid.bedrag) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {staten.length > 0 && (
        <table style={{ marginBottom: 8 }}>
          <tbody>
            <tr>
              <th>Week</th>
              {meerdereLeden && <th>ZZP'er</th>}
              <th>Project</th>
              <th>Goedgekeurde uren</th>
            </tr>
            {staten
              .sort((a, b) => a.jaar - b.jaar || a.weeknummer - b.weeknummer)
              .map((s) => (
                <tr key={s.weekstaat_id}>
                  <td>
                    wk {s.weeknummer} · {s.jaar}
                  </td>
                  {meerdereLeden && <td>{leden.find((l) => l.gebruiker_id === s.gebruiker_id)?.naam ?? '—'}</td>}
                  <td>{s.project_naam ?? '—'}</td>
                  <td>{uren(s.uren)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
      {staten.length === 0 && (
        <p className="hint">Geen goedgekeurde weekstaten in deze berekening — de toetsbron is leeg.</p>
      )}

      <div className="actions" style={{ marginBottom: 4 }}>
        <button className="btn secondary" onClick={() => setPeriodeOpen(true)}>
          Periode kiezen / herberekenen…
        </button>
      </div>

      {match.uitkomst === 'afwijking' && (
        <MatchMailPaneel administratieId={administratieId} documentId={documentId} onVerzonden={onGewijzigd} />
      )}

      {periodeOpen && (
        <PeriodeKeuzeModal
          administratieId={administratieId}
          documentId={documentId}
          factuurUren={match.factuur_uren}
          onSluiten={() => setPeriodeOpen(false)}
          onHerberekend={() => {
            setPeriodeOpen(false)
            onGewijzigd()
          }}
        />
      )}
    </div>
  )
}

/** Periode-keuze (fase 3): expliciete weekstaat-selectie + optionele mens-opgave van de
 * factuur-uren. NB een herberekening wist een eerdere "boeken ondanks afwijking"-bevestiging
 * (nieuwe cijfers = nieuwe beslissing) — dat staat er expliciet bij. */
function PeriodeKeuzeModal({
  administratieId,
  documentId,
  factuurUren,
  onSluiten,
  onHerberekend,
}: {
  administratieId: string
  documentId: string
  factuurUren: string | null
  onSluiten: () => void
  onHerberekend: () => void
}) {
  const [kandidaten, setKandidaten] = useState<KandidaatStaatDto[] | null>(null)
  const [selectie, setSelectie] = useState<Set<string>>(new Set())
  const [urenInvoer, setUrenInvoer] = useState(factuurUren ?? '')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    apiJson<{ staten: KandidaatStaatDto[] }>(
      `/administraties/${administratieId}/documenten/${documentId}/factuurmatch/kandidaat-staten`,
    )
      .then((data) => {
        setKandidaten(data.staten)
        setSelectie(new Set(data.staten.filter((s) => s.in_match).map((s) => s.weekstaat_id)))
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Weekstaten laden mislukt'))
  }, [administratieId, documentId])

  function wissel(id: string) {
    setSelectie((huidig) => {
      const nieuw = new Set(huidig)
      if (nieuw.has(id)) nieuw.delete(id)
      else nieuw.add(id)
      return nieuw
    })
  }

  async function herbereken() {
    setBezig(true)
    setFout(null)
    try {
      await apiPostJson(`/administraties/${administratieId}/documenten/${documentId}/factuurmatch/herbereken`, {
        weekstaat_ids: [...selectie],
        factuur_uren: urenInvoer.trim() === '' ? null : urenInvoer.replace(',', '.'),
      })
      onHerberekend()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Herberekenen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div className="modal-bg" role="presentation" onClick={() => !bezig && onSluiten()}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Periode kiezen"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ marginTop: 0 }}>Periode kiezen — welke getekende weekstaten tellen mee?</h2>
        <p className="hint">
          Alleen goedgekeurde, onverrekende weekstaten zijn selecteerbaar. Herberekenen wist een eerdere
          "boeken ondanks afwijking"-bevestiging — nieuwe cijfers, nieuwe beslissing.
        </p>
        {fout && <div className="fout">{fout}</div>}
        {kandidaten === null && !fout && <p className="hint">Weekstaten laden…</p>}
        {kandidaten !== null && kandidaten.length === 0 && (
          <p className="hint">Geen selecteerbare weekstaten — er is nog niets goedgekeurd (of alles is verrekend).</p>
        )}
        {kandidaten !== null && kandidaten.length > 0 && (
          <div style={{ maxHeight: 280, overflowY: 'auto', margin: '8px 0' }}>
            {kandidaten.map((s) => (
              <label key={s.weekstaat_id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0' }}>
                <input
                  type="checkbox"
                  checked={selectie.has(s.weekstaat_id)}
                  onChange={() => wissel(s.weekstaat_id)}
                />
                <span>
                  wk {s.weeknummer} · {s.jaar}
                  {s.gebruiker_naam ? ` · ${s.gebruiker_naam}` : ''}
                  {s.project_naam ? ` · ${s.project_naam}` : ''} — {uren(s.uren)}
                </span>
              </label>
            ))}
          </div>
        )}
        <label style={{ display: 'block', margin: '8px 0' }}>
          <span className="hint">Factuur-uren (optioneel — overschrijft de uren uit de extractie)</span>
          <input
            type="number"
            inputMode="decimal"
            min="0"
            step="0.25"
            placeholder="bijv. 32"
            value={urenInvoer}
            onChange={(e) => setUrenInvoer(e.target.value)}
          />
        </label>
        <div className="actions">
          <button className="btn secondary" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </button>
          <button className="btn" onClick={() => void herbereken()} disabled={bezig || kandidaten === null}>
            {bezig ? 'Bezig…' : 'Herbereken match'}
          </button>
        </div>
      </div>
    </div>
  )
}
