import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { Breadcrumb } from '../werkvoorraad/Breadcrumb'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { Badge, Button } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import {
  haalPlanning,
  isoWeekVan,
  parseWeekParam,
  planToewijzing,
  schuifWeek,
  verplaatsToewijzing,
  verwijderToewijzing,
  weekDagen,
  weekNaarParam,
  zetDagdeel,
  type PlanningKaartDto,
  type PlanningProjectRijDto,
  type PlanningWeekDto,
} from './planningApi'

/* Planning-agenda steigerbouw (mockup planning-steigerbouw.html v3, besluit Peter 23-08 —
 * vervángt het 22-08-grid-filter "alleen projecten mét planning + zoekrij", dat gaf een leeg
 * grid waarin je niet kon beginnen): het grid toont ÁLLE actieve projecten in twee blokken —
 * mét planning deze week bovenaan (volle rijen, tellers), daaronder compact de overige
 * actieve projecten (lage rijen, direct beplanbaar via klik én drag & drop; zodra er iemand
 * gepland wordt schuift het project bij de verversing naar boven). Het filterveld boven het
 * grid versmalt beide blokken live (nummer/plaats/opdrachtgever); één request levert alles.
 * Vrij vooruit plannen (weeknavigatie + weekkiezer, onbegrensd — het hele jaar wordt vooruit
 * gevuld, besluit: géén week-kopieerknop); de URL draagt de week (?week=2026-W41) zodat een
 * stand deelbaar/herlaadbaar is. Slepen uit de pool = plannen (maakt de projectkoppeling
 * automatisch aan, besluit A); slepen tussen cellen = atomair verplaatsen; klik-alternatief:
 * cel aanklikken → persoon kiezen uit de pool (DnD is nooit de enige weg — touch/trackpad).
 * FAILSAFE: dezelfde persoon nooit 2× op dezelfde dag op hetzélfde project — de cel weigert
 * (rood), de backend-PK is het vangnet. Plannen ná de project-einddatum mag: zacht oranje
 * signaal op kaartje én rijkop, ook in het compacte blok (natuurlijke grens, geen blokkade).
 * De zijbalk toont de pool (geplande dagen; > 5 = zacht signaal, besluit C), de controle-
 * meldingen en de dubbele-dag-teller — uitsluitend kantoor. Toegang: module-recht
 * 'Meerwerk & urenstaten'. */

interface Sleep {
  gebruikerId: string
  naam: string | null
  bron: 'pool' | { projectId: string; datum: string }
}

function dagLabel(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString('nl-NL', { day: 'numeric', month: 'numeric' })
}

