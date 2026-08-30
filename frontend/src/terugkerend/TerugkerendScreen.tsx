// Terugkerende facturen — signaal-overzicht per administratie (blok B 30-08, benchmark-besluit Peter 29-08).
// Deterministisch uit de historie: een leverancier is terugkerend bij ≥ 3 facturen met een regelmatig
// interval (maand/kwartaal, ±35 %). Signaal 1 "verwachte factuur ontbreekt" (oranje, geen blokkade,
// verdwijnt vanzelf bij de volgende factuur; snooze/afmelden per leverancier), signaal 2 "prijsstijging"
// boven de drempel (chip op het controlescherm + hier). Alleen signaleren — nooit boeken of muteren.
import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import { Badge, Button, SkeletonRegels } from '../ui/basis'
import { formatBedrag, formatDatumKort } from '../werkvoorraad/format'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  haalTerugkerendOverzicht,
  herberekenTerugkerend,
  patroonLabel,
  snoozeTerugkerend,
  STATUS_LABEL,
  zetTerugkerendAfgemeld,
  zetTerugkerendDrempel,
  type TerugkerendOverzichtDto,
  type TerugkerendSignaalDto,
} from './terugkerendApi'

function plusDagen(dagen: number): string {
  const d = new Date()
  d.setDate(d.getDate() + dagen)
  return d.toISOString().slice(0, 10)
}

