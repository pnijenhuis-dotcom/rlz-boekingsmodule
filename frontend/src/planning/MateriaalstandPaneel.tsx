import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { Badge, SkeletonRegels } from '../ui/basis'
import { haalMateriaalstand, type MateriaalStandDto } from './transportApi'

/* Materiaalstand per project (steigerbouw-run D4, mockup planning-steigerbouw zijbalk "📦 Materiaal
 * op locatie"): som leveringen − retouren per materiaalsoort over álle leveranciers, huurperiode per
 * item (start = geleverd, eind = retour), m² op locatie. Zichtbaar in de transport-zijbalk én op het
 * projectdetail. Alleen status 'geleverd' telt. */
export function MateriaalstandPaneel({ administratieId, projectId, compact = false }: { administratieId: string; projectId: string; compact?: boolean }) {
  const [stand, setStand] = useState<MateriaalStandDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  useEffect(() => {
    let actief = true
    haalMateriaalstand(administratieId, projectId)
      .then((s) => actief && setStand(s))
      .catch((err: unknown) => {
        // 403/409 = geen module-recht of geen opt-in → paneel bestaat niet (toon-regel).
        if (actief) setFout(err instanceof ApiError && (err.status === 403 || err.status === 409) ? '' : err instanceof Error ? err.message : 'Laden mislukt')
      })
    return () => {
      actief = false
    }
  }, [administratieId, projectId])
  if (fout === '') return null
  return (
    <div className="panel">
      <h2 style={compact ? { margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' } : undefined}>
        📦 Materiaal op locatie{stand?.project_naam && compact ? ` — ${stand.project_naam}` : ''}
        {stand && Number(stand.m2_op_locatie) > 0 && (
          <>
            {' '}
            <Badge variant="info">{Number(stand.m2_op_locatie).toLocaleString('nl-NL')} m²</Badge>
          </>
        )}
      </h2>
      {fout && <div className="fout">{fout}</div>}
      {stand === null && !fout && <SkeletonRegels />}
      {stand !== null && stand.regels.length === 0 && <p className="hint">Nog geen geleverd materiaal geregistreerd op dit project (Transport-tab → status geleverd).</p>}
      {stand !== null && stand.regels.length > 0 && (
        <div className="tabel-scroll">
          <table>
            <thead>
              <tr>
                <th>Materiaal</th>
                <th className="amount">Op locatie</th>
                <th className="amount">Geleverd / retour</th>
                <th>Huurperiode</th>
                {!compact && <th>Leverancier(s)</th>}
              </tr>
            </thead>
            <tbody>
              {stand.regels.map((r) => (
                <tr key={r.product_id}>
                  <td>
                    <b>{r.naam}</b>
                    <div className="hint" style={{ fontSize: 11 }}>{r.categorie}</div>
                  </td>
                  <td className="amount">
                    {r.op_locatie} {r.eenheid}
                    {Number(r.m2) > 0 && <div className="hint" style={{ fontSize: 11 }}>{Number(r.m2).toLocaleString('nl-NL')} m²</div>}
                  </td>
                  <td className="amount">
                    {r.geleverd} / {r.retour}
                  </td>
                  <td>
                    {r.eerste_levering ? new Date(r.eerste_levering).toLocaleDateString('nl-NL') : '—'} →{' '}
                    {r.laatste_retour ? new Date(r.laatste_retour).toLocaleDateString('nl-NL') : 'loopt'}
                    <div className="hint" style={{ fontSize: 11 }}>
                      {r.huurdagen_tot_vandaag} dagen · {Number(r.huur_eenheden).toLocaleString('nl-NL')} item-weken
                    </div>
                  </td>
                  {!compact && <td>{r.leveranciers.join(', ')}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {stand !== null && stand.regels.length > 0 && (
        <p className="hint" style={{ marginBottom: 0 }}>
          Stand = som leveringen − retouren over álle leveranciers ({stand.leveranciers.join(', ')}) · huurperiode loopt per item · m² =
          Σ(aantal × lengte) / 4,6.
        </p>
      )}
    </div>
  )
}
