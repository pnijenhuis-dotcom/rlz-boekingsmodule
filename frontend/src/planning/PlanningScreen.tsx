import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { Breadcrumb } from '../werkvoorraad/Breadcrumb'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { Badge, Button } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import {
  haalPlanning,
  isoWeekVan,
  planToewijzing,
  schuifWeek,
  verplaatsToewijzing,
  verwijderToewijzing,
  weekDagen,
  zetDagdeel,
  type PlanningKaartDto,
  type PlanningWeekDto,
} from './planningApi'

/* Planning-agenda steigerbouw (mockup planning-steigerbouw.html 1-op-1, definitief akkoord
 * Peter 22-08): ALLEEN actieve projecten als rijen, dagen (ma–vr) als kolommen, ZZP'ers/
 * uitvoerders als sleepbare kaartjes — meerdere per project/dag; halve dagen dragen een
 * ½-label. Slepen uit de pool = plannen (maakt de projectkoppeling automatisch aan, besluit
 * A); slepen tussen cellen = atomair verplaatsen. FAILSAFE: dezelfde persoon nooit 2× op
 * dezelfde dag op hetzélfde project — de cel weigert (rood), de backend-PK is het vangnet.
 * De zijbalk toont de pool (geplande dagen; > 5 = zacht signaal, besluit C), de controle-
 * meldingen (uren buiten planning · dubbele dag zonder dekking) en de dubbele-dag-teller —
 * uitsluitend zichtbaar voor kantoor. Toegang: module-recht 'Meerwerk & urenstaten'. */

interface Sleep {
  gebruikerId: string
  naam: string | null
  bron: 'pool' | { projectId: string; datum: string }
}

function dagLabel(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString('nl-NL', { day: 'numeric', month: 'numeric' })
}