function lokaleIsoDatum(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
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
  const [searchParams, setSearchParams] = useSearchParams()
  const administratieId = searchParams.get('administratie')
  const { administraties } = useAdministraties()

  // De URL draagt de week (?week=2026-W41) — deelbaar/herlaadbaar; ongeldig → huidige week.
  const week = useMemo(
    () => parseWeekParam(searchParams.get('week')) ?? isoWeekVan(new Date()),
    [searchParams],
  )
  const [data, setData] = useState<PlanningWeekDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [geenRecht, setGeenRecht] = useState(false)
  const [moduleUit, setModuleUit] = useState(false)
  const [sleep, setSleep] = useState<Sleep | null>(null)
  const [dragOver, setDragOver] = useState<string | null>(null) // celkey "project|datum"
  const [weigerCel, setWeigerCel] = useState<string | null>(null) // failsafe-flits (rood)
  const [kiesCel, setKiesCel] = useState<string | null>(null) // klik-alternatief: persoon kiezen
  // Filterveld boven het grid: versmalt beide blokken live (client-side — één request).
  const [filterTerm, setFilterTerm] = useState('')

  const administratieNaam = useMemo(
    () => (administraties ?? []).find((a) => a.id === administratieId)?.naam ?? 'Administratie',
    [administraties, administratieId],
  )

  function zetWeek(w: { jaar: number; weeknummer: number }) {
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        p.set('week', weekNaarParam(w))
        return p
      },
      { replace: true },
    )
  }

  function laad() {
    if (!administratieId) return
    setFout(null)
    haalPlanning(administratieId, week.jaar, week.weeknummer)
      .then(setData)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) setGeenRecht(true)
        else if (err instanceof ApiError && err.status === 409) setModuleUit(true)
        else setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
  }

  useEffect(() => {
    setData(null)
    setKiesCel(null)
    laad()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administratieId, week.jaar, week.weeknummer])

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
  const vandaagIso = lokaleIsoDatum(new Date())

  // Grid-rijen (v3): de server levert ÁLLE actieve projecten (mét planning gevuld) in één
  // request. Splitsing in twee blokken op planning; het filter versmalt beide blokken live
  // op nummer/plaats (projectnaam) én opdrachtgever. Tellingen over de ongefilterde stand.
  const alleRijen = data?.projecten ?? []
  const term = filterTerm.trim().toLowerCase()
  const past = (rij: PlanningProjectRijDto) =>
    term === '' || `${rij.project_naam ?? ''} ${rij.opdrachtgever ?? ''}`.toLowerCase().includes(term)
  const metPlanning = alleRijen.filter((rij) => Object.keys(rij.per_datum).length > 0)
  const zonderPlanning = alleRijen.filter((rij) => Object.keys(rij.per_datum).length === 0)
  const bovenblok = metPlanning.filter(past)
  const onderblok = zonderPlanning.filter(past)
  const aantalActief = alleRijen.filter((rij) => rij.is_actief).length

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

  function plan(gebruikerId: string, projectId: string, datum: string) {
    void actie(() =>
      planToewijzing({
        administratie_id: administratieId!,
        gebruiker_id: gebruikerId,
        project_id: projectId,
        datum,
      }),
    )
  }

  function weiger(celKey: string) {
    setWeigerCel(celKey)
    window.setTimeout(() => setWeigerCel(null), 700)
  }

  function kaartenIn(projectId: string, datum: string): PlanningKaartDto[] {
    return alleRijen.find((p) => p.project_id === projectId)?.per_datum[datum] ?? []
  }

  function drop(projectId: string, datum: string) {
    const celKey = `${projectId}|${datum}`
    setDragOver(null)
    if (!sleep || !administratieId) return
    const huidige = sleep
    setSleep(null)
    // FAILSAFE (besluit 22-08): zelfde persoon max 1× per project per dag — de cel weigert
    // (rode flits); de samengestelde PK in de backend is het harde vangnet.
    const cel = kaartenIn(projectId, datum)
    const zelfdeCel =
      typeof huidige.bron === 'object' && huidige.bron.projectId === projectId && huidige.bron.datum === datum
    if (!zelfdeCel && cel.some((k) => k.gebruiker_id === huidige.gebruikerId)) {
      weiger(celKey)
      return
    }
    if (huidige.bron === 'pool') {
      plan(huidige.gebruikerId, projectId, datum)
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

  function Kaart({
    kaart,
    projectId,
    datum,
    naEinddatum,
  }: {
    kaart: PlanningKaartDto
    projectId: string
    datum: string
    naEinddatum: boolean
  }) {
    return (
      <div
        draggable
        title={naEinddatum ? 'Gepland ná de einddatum van het project (zacht signaal, geen blokkade)' : undefined}
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
          background: naEinddatum ? 'var(--warn-bg)' : kaart.rol === 'uitvoerder' ? 'var(--ok-bg)' : 'var(--info-bg)',
          border: naEinddatum ? '1px solid var(--warn)' : '1px solid var(--border)',
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
        {naEinddatum && (
          <span aria-label="ná projecteinddatum" style={{ fontSize: 10, color: 'var(--warn)', fontWeight: 700 }}>
            ⚠
          </span>
        )}
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

  // Eén projectrij, gedeeld door beide blokken. compact = project zónder planning deze week
  // (lage rij, alleen nummer/plaats + opdrachtgever in de rijkop) — de cellen zijn identiek
  // en direct beplanbaar via klik én drag & drop; ná het plannen ververst het grid en schuift
  // het project naar het bovenste blok. Bewust een render-functie (geen component): met 68
  // projecten zou een per-render nieuw componenttype elke keer de hele subtree remounten.
  function renderRij(rij: PlanningProjectRijDto, compact: boolean) {
    const rijNaEinddatum = rij.looptijd_tot !== null && dagen[0].datum > rij.looptijd_tot
    return (
      <tr key={rij.project_id} className={compact ? 'plan-compact' : undefined}>
        <th style={{ verticalAlign: 'top', textAlign: 'left' }}>
          {rij.project_naam ?? rij.project_id}
          <div style={{ fontWeight: 400, fontSize: 10.5, color: 'var(--muted)', marginTop: 2 }}>
            {[rij.opdrachtgever, rij.soort_werk, rij.looptijd_tot ? `t/m ${dagLabel(rij.looptijd_tot)}` : null]
              .filter(Boolean)
              .join(' · ')}
            {compact && rijNaEinddatum && (
              <b style={{ color: 'var(--warn)', fontWeight: 700 }}> ⚠ ná einddatum</b>
            )}
          </div>
          {!compact && rijNaEinddatum && (
            <div style={{ fontWeight: 600, fontSize: 10.5, color: 'var(--warn)', marginTop: 3 }}>
              ⚠ deze week valt ná de einddatum
            </div>
          )}
          {!compact && rij.week_man > 0 && (
            <div style={{ marginTop: 5 }}>
              <Badge variant="info">deze week: {rij.week_man} man</Badge>
            </div>
          )}
        </th>
        {dagen.map((d) => {
          const celKey = `${rij.project_id}|${d.datum}`
          const kaarten = rij.per_datum[d.datum] ?? []
          const naEinddatum = rij.looptijd_tot !== null && d.datum > rij.looptijd_tot
          // De persoon-kiezer alleen berekenen voor de éne open cel (68 rijen × 5 dagen).
          const kiesbaar =
            kiesCel === celKey
              ? (data?.pool ?? []).filter((p) => !kaarten.some((k) => k.gebruiker_id === p.gebruiker_id))
              : []
          return (
            <td
              key={d.datum}
              data-testid={`cel-${celKey}`}
              className={`plan-cel${d.datum === vandaagIso ? ' plan-vandaag' : ''}`}
              title="Klik om een persoon te plannen"
              onClick={(e) => {
                // Klik-alternatief voor DnD: alleen op de lege celruimte zelf
                // (kliks op kaartjes/kiezer raken de td niet als target).
                if (e.target === e.currentTarget) setKiesCel((h) => (h === celKey ? null : celKey))
              }}
              onDragEnter={(e) => e.preventDefault()}
              onDragOver={(e) => {
                e.preventDefault()
                e.dataTransfer.dropEffect = sleep?.bron === 'pool' ? 'copy' : 'move'
                setDragOver(celKey)
              }}
              onDragLeave={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                  setDragOver((h) => (h === celKey ? null : h))
                }
              }}
              onDrop={(e) => {
                e.preventDefault()
                drop(rij.project_id, d.datum)
              }}
              style={{
                padding: 5,
                verticalAlign: 'top',
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
                <Kaart
                  key={k.gebruiker_id}
                  kaart={k}
                  projectId={rij.project_id}
                  datum={d.datum}
                  naEinddatum={naEinddatum}
                />
              ))}
              {kiesCel === celKey && (
                <div
                  style={{
                    background: 'var(--panel)',
                    border: '1px solid var(--border)',
                    borderRadius: 9,
                    boxShadow: 'var(--schaduw, 0 4px 16px rgba(0,0,0,.12))',
                    fontSize: 12,
                    marginTop: 2,
                    padding: 6,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                    <b style={{ fontSize: 11 }}>Plan op {dagLabel(d.datum)}</b>
                    <button
                      className="linkbtn"
                      aria-label="Kiezer sluiten"
                      style={{ marginLeft: 'auto' }}
                      onClick={() => setKiesCel(null)}
                    >
                      ✕
                    </button>
                  </div>
                  {kiesbaar.length === 0 && <p className="hint" style={{ margin: 0 }}>Iedereen staat al in deze cel.</p>}
                  {kiesbaar.map((p) => (
                    <button
                      key={p.gebruiker_id}
                      className="linkbtn"
                      style={{ display: 'block', padding: '3px 4px', textAlign: 'left', width: '100%' }}
                      onClick={() => {
                        setKiesCel(null)
                        plan(p.gebruiker_id, rij.project_id, d.datum)
                      }}
                    >
                      {p.naam}
                      {p.rol === 'uitvoerder' ? ' · uitv.' : ''}
                    </button>
                  ))}
                </div>
              )}
            </td>
          )
        })}
      </tr>
    )
  }

  const vandaagWeek = isoWeekVan(new Date())

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
            Week {week.weeknummer} · {dagLabel(dagen[0].datum)} – {dagLabel(dagen[4].datum)} · álle actieve projecten
            (mét planning bovenaan) · sleep een persoon naar een project-dag, of klik een cel om te plannen
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <Button
            variant="secundair"
            maat="klein"
            aria-label="Vorige week"
            onClick={() => zetWeek(schuifWeek(week.jaar, week.weeknummer, -1))}
          >
            ‹
          </Button>
          {/* Week-/datumkiezer: zelfde vorm als de URL-parameter (2026-W41) — vrij vooruit. */}
          <input
            type="week"
            aria-label="Weekkiezer"
            value={weekNaarParam(week)}
            onChange={(e) => {
              const gekozen = parseWeekParam(e.target.value)
              if (gekozen) zetWeek(gekozen)
            }}
            style={{
              background: 'var(--panel)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              color: 'var(--text)',
              font: 'inherit',
              fontWeight: 700,
              padding: '4px 8px',
            }}
          />
          <Button
            variant="secundair"
            maat="klein"
            aria-label="Volgende week"
            onClick={() => zetWeek(schuifWeek(week.jaar, week.weeknummer, 1))}
          >
            ›
          </Button>
          <Button
            variant="secundair"
            maat="klein"
            disabled={week.jaar === vandaagWeek.jaar && week.weeknummer === vandaagWeek.weeknummer}
            onClick={() => zetWeek(vandaagWeek)}
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
          {data !== null && (
            <>
              {/* Filter (client-side, live) + telling — mockup v3. */}
              <div
                style={{
                  alignItems: 'center',
                  borderBottom: '1px solid var(--border)',
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 10,
                  padding: '10px 12px',
                }}
              >
                <input
                  type="search"
                  aria-label="Filter projecten"
                  placeholder="Filter projecten… (nummer, plaats of opdrachtgever)"
                  value={filterTerm}
                  onChange={(e) => setFilterTerm(e.target.value)}
                  style={{
                    background: 'var(--panel-2)',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    color: 'var(--text)',
                    flex: '0 1 340px',
                    font: 'inherit',
                    fontSize: 12.5,
                    padding: '7px 11px',
                  }}
                />
                <span style={{ color: 'var(--faint)', fontSize: 11.5 }}>
                  {aantalActief} actieve projecten · {metPlanning.length} mét planning deze week
                </span>
              </div>
              <div className="tabel-scroll">
              <table className="plan-grid" style={{ tableLayout: 'fixed', minWidth: 760 }}>
                <thead>
                  <tr>
                    <th style={{ width: 180 }}>Project</th>
                    {dagen.map((d) => (
                      <th
                        key={d.datum}
                        className={d.datum === vandaagIso ? 'plan-vandaag' : undefined}
                        style={{ textAlign: 'center' }}
                      >
                        {d.naam} {dagLabel(d.datum)}
                        {d.datum === vandaagIso && (
                          <span style={{ display: 'block', textTransform: 'none', letterSpacing: 0, fontWeight: 500 }}>
                            vandaag
                          </span>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {alleRijen.length === 0 && (
                    <tr>
                      <td colSpan={6}>
                        <p className="hint" style={{ margin: 0 }}>
                          Geen actieve projecten in deze administratie — synchroniseer de projecten of activeer ze in
                          RLZ.
                        </p>
                      </td>
                    </tr>
                  )}
                  {alleRijen.length > 0 && bovenblok.length === 0 && onderblok.length === 0 && (
                    <tr>
                      <td colSpan={6}>
                        <p className="hint" style={{ margin: 0 }}>
                          Geen project past bij &quot;{filterTerm.trim()}&quot; — pas het filter aan.
                        </p>
                      </td>
                    </tr>
                  )}
                  {bovenblok.map((rij) => renderRij(rij, false))}
                  {/* Overige actieve projecten: compact, leeg maar direct beplanbaar (v3). */}
                  {onderblok.length > 0 && (
                    <tr className="plan-scheider">
                      <th colSpan={6}>Overige actieve projecten — nog niemand gepland deze week</th>
                    </tr>
                  )}
                  {onderblok.map((rij) => renderRij(rij, true))}
                </tbody>
              </table>
              </div>
            </>
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
        dagen dragen een ½-label. Vooruit plannen kan onbegrensd (het hele jaar wordt vooruit gevuld); plannen ná
        de einddatum van een project mag en kleurt oranje.
      </p>
    </div>
  )
}