export function TerugkerendScreen() {
  const { rol } = useAuth()
  const { administraties } = useAdministraties()
  const [zoekParams, setZoekParams] = useSearchParams()
  const administratieId = zoekParams.get('administratie') ?? ''
  const [data, setData] = useState<TerugkerendOverzichtDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [melding, setMelding] = useState<string | null>(null)
  const [laden, setLaden] = useState(false)
  const [drempel, setDrempel] = useState('')
  const [toonAlles, setToonAlles] = useState(false)

  const laad = useCallback(() => {
    if (!administratieId) return
    setLaden(true)
    setFout(null)
    haalTerugkerendOverzicht(administratieId)
      .then((d) => {
        setData(d)
        setDrempel(d.prijsstijging_drempel_pct)
      })
      .catch((err: unknown) => {
        setData(null)
        setFout(err instanceof Error ? err.message : 'Laden mislukt.')
      })
      .finally(() => setLaden(false))
  }, [administratieId])

  useEffect(() => {
    laad()
  }, [laad])

  const kies = (id: string) => {
    const p = new URLSearchParams(zoekParams)
    p.set('administratie', id)
    setZoekParams(p, { replace: true })
  }

  const actie = async (werk: () => Promise<unknown>, tekst: string) => {
    setMelding(null)
    try {
      await werk()
      setMelding(tekst)
      laad()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Actie mislukt.')
    }
  }

  const herbereken = () =>
    actie(async () => {
      const r = await herberekenTerugkerend(administratieId)
      setMelding(`Herberekend: ${r.terugkerend} terugkerende leveranciers, ${r.ontbreekt} ontbrekend, ${r.prijsstijging} prijsstijging.`)
    }, 'Herberekend.')

  const drempelOpslaan = () => {
    const w = drempel.trim().replace(',', '.')
    const n = Number(w)
    if (w === '' || Number.isNaN(n) || n <= 0 || n > 1000) {
      setFout('Drempel moet een percentage boven 0 zijn.')
      return
    }
    void actie(() => zetTerugkerendDrempel(administratieId, w), `Drempel prijsstijging gezet op ${w}%.`)
  }

  const zichtbaar = (data?.signalen ?? []).filter((s) => toonAlles || s.status !== 'op_schema' || s.prijsstijging_pct !== null)
  const verborgen = (data?.signalen.length ?? 0) - zichtbaar.length

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Terugkerende facturen</h1>
          <div className="hint" style={{ marginTop: 2 }}>
            Leveranciers met een regelmatig factuurritme (≥ 3 facturen, maand of kwartaal, ±35 %). Signaal als de verwachte
            factuur uitblijft of de prijs stijgt — puur code, nooit een blokkade.
          </div>
        </div>
      </div>

      <div className="panel" style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div style={{ minWidth: 280 }}>
          <AdministratieCombobox
            label="Administratie"
            administraties={administraties ?? []}
            waarde={administratieId || null}
            onWijzig={kies}
            placeholder="— kies administratie —"
          />
        </div>
        <Button variant="secundair" maat="klein" disabled={!administratieId || laden} onClick={() => void herbereken()}>
          ⟳ Herberekenen
        </Button>
        {rol === 'beheerder' && data && (
          <label style={{ margin: 0, fontSize: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
            Drempel prijsstijging (%)
            <input inputMode="decimal" value={drempel} onChange={(e) => setDrempel(e.target.value)} aria-label="Drempel prijsstijging" style={{ width: 70 }} />
            <Button variant="ghost" maat="klein" onClick={drempelOpslaan}>
              Opslaan
            </Button>
          </label>
        )}
      </div>

      {fout && <FoutMelding melding="Er ging iets mis." detail={fout} onOpnieuw={laad} />}
      {melding && (
        <div className="hint" role="status" style={{ marginBottom: 10 }}>
          {melding}
        </div>
      )}
      {!administratieId && <p className="hint">Kies een administratie.</p>}
      {administratieId && laden && data === null && <SkeletonRegels />}

      {data !== null && (
        <div className="panel">
          {data.signalen.length === 0 && <p className="hint">Nog geen terugkerende leveranciers herkend (minimaal 3 facturen met een regelmatig interval).</p>}
          {data.signalen.length > 0 && (
            <>
              <div className="tabel-scroll">
                <table data-testid="terugkerend-tabel">
                  <thead>
                    <tr>
                      <th>Leverancier</th>
                      <th>Ritme</th>
                      <th>Laatste factuur</th>
                      <th>Verwacht</th>
                      <th>Signaal</th>
                      <th>Prijs</th>
                      <th className="acties" />
                    </tr>
                  </thead>
                  <tbody>
                    {zichtbaar.map((s) => (
                      <Rij key={s.id} s={s} administratieId={administratieId} onActie={actie} />
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="hint" style={{ marginBottom: 0 }}>
                {data.signalen.length} terugkerende leverancier{data.signalen.length === 1 ? '' : 's'} · drempel prijsstijging{' '}
                {Number(data.prijsstijging_drempel_pct).toLocaleString('nl-NL')}%
                {verborgen > 0 && (
                  <>
                    {' '}
                    ·{' '}
                    <button type="button" className="linkbtn" onClick={() => setToonAlles(true)}>
                      {verborgen} op schema tonen
                    </button>
                  </>
                )}
                {toonAlles && verborgen === 0 && data.signalen.some((s) => s.status === 'op_schema') && (
                  <>
                    {' '}
                    ·{' '}
                    <button type="button" className="linkbtn" onClick={() => setToonAlles(false)}>
                      alleen signalen
                    </button>
                  </>
                )}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function Rij({
  s,
  administratieId,
  onActie,
}: {
  s: TerugkerendSignaalDto
  administratieId: string
  onActie: (werk: () => Promise<unknown>, tekst: string) => Promise<void>
}) {
  const naam = s.leverancier ?? 'onbekende leverancier'
  return (
    <tr className={s.status === 'afgemeld' ? 'gedempt' : undefined}>
      <td>
        <b>{naam}</b>
        <div className="hint" style={{ fontSize: 11 }}>
          {s.aantal_facturen} facturen
        </div>
      </td>
      <td>{patroonLabel(s.patroon, s.interval_dagen)}</td>
      <td>
        {formatDatumKort(s.laatste_datum)}
        {s.laatste_bedrag !== null && <div className="hint" style={{ fontSize: 11 }}>{formatBedrag(s.laatste_bedrag)}</div>}
        {s.laatste_document_id && (
          <div style={{ fontSize: 11 }}>
            <Link to={`/documenten/${administratieId}/${s.laatste_document_id}`}>document →</Link>
          </div>
        )}
      </td>
      <td>
        {formatDatumKort(s.verwacht_op)}
        <div className="hint" style={{ fontSize: 11 }}>uiterlijk {formatDatumKort(s.uiterlijk_op)}</div>
      </td>
      <td>
        {s.status === 'ontbreekt' && (
          <Badge variant="warn">
            ⚑ {STATUS_LABEL.ontbreekt} · {s.dagen_te_laat} d te laat
          </Badge>
        )}
        {s.status === 'op_schema' && <Badge variant="ok">✓ {STATUS_LABEL.op_schema}</Badge>}
        {s.status === 'gesnoozed' && (
          <Badge variant="stil" title={`tot ${s.snooze_tot ?? ''}`}>
            {STATUS_LABEL.gesnoozed}
            {s.snooze_tot ? ` tot ${formatDatumKort(s.snooze_tot)}` : ''}
          </Badge>
        )}
        {s.status === 'afgemeld' && <Badge variant="stil">{STATUS_LABEL.afgemeld}</Badge>}
      </td>
      <td>
        {s.prijsstijging_pct !== null ? (
          <Badge variant="warn" title={`vorige factuur ${s.vorige_bedrag ? formatBedrag(s.vorige_bedrag) : ''}${s.vorige_datum ? ` (${formatDatumKort(s.vorige_datum)})` : ''}`}>
            ▲ +{Number(s.prijsstijging_pct).toLocaleString('nl-NL', { maximumFractionDigits: 1 })}%
          </Badge>
        ) : (
          <span className="hint">—</span>
        )}
      </td>
      <td className="acties" style={{ whiteSpace: 'nowrap' }}>
        {s.status === 'ontbreekt' && (
          <Button variant="ghost" maat="klein" aria-label={`Snooze ${naam}`} onClick={() => void onActie(() => snoozeTerugkerend(administratieId, s.vendor_id, plusDagen(30)), `${naam} 30 dagen gesnoozed.`)}>
            snooze 30 d
          </Button>
        )}
        {s.status === 'gesnoozed' && (
          <Button variant="ghost" maat="klein" onClick={() => void onActie(() => snoozeTerugkerend(administratieId, s.vendor_id, null), `Snooze voor ${naam} opgeheven.`)}>
            snooze opheffen
          </Button>
        )}{' '}
        {s.status === 'afgemeld' ? (
          <Button variant="ghost" maat="klein" onClick={() => void onActie(() => zetTerugkerendAfgemeld(administratieId, s.vendor_id, false), `${naam} weer aangemeld.`)}>
            heractiveren
          </Button>
        ) : (
          <Button variant="ghost" maat="klein" aria-label={`Afmelden ${naam}`} onClick={() => void onActie(() => zetTerugkerendAfgemeld(administratieId, s.vendor_id, true), `${naam} afgemeld — geen signaal meer voor deze leverancier.`)}>
            afmelden
          </Button>
        )}
      </td>
    </tr>
  )
}