function initialen(naam: string | null): string {
  if (!naam) return '?'
  return naam
    .split(/\s+/)
    .map((d) => d[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
}

export function PlanningScreen() {
  const [searchParams] = useSearchParams()
  const administratieId = searchParams.get('administratie')
  const { administraties } = useAdministraties()

  const [week, setWeek] = useState(() => isoWeekVan(new Date()))
  const [data, setData] = useState<PlanningWeekDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [geenRecht, setGeenRecht] = useState(false)
  const [moduleUit, setModuleUit] = useState(false)
  const [sleep, setSleep] = useState<Sleep | null>(null)
  const [dragOver, setDragOver] = useState<string | null>(null) // celkey "project|datum"
  const [weigerCel, setWeigerCel] = useState<string | null>(null) // failsafe-flits (rood)

  const administratieNaam = useMemo(
    () => (administraties ?? []).find((a) => a.id === administratieId)?.naam ?? 'Administratie',
    [administraties, administratieId],
  )

  const laad = useCallback(() => {
    if (!administratieId) return
    setFout(null)
    haalPlanning(administratieId, week.jaar, week.weeknummer)
      .then(setData)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) setGeenRecht(true)
        else if (err instanceof ApiError && err.status === 409) setModuleUit(true)
        else setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
  }, [administratieId, week])

  useEffect(() => {
    setData(null)
    laad()
  }, [laad])

  if (!administratieId) {
    return <p className="hint">Geen administratie gekozen — open de planning vanaf de klantpagina.</p>
  }
  if (geenRecht) {
    return (
      <p className="hint">
        De planning hoort bij het module-recht &quot;Meerwerk &amp; urenstaten&quot; — een Beheerder kent dit toe
        onder Gebruikers &amp; toegang.
      </p>
    )
  }
  if (moduleUit) {
    return <p className="hint">Uren &amp; meerwerk (en daarmee de planning) is niet ingeschakeld voor deze administratie.</p>
  }

  // Mockup: ma–vr als kolommen (weekendwerk loopt via de weekstaten, niet via de planning).
  const dagen = weekDagen(week.jaar, week.weeknummer).slice(0, 5)

  async function actie(fn: () => Promise<void>) {
    setActieFout(null)
    try {
      await fn()
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Actie mislukt — probeer het opnieuw.')
      laad() // grid verversen: de server-staat is leidend
    }
  }

  function drop(projectId: string, datum: string) {
    const celKey = `${projectId}|${datum}`
    setDragOver(null)
    if (!sleep || !administratieId) return
    const huidige = sleep
    setSleep(null)
    // FAILSAFE (besluit 22-08): zelfde persoon max 1× per project per dag — de cel weigert
    // (rode flits); de samengestelde PK in de backend is het harde vangnet.
    const cel = data?.projecten.find((p) => p.project_id === projectId)?.per_datum[datum] ?? []
    const zelfdeCel =
      typeof huidige.bron === 'object' && huidige.bron.projectId === projectId && huidige.bron.datum === datum
    if (!zelfdeCel && cel.some((k) => k.gebruiker_id === huidige.gebruikerId)) {
      setWeigerCel(celKey)
      window.setTimeout(() => setWeigerCel(null), 700)
      return
    }
    if (huidige.bron === 'pool') {
      void actie(() =>
        planToewijzing({
          administratie_id: administratieId,
          gebruiker_id: huidige.gebruikerId,
          project_id: projectId,
          datum,
        }),
      )
    } else if (!zelfdeCel) {
      const bron = huidige.bron
      void actie(() =>
        verplaatsToewijzing({
          administratie_id: administratieId,
          gebruiker_id: huidige.gebruikerId,
          van_project_id: bron.projectId,
          van_datum: bron.datum,
          naar_project_id: projectId,
          naar_datum: datum,
        }),
      )
    }
  }

  function Kaart({ kaart, projectId, datum }: { kaart: PlanningKaartDto; projectId: string; datum: string }) {
    return (
      <div
        draggable
        onDragStart={(e) => {
          e.dataTransfer.effectAllowed = 'move'
          e.dataTransfer.setData('text/plain', kaart.gebruiker_id)
          setSleep({ gebruikerId: kaart.gebruiker_id, naam: kaart.naam, bron: { projectId, datum } })
        }}
        onDragEnd={() => setSleep(null)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          background: kaart.rol === 'uitvoerder' ? 'var(--ok-bg)' : 'var(--info-bg)',
          border: '1px solid var(--border)',
          borderRadius: 9,
          padding: '4px 8px',
          fontSize: 11.5,
          marginBottom: 5,
          cursor: 'grab',
          userSelect: 'none',
        }}
      >
        <span
          aria-hidden
          style={{
            width: 20,
            height: 20,
            borderRadius: 99,
            background: 'var(--panel)',
            border: '1px solid var(--border)',
            display: 'grid',
            placeItems: 'center',
            fontSize: 9.5,
            fontWeight: 800,
            color: 'var(--primary)',
            flexShrink: 0,
          }}
        >
          {initialen(kaart.naam)}
        </span>
        <b style={{ fontSize: 12 }}>{kaart.naam ?? '?'}</b>
        {kaart.rol === 'uitvoerder' && <span style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 700 }}>uitv.</span>}
        <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 4 }}>
          <button
            className="linkbtn"
            title={kaart.dagdeel === 'half' ? 'Nu ½ dag — maak hele dag' : 'Hele dag — maak ½ dag'}
            style={{ fontSize: 10.5, fontWeight: 700 }}
            onClick={() =>
              void actie(() =>
                zetDagdeel({
                  administratie_id: administratieId!,
                  gebruiker_id: kaart.gebruiker_id,
                  project_id: projectId,
                  datum,
                  dagdeel: kaart.dagdeel === 'half' ? 'heel' : 'half',
                }),
              )
            }
          >
            {kaart.dagdeel === 'half' ? '½' : '1'}
          </button>
          <button
            className="linkbtn"
            title="Uit de planning halen"
            aria-label={`${kaart.naam ?? 'persoon'} uit de planning halen`}
            style={{ fontSize: 10.5 }}
            onClick={() =>
              void actie(() =>
                verwijderToewijzing({
                  administratie_id: administratieId!,
                  gebruiker_id: kaart.gebruiker_id,
                  project_id: projectId,
                  datum,
                }),
              )
            }
          >
            ✕
          </button>
        </span>
      </div>
    )
  }

  const vandaag = isoWeekVan(new Date())

  return (
    <div>
      <div className="topbar">
        <div>
          <Breadcrumb
            stappen={[
              { label: 'Werkvoorraad', naar: '/' },
              { label: administratieNaam, naar: `/?administratie=${administratieId}` },
            ]}
            huidige="Planning"
          />
          <h1>Planning — {administratieNaam}</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Week {week.weeknummer} · {dagLabel(dagen[0].datum)} – {dagLabel(dagen[4].datum)} · alleen actieve projecten ·
            sleep een persoon naar een project-dag — plannen maakt de projectkoppeling automatisch aan
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <Button variant="secundair" maat="klein" aria-label="Vorige week" onClick={() => setWeek(schuifWeek(week.jaar, week.weeknummer, -1))}>
            ‹
          </Button>
          <b style={{ padding: '0 4px' }}>Week {week.weeknummer}</b>
          <Button variant="secundair" maat="klein" aria-label="Volgende week" onClick={() => setWeek(schuifWeek(week.jaar, week.weeknummer, 1))}>
            ›
          </Button>
          <Button
            variant="secundair"
            maat="klein"
            disabled={week.jaar === vandaag.jaar && week.weeknummer === vandaag.weeknummer}
            onClick={() => setWeek(vandaag)}
          >
            Vandaag
          </Button>
        </div>
      </div>

      {fout && <FoutMelding melding="De planning kon niet geladen worden." detail={fout} onOpnieuw={laad} />}
      {actieFout && <div className="fout">{actieFout}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px', gap: 16, alignItems: 'start' }}>
        <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
          {data === null && !fout && (
            <div aria-busy="true" style={{ padding: 16 }}>
              <span className="skeleton" style={{ width: '55%', marginBottom: 8 }} />
              <span className="skeleton" style={{ width: '40%' }} />
            </div>
          )}
          {data !== null && data.projecten.length === 0 && (
            <p className="hint" style={{ padding: 16 }}>
              Geen actieve projecten in deze administratie — synchroniseer de projecten of activeer ze in Reeleezee.
            </p>
          )}
          {data !== null && data.projecten.length > 0 && (
            <div className="tabel-scroll">
              <table style={{ tableLayout: 'fixed', minWidth: 760 }}>
                <tbody>
                  <tr>
                    <th style={{ width: 180 }}>Project (actief)</th>
                    {dagen.map((d) => (
                      <th key={d.datum} style={{ textAlign: 'center' }}>
                        {d.naam} {dagLabel(d.datum)}
                      </th>
                    ))}
                  </tr>
                  {data.projecten.map((rij) => (
                    <tr key={rij.project_id}>
                      <th style={{ verticalAlign: 'top', textAlign: 'left' }}>
                        {rij.project_naam ?? rij.project_id}
                        <div style={{ fontWeight: 400, fontSize: 10.5, color: 'var(--muted)', marginTop: 2 }}>
                          {[rij.opdrachtgever, rij.soort_werk, rij.looptijd_tot ? `t/m ${dagLabel(rij.looptijd_tot)}` : null]
                            .filter(Boolean)
                            .join(' · ')}
                        </div>
                        {rij.week_man > 0 && (
                          <div style={{ marginTop: 5 }}>
                            <Badge variant="info">deze week: {rij.week_man} man</Badge>
                          </div>
                        )}
                      </th>
                      {dagen.map((d) => {
                        const celKey = `${rij.project_id}|${d.datum}`
                        const kaarten = rij.per_datum[d.datum] ?? []
                        return (
                          <td
                            key={d.datum}
                            data-testid={`cel-${celKey}`}
                            onDragOver={(e) => {
                              e.preventDefault()
                              setDragOver(celKey)
                            }}
                            onDragLeave={() => setDragOver((h) => (h === celKey ? null : h))}
                            onDrop={(e) => {
                              e.preventDefault()
                              drop(rij.project_id, d.datum)
                            }}
                            style={{
                              padding: 5,
                              verticalAlign: 'top',
                              minHeight: 52,
                              outline:
                                weigerCel === celKey
                                  ? '2px solid var(--danger)'
                                  : dragOver === celKey
                                    ? '2px dashed var(--primary)'
                                    : undefined,
                              outlineOffset: -3,
                              background: dragOver === celKey ? 'var(--accent-bg)' : undefined,
                            }}
                          >
                            {kaarten.map((k) => (
                              <Kaart key={k.gebruiker_id} kaart={k} projectId={rij.project_id} datum={d.datum} />
                            ))}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, position: 'sticky', top: 16 }}>
          <div className="panel">
            <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' }}>
              👷 ZZP&apos;ers &amp; uitvoerders <span style={{ fontWeight: 400, color: 'var(--faint)' }}>· sleep naar het grid</span>
            </h2>
            {data !== null && data.pool.length === 0 && (
              <p className="hint">Nog geen veldwerkers — nodig ze uit onder Gebruikers &amp; toegang.</p>
            )}
            {(data?.pool ?? []).map((p) => {
              const dagenGepland = Number(p.geplande_dagen)
              return (
                <div
                  key={p.gebruiker_id}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = 'copy'
                    e.dataTransfer.setData('text/plain', p.gebruiker_id)
                    setSleep({ gebruikerId: p.gebruiker_id, naam: p.naam, bron: 'pool' })
                  }}
                  onDragEnd={() => setSleep(null)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    background: p.rol === 'uitvoerder' ? 'var(--ok-bg)' : 'var(--info-bg)',
                    border: '1px solid var(--border)',
                    borderRadius: 9,
                    padding: '5px 8px',
                    fontSize: 11.5,
                    marginBottom: 6,
                    cursor: 'grab',
                    userSelect: 'none',
                  }}
                >
                  <b style={{ fontSize: 12 }}>{p.naam}</b>
                  {p.rol === 'uitvoerder' && <span style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 700 }}>uitv.</span>}
                  {/* Besluit C: > 5 geplande dagen per week = zacht signaal (kleurt oranje). */}
                  <span
                    style={{
                      marginLeft: 'auto',
                      fontSize: 10.5,
                      fontWeight: 600,
                      color: dagenGepland > 5 ? 'var(--warn)' : 'var(--faint)',
                    }}
                    title={dagenGepland > 5 ? 'Meer dan 5 geplande dagen deze week (zacht signaal)' : undefined}
                  >
                    {dagenGepland.toLocaleString('nl-NL', { maximumFractionDigits: 1 })} dg
                  </span>
                </div>
              )
            })}
          </div>

          {data !== null && (data.dubbele_dagen.length > 0 || data.buiten_planning.length > 0) && (
            <div className="panel">
              <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' }}>
                ⚠ Controle-meldingen{' '}
                <Badge variant="danger">{data.dubbele_dagen.length + data.buiten_planning.length}</Badge>
              </h2>
              {data.dubbele_dagen.map((m, i) => (
                <div key={`dd-${i}`} style={{ display: 'flex', gap: 8, padding: '7px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                  <span aria-hidden>🟥</span>
                  <span>
                    <b>{m.naam ?? '?'}</b> — dubbele dag {dagLabel(m.datum)}: uren op <b>{m.project_namen.join(' én ')}</b>,
                    planning dekte{' '}
                    {m.ongedekte_project_namen.length === m.project_namen.length
                      ? 'geen van de projecten'
                      : `niet: ${m.ongedekte_project_namen.join(', ')}`}
                    .
                    <span style={{ display: 'block', color: 'var(--muted)', fontSize: 11 }}>alleen zichtbaar voor kantoor</span>
                  </span>
                </div>
              ))}
              {data.buiten_planning.map((m, i) => (
                <div key={`bp-${i}`} style={{ display: 'flex', gap: 8, padding: '7px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                  <span aria-hidden>🟧</span>
                  <span>
                    <b>{m.naam ?? '?'}</b> — uren buiten planning: {dagLabel(m.datum)},{' '}
                    {Number(m.uren).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} u op {m.project_naam ?? '?'}.
                    <span style={{ display: 'block', color: 'var(--muted)', fontSize: 11 }}>
                      kleurt oranje bij de keuring — geen blokkade
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}

          {data !== null && data.dubbele_dag_tellers.length > 0 && (
            <div className="panel">
              <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' }}>
                📊 Dubbele-dag-teller (intern)
              </h2>
              {data.dubbele_dag_tellers.map((t) => (
                <div key={t.gebruiker_id} style={{ display: 'flex', padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                  <span>{t.naam ?? '?'}</span>
                  <span style={{ marginLeft: 'auto' }}>
                    <Badge variant={t.aantal >= 3 ? 'danger' : 'warn'}>{t.aantal}× / 30 dgn</Badge>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <p className="hint" style={{ marginTop: 14, maxWidth: 980 }}>
        ℹ️ Zo grijpt de planning op de weekstaten in: uren op een gepland project/dag = groen · uren búíten de
        planning = oranje &quot;buiten planning&quot; bij de keuring (geen blokkade — invallen en omplannen blijft
        mogelijk) · twee projecten op één dag zónder planning-dekking = interne melding + teller per ZZP&apos;er,
        alleen zichtbaar voor kantoor. Meerdere mensen op één project/dag = meerdere kaartjes in één cel; halve
        dagen dragen een ½-label.
      </p>
    </div>
  )
}
