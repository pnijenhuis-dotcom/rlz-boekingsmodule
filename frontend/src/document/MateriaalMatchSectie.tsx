import { useState } from 'react'
import { ApiError } from '../api/client'
import { herberekenMateriaalmatch, type MateriaalmatchDto } from '../planning/transportApi'

/* Materiaalcontrole-sectie controlescherm (steigerbouw-run D6, besluit Peter 24-08 — model
 * aantal × huurperiode per item; mockup planning-steigerbouw zijbalk "Factuurcontrole materiaal"):
 * chip per uitkomst, regels met verwacht aantal / item-weken uit de geregistreerde leveringen,
 * herberekenen. Signaal bovenop de normale flow (vlag-patroon, geen status); boeken-ondanks-
 * afwijking loopt via MateriaalAfwijkingPopup in het boekvoorstel. */
function chip(m: MateriaalmatchDto): { klasse: string; label: string } {
  switch (m.uitkomst) {
    case 'match':
      return { klasse: 'ok', label: 'match — factuurregels sluiten op de leveringen' }
    case 'afwijking':
      return { klasse: 'vraag', label: 'wijkt af — bevestiging vereist bij boeken' }
    default:
      return { klasse: 'geheugen', label: 'niet toetsbaar' }
  }
}

function statusLabel(s: string): string {
  switch (s) {
    case 'match_aantal':
      return 'klopt (aantal)'
    case 'match_huur_eenheden':
      return 'klopt (item-weken)'
    case 'afwijking':
      return 'wijkt af'
    case 'onbekend':
      return 'niet herkend'
    case 'geen_hoeveelheid':
      return 'geen hoeveelheid'
    default:
      return s
  }
}

export function MateriaalMatchSectie({ administratieId, documentId, match, onGewijzigd }: { administratieId: string; documentId: string; match: MateriaalmatchDto; onGewijzigd: () => void }) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const c = chip(match)
  const regels = match.details?.regels ?? []
  return (
    <div className="panel">
      <h2>
        Materiaalcontrole <span className={`chip ${c.klasse}`}>{c.label}</span>
      </h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Verhuur-crediteur <b>{match.leverancier_naam ?? '?'}</b>
        {match.project_naam ? <> · project <b>{match.project_naam}</b></> : ' · project onbekend'} · {match.aantal_regels_getoetst} regel(s) getoetst
        {match.aantal_regels_afwijkend > 0 && <> · <b>{match.aantal_regels_afwijkend} afwijkend</b></>}
        {match.aantal_regels_onbekend > 0 && <> · {match.aantal_regels_onbekend} niet herkend</>}
        {match.details?.m2_op_locatie && <> · geleverd op locatie {Number(match.details.m2_op_locatie).toLocaleString('nl-NL')} m²</>}
        {match.afwijking_bevestigd && (
          <>
            {' '}
            · <span className="chip geheugen">afwijking bevestigd</span>
          </>
        )}
      </p>
      {match.details?.reden && <p className="hint">{match.details.reden}</p>}
      {regels.length > 0 && (
        <table style={{ marginBottom: 8 }}>
          <tbody>
            <tr>
              <th>Factuurregel</th>
              <th>Product</th>
              <th>Hoeveelheid</th>
              <th>Verwacht aantal</th>
              <th>Verwacht item-weken</th>
              <th>Status</th>
            </tr>
            {regels.map((r, i) => (
              <tr key={i}>
                <td>{r.omschrijving}</td>
                <td>{r.product_naam ?? '—'}</td>
                <td>{r.hoeveelheid ?? '—'}</td>
                <td>{r.verwacht_aantal ?? '—'}</td>
                <td>
                  {r.verwacht_huur_eenheden ?? '—'}
                  {r.huurdagen !== undefined && r.huurdagen > 0 && <span className="hint"> ({r.huurdagen} d)</span>}
                </td>
                <td>
                  <span className={`chip ${r.status === 'afwijking' ? 'vraag' : r.status.startsWith('match') ? 'ok' : 'geheugen'}`}>{statusLabel(r.status)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {fout && <div className="fout">{fout}</div>}
      <div className="actions" style={{ marginBottom: 4 }}>
        <button
          className="btn secondary"
          disabled={bezig}
          onClick={() => {
            setBezig(true)
            setFout(null)
            herberekenMateriaalmatch(administratieId, documentId)
              .then(() => onGewijzigd())
              .catch((err: unknown) => setFout(err instanceof ApiError ? err.message : 'Herberekenen mislukt.'))
              .finally(() => setBezig(false))
          }}
        >
          {bezig ? 'Bezig…' : 'Herberekenen'}
        </button>
        <span className="hint" style={{ alignSelf: 'center' }}>
          berekend {new Date(match.berekend_op).toLocaleString('nl-NL')} — model: aantal × huurperiode per item (besluit 24-08)
        </span>
      </div>
    </div>
  )
}
