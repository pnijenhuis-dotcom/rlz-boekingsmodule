// Kantoor-weekstaat (feedback uitvoerder via Peter 18-09, blok B): de weekstaat die het planning-grid al opende via
// `/meerwerk?administratie=…&weekstaat=<id>` (15-09, bestaande kantoor-leesroute `GET /uren/kantoor/weekstaten/…`)
// krijgt hier een leesbaar paneel mét de doorfactureren-keuze per regel, het filter "alleen niet doorfactureren" en de
// chips "niet gepland" (buiten planning) — informatief, het kantoor keurt niet vanaf hier (keuring = uitvoerder, app).
// Regels "Niet doorfactureren" tellen niet mee in wat aan de klant doorbelast mag worden: de balk toont beide totalen.
import { useCallback, useEffect, useState } from 'react'
import { apiJson } from '../api/client'
import { Badge } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'

interface KantoorDagDto {
  datum: string
  uren: string
  m2: string | null
  opmerking: string | null
  ingevuld_door_naam: string | null
  namens: boolean
  buiten_planning: boolean
  doorfactureren?: boolean
}

export interface KantoorWeekstaatDto {
  id: string
  gebruiker_naam: string | null
  project_naam: string | null
  jaar: number
  weeknummer: number
  status: 'concept' | 'ingediend' | 'goedgekeurd' | 'corrigeren'
  totaal_uren: string
  totaal_m2: string
  totaal_uren_niet_doorfactureren?: string
  totaal_m2_niet_doorfactureren?: string
  dagen_buiten_planning?: number
  doorfactureren_standaard?: boolean
  dagen: KantoorDagDto[]
}

const STATUS_LABEL: Record<KantoorWeekstaatDto['status'], string> = {
  concept: 'concept',
  ingediend: 'ingediend — wacht op keuring',
  goedgekeurd: 'goedgekeurd (getekende urenstaat)',
  corrigeren: 'afgekeurd — corrigeren',
}

function getal(waarde: string | null | undefined, eenheid: string): string {
  if (waarde === null || waarde === undefined) return '—'
  return `${Number(waarde).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} ${eenheid}`
}

function dagLabel(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('nl-NL', { weekday: 'short', day: 'numeric', month: 'short' })
}

/** Uren die aan de klant doorbelast mogen worden = totaal − "niet doorfactureren". */
export function doorTeBelasten(totaal: string, nietDoorfactureren: string | undefined): string {
  return (Number(totaal) - Number(nietDoorfactureren ?? '0')).toString()
}

export function WeekstaatPaneel({ administratieId, weekstaatId }: { administratieId: string; weekstaatId: string }) {
  const [staat, setStaat] = useState<KantoorWeekstaatDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [alleenNiet, setAlleenNiet] = useState(false)

  const laad = useCallback(() => {
    setFout(null)
    apiJson<KantoorWeekstaatDto>(`/uren/kantoor/weekstaten/${administratieId}/${weekstaatId}`)
      .then(setStaat)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, weekstaatId])
  useEffect(() => {
    laad()
  }, [laad])

  if (fout) return <FoutMelding melding="De weekstaat kon niet geladen worden." detail={fout} onOpnieuw={laad} />
  if (staat === null) return <p className="hint">Weekstaat laden…</p>

  const dagen = staat.dagen.filter((d) => !alleenNiet || d.doorfactureren === false)
  const nietUren = staat.totaal_uren_niet_doorfactureren ?? '0'
  const heeftNiet = Number(nietUren) > 0

  return (
    <div className="panel" data-testid="weekstaat-paneel">
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
        <h2 style={{ margin: 0, fontSize: 15 }}>
          Weekstaat {staat.gebruiker_naam ?? 'veldwerker'} · week {staat.weeknummer} · {staat.project_naam ?? 'project'}
        </h2>
        <Badge variant={staat.status === 'goedgekeurd' ? 'ok' : staat.status === 'corrigeren' ? 'danger' : 'stil'}>
          {STATUS_LABEL[staat.status]}
        </Badge>
        {(staat.dagen_buiten_planning ?? 0) > 0 && (
          <Badge variant="warn">{staat.dagen_buiten_planning} dag(en) niet gepland</Badge>
        )}
        <label style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 12.5 }}>
          <input type="checkbox" checked={alleenNiet} onChange={(e) => setAlleenNiet(e.target.checked)} />
          alleen "niet doorfactureren"
        </label>
      </div>
      <table className="tabel" style={{ width: '100%' }}>
        <thead>
          <tr>
            <th>Dag</th>
            <th>Uren</th>
            <th>m²</th>
            <th>Doorfactureren</th>
            <th>Planning</th>
            <th>Opmerking</th>
          </tr>
        </thead>
        <tbody>
          {dagen.length === 0 && (
            <tr>
              <td colSpan={6} className="hint">
                {alleenNiet ? 'Geen regels "niet doorfactureren" in deze week.' : 'Nog geen dagen ingevuld.'}
              </td>
            </tr>
          )}
          {dagen.map((d) => (
            <tr key={d.datum} data-testid={`weekstaat-dag-${d.datum}`}>
              <td>{dagLabel(d.datum)}</td>
              <td>{getal(d.uren, 'u')}</td>
              <td>{getal(d.m2, 'm²')}</td>
              <td>
                {d.doorfactureren === false ? <Badge variant="warn">niet doorfactureren</Badge> : <Badge variant="stil">doorfactureren</Badge>}
              </td>
              <td>{d.buiten_planning ? <Badge variant="warn">niet gepland</Badge> : 'gepland'}</td>
              <td>
                {d.opmerking ?? '—'}
                {d.namens && d.ingevuld_door_naam ? ` · ingevuld door ${d.ingevuld_door_naam} (namens)` : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 8, fontSize: 12.5 }}>
        <span>
          <b>Totaal</b> {getal(staat.totaal_uren, 'u')} · {getal(staat.totaal_m2, 'm²')}
        </span>
        <span data-testid="door-te-belasten">
          <b>Door te belasten</b> {getal(doorTeBelasten(staat.totaal_uren, staat.totaal_uren_niet_doorfactureren), 'u')}
          {heeftNiet ? ` (niet doorfactureren: ${getal(nietUren, 'u')} · ${getal(staat.totaal_m2_niet_doorfactureren ?? '0', 'm²')})` : ''}
        </span>
        <span style={{ color: 'var(--muted)' }}>
          standaard voor dit project: {staat.doorfactureren_standaard === false ? 'niet doorfactureren' : 'doorfactureren'}
        </span>
      </div>
    </div>
  )
}
