// Punt 12 run A (Peter 02-10: "als ik dan op projectniveau ben wil ik daar ook alle meerwerk statussen (def en concept)
// kunnen zien"): blok "Meerwerk" op de projectpagina — ÁLLE meldingen van dit project mét status, uit DEZELFDE route en
// statusdefinitie als Beoordelen › Meerwerk (`GET /uren/kantoor/meerwerk?project_id=`), nieuwste bovenaan (server-
// volgorde), klik = de meerwerkbon (punt 10). Zonder module-recht toont het blok dat eerlijk (403 → één zin), nooit een
// valse lege lijst. Presentatie only; tabel in .tabel-scroll (overflow-les 18-09).
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import { eenheidLabel, haalMeerwerkLijst, type MeerwerkDto } from '../meerwerk/meerwerkApi'
import { MEERWERK_STATUS_LABEL, MEERWERK_STATUS_VOLGORDE, meerwerkStatusBadge } from '../meerwerk/meerwerkStatus'
import { Badge } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { meerwerkBonPad } from './projectPad'

function ddmmyyyy(iso: string): string {
  return new Date(`${iso.slice(0, 10)}T12:00:00Z`).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

export function ProjectMeerwerkPaneel({ administratieId, projectId }: { administratieId: string; projectId: string }) {
  const [items, setItems] = useState<MeerwerkDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [geenRecht, setGeenRecht] = useState(false)

  const laad = useCallback(() => {
    setFout(null)
    setGeenRecht(false)
    haalMeerwerkLijst(administratieId, projectId)
      .then(setItems)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) setGeenRecht(true)
        else setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
  }, [administratieId, projectId])

  useEffect(() => {
    setItems(null)
    laad()
  }, [laad])

  const tellers = new Map<string, number>()
  for (const i of items ?? []) tellers.set(i.status, (tellers.get(i.status) ?? 0) + 1)

  return (
    <div className="panel" data-testid="meerwerk-paneel">
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        Meerwerk{items !== null ? ` (${items.length})` : ''}
        {MEERWERK_STATUS_VOLGORDE.filter((s) => (tellers.get(s) ?? 0) > 0).map((s) => (
          <Badge key={s} variant="stil" data-testid={`meerwerk-teller-${s}`}>
            {tellers.get(s)} {MEERWERK_STATUS_LABEL[s]}
          </Badge>
        ))}
      </h2>
      {geenRecht && (
        <p className="hint" style={{ margin: 0 }} data-testid="meerwerk-geen-recht">
          Meerwerk vereist het module-recht "Meerwerk &amp; urenstaten" — een Beheerder kent dit toe onder Gebruikers &amp; toegang.
        </p>
      )}
      {fout && <FoutMelding melding="Het meerwerk van dit project kon niet geladen worden." detail={fout} onOpnieuw={laad} />}
      {items === null && !fout && !geenRecht && (
        <div aria-busy="true">
          <span className="skeleton" style={{ width: '55%', marginBottom: 8 }} />
          <span className="skeleton" style={{ width: '40%' }} />
        </div>
      )}
      {items !== null && items.length === 0 && (
        <p className="hint" style={{ margin: 0 }} data-testid="meerwerk-leeg">
          Nog geen meerwerk gemeld op dit project. De uitvoerder meldt meerwerk vanaf de projectkaart in de app; het kantoor
          beoordeelt op{' '}
          <Link to={`/meerwerk?administratie=${administratieId}&tab=meerwerk`} className="text-primary">
            Beoordelen › Meerwerk →
          </Link>
        </p>
      )}
      {items !== null && items.length > 0 && (
        <div className="tabel-scroll">
          <table data-testid="meerwerk-tabel">
            <tbody>
              <tr>
                <th>Gemeld</th>
                <th>Omschrijving</th>
                <th>Aantal</th>
                <th>Gemeld door</th>
                <th>Status</th>
                <th />
              </tr>
              {items.map((item) => (
                <tr key={item.id} data-testid={`meerwerk-rij-${item.id}`}>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {ddmmyyyy(item.gemeld_op)}
                    <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>uitgevoerd {ddmmyyyy(item.datum_uitgevoerd)}</div>
                  </td>
                  {/* Omschrijving altijd voluit (mockup-norm meerwerk-kantoor): regelterugloop, nooit "…" */}
                  <td style={{ maxWidth: 380, whiteSpace: 'normal' }}>
                    {item.omschrijving}
                    {item.heeft_foto && <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>foto ✓</div>}
                    {item.afwijs_reden && <div style={{ fontSize: 11.5, color: 'var(--danger)' }}>reden: {item.afwijs_reden}</div>}
                  </td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {item.aantal} {eenheidLabel(item.eenheid)}
                  </td>
                  <td>{item.gemeld_door_naam ?? '—'}</td>
                  <td>{meerwerkStatusBadge(item)}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <Link to={meerwerkBonPad(administratieId, item.id)} className="linkbtn" data-testid={`meerwerk-bon-${item.id}`}>
                      Bon openen →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
