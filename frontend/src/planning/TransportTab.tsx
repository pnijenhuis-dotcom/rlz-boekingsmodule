import { useCallback, useEffect, useMemo, useState, type DragEvent as ReactDragEvent } from 'react'
import { ApiError } from '../api/client'
import { Badge, Button, Select, useToastOptioneel, SkeletonRegels } from '../ui/basis'
import { BestellingPopup } from './BestellingPopup'
import { MateriaalstandPaneel } from './MateriaalstandPaneel'
import {
  bevestigTransport,
  haalBestellingen,
  haalCatalogus,
  haalLeveranciers,
  haalTransportWeek,
  maakBestelling,
  maakTransportDefinitief,
  planTransport,
  schatM2,
  verschuifTransport,
  wijzigMateriaallijst,
  wijzigTransport,
  zetTransportStatus,
  type BestellingDto,
  type CategorieDto,
  type LeverancierDto,
  type ProductDto,
  type TePlannenDto,
  type TransportDto,
  type TransportProjectRijDto,
  type TransportWeekDto,
} from './transportApi'

/* Transport-tab op /planning als DAG-AGENDA (feedbackronde Peter 31-08, mockup
 * planning-werkopdracht-transport.html TAB 2 = norm): géén projectrijen — kolommen = de vijf
 * werkdagen, elke kaart is zelfstandig leesbaar (projectnr · klant · adres · ▲levering/▼retour ·
 * materiaal · leverancier · voertuig · planner · status). Statusflow: werkbakje-sleep =
 * gereserveerd (rood) → kaart-klik = bevestigd (oranje, voertuigtoezegging + melding aan het
 * transport-contact) → materiaallijst + transportplanner = definitief (groen, lijst naar het
 * materiaal-contact; wijzigen daarna = delta-mail) → geleverd (grijs). Dag verschuiven
 * (slepen/klik-klik) zet de kaart terug naar gereserveerd. Signaalkaart "nog te plannen" voor
 * verstuurde bestellingen zonder transportregel. Zijbalk: werkbakje, leveranciers-contacten,
 * materiaalstand, factuurcontrole, wachtrisico's (kruissignaal), bestellingen (popup). */

function dagLabel(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('nl-NL', { weekday: 'short', day: 'numeric', month: 'numeric' })
}

const STATUS_STIJL: Record<TransportDto['status'], { bg: string; rand: string; kleur: string }> = {
  gereserveerd: { bg: 'var(--danger-bg)', rand: 'var(--danger)', kleur: 'var(--danger)' },
  bevestigd: { bg: 'var(--warn-bg)', rand: 'var(--warn)', kleur: 'var(--warn)' },
  definitief: { bg: 'var(--ok-bg)', rand: 'var(--ok)', kleur: 'var(--ok)' },
  geleverd: { bg: 'var(--panel-2)', rand: 'var(--border)', kleur: 'var(--muted)' },
  geannuleerd: { bg: 'var(--panel-2)', rand: 'var(--border)', kleur: 'var(--muted)' },
}

const VOERTUIG_LABEL: Record<'combi' | 'voorwagen', string> = { combi: '🚛 combi', voorwagen: '🚚 voorwagen' }

interface BakChip {
  project_id: string
  label: string
}

function bakSleutel(administratieId: string): string {
  return `transport_werkbakje_${administratieId}`
}

function leesBak(administratieId: string): BakChip[] {
  try {
    const raw = localStorage.getItem(bakSleutel(administratieId))
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    return Array.isArray(parsed) ? (parsed as BakChip[]).filter((c) => typeof c?.project_id === 'string' && typeof c?.label === 'string') : []
  } catch {
    return []
  }
}

function schrijfBak(administratieId: string, bak: BakChip[]): void {
  try {
    localStorage.setItem(bakSleutel(administratieId), JSON.stringify(bak))
  } catch {
    /* localStorage kan ontbreken — het bakje is alleen gemak */
  }
}

export function TransportTab({
  administratieId,
  week,
  dagen,
  filterTerm,
  setFilterTerm,
}: {
  administratieId: string
  week: { jaar: number; weeknummer: number }
  dagen: { datum: string; naam: string }[]
  filterTerm: string
  setFilterTerm: (t: string) => void
}) {
  const { meld } = useToastOptioneel()
  const [data, setData] = useState<TransportWeekDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [leveranciers, setLeveranciers] = useState<LeverancierDto[]>([])
  const [bewerk, setBewerk] = useState<TransportDto | null>(null)
  const [bevestigKaart, setBevestigKaart] = useState<TransportDto | null>(null)
  const [lijstKaart, setLijstKaart] = useState<TransportDto | null>(null)
  const [verplaats, setVerplaats] = useState<TransportDto | null>(null)
  const [zijProject, setZijProject] = useState<string | null>(null)
  const [bestellingen, setBestellingen] = useState<BestellingDto[]>([])
  const [popupBestelling, setPopupBestelling] = useState<string | null>(null)
  const [nieuweBestelling, setNieuweBestelling] = useState(false)
  // Werkbakje (mockup): chips blijven staan per administratie (localStorage) tot je ze wegklikt.
  const [bak, setBakState] = useState<BakChip[]>(() => leesBak(administratieId))
  const [bakZoek, setBakZoek] = useState('')
  const [bakSelectie, setBakSelectie] = useState<string | null>(null)
  const [levKeuze, setLevKeuze] = useState<{ projectId: string; label: string; datum: string; bestellingId: string | null } | null>(null)
  const [dragOverDag, setDragOverDag] = useState<string | null>(null)

  useEffect(() => {
    setBakState(leesBak(administratieId))
    setBakSelectie(null)
  }, [administratieId])
  const zetBak = (volgende: BakChip[]) => {
    setBakState(volgende)
    schrijfBak(administratieId, volgende)
  }

  const laad = useCallback(() => {
    setFout(null)
    haalTransportWeek(administratieId, week.jaar, week.weeknummer)
      .then(setData)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
    haalBestellingen(administratieId, { per_pagina: 10 })
      .then((r) => setBestellingen(r.items))
      .catch(() => undefined)
  }, [administratieId, week.jaar, week.weeknummer])
  useEffect(() => {
    laad()
  }, [laad])
  useEffect(() => {
    haalLeveranciers(administratieId).then(setLeveranciers).catch(() => setLeveranciers([]))
  }, [administratieId])

  const term = filterTerm.trim().toLowerCase()
  const zichtbaar = (r: TransportProjectRijDto) => !term || `${r.project_naam ?? ''} ${r.opdrachtgever ?? ''}`.toLowerCase().includes(term)
  const wachtrisicoKeys = useMemo(() => new Set((data?.wachtrisico ?? []).map((w) => `${w.project_id}|${w.datum}`)), [data])
  const werkdagen = dagen.slice(0, 5)
  const leverancierBij = (id: string) => leveranciers.find((l) => l.id === id) ?? null

  // Dag-agenda: alle kaarten van de week per datum (over álle projecten), gesorteerd op
  // tijdstip (leeg achteraan) en dan projectnaam.
  const perDag = useMemo(() => {
    const m = new Map<string, TransportDto[]>()
    for (const r of data?.projecten ?? []) {
      if (!zichtbaar(r)) continue
      for (const [datum, items] of Object.entries(r.per_datum)) {
        m.set(datum, [...(m.get(datum) ?? []), ...items])
      }
    }
    for (const items of m.values()) {
      items.sort((a, b) => (a.tijdstip ?? '99:99').localeCompare(b.tijdstip ?? '99:99') || (a.project_naam ?? '').localeCompare(b.project_naam ?? ''))
    }
    return m
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, term])
  const tePlannenPerDag = useMemo(() => {
    const m = new Map<string, TePlannenDto[]>()
    for (const s of data?.te_plannen ?? []) {
      if (term && !`${s.project_naam ?? ''} ${s.leverancier_naam}`.toLowerCase().includes(term)) continue
      m.set(s.datum, [...(m.get(s.datum) ?? []), s])
    }
    return m
  }, [data, term])
  const metTransport = (data?.projecten ?? []).filter((r) => r.week_transporten > 0 && zichtbaar(r))
  const zijProjectId = zijProject ?? metTransport[0]?.project_id ?? null

  async function status(t: TransportDto, nieuw: TransportDto['status']) {
    setActieFout(null)
    try {
      let reden: string | undefined
      if (nieuw === 'geannuleerd') {
        const r = window.prompt('Reden van annuleren (verplicht):')
        if (!r || r.trim().length < 3) return
        reden = r.trim()
      }
      await zetTransportStatus(administratieId, t.id, nieuw, reden)
      meld(`Transport ${t.samenvatting}: ${nieuw}${nieuw === 'geleverd' ? ' — materiaalstand bijgewerkt' : ''}.`)
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Statuswijziging mislukt.')
    }
  }

  async function planNieuw(projectId: string, datum: string, leverancierId: string, bestellingId: string | null) {
    setActieFout(null)
    try {
      await planTransport(administratieId, {
        project_id: projectId,
        leverancier_id: leverancierId,
        soort: 'levering',
        datum,
        tijdstip: null,
        regels: {},
        omschrijving: null,
        bestelling_id: bestellingId,
      })
      meld('Transport gereserveerd (rood) — klik de kaart om te bevestigen zodra het transport-contact toezegt.')
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Plannen mislukt.')
    }
  }

  /** Plannen vereist een leverancier: precies één actieve = die; anders eerst een keuzemenu. */
  function startPlan(projectId: string, label: string, datum: string, bestellingId: string | null) {
    if (leveranciers.length === 0) {
      setActieFout('Nog geen leveranciers — Beheerder: Instellingen → Materiaalcatalogus.')
      return
    }
    if (leveranciers.length === 1) {
      void planNieuw(projectId, datum, leveranciers[0].id, bestellingId)
      return
    }
    setLevKeuze({ projectId, label, datum, bestellingId })
  }

  function planTePlannen(s: TePlannenDto) {
    const lev = leveranciers.find((l) => l.naam === s.leverancier_naam)
    if (lev) {
      void planNieuw(s.project_id, s.datum, lev.id, s.bestelling_id)
      return
    }
    startPlan(s.project_id, `${s.bestelling_nummer} · ${s.project_naam ?? '?'}`, s.datum, s.bestelling_id)
  }

  async function verschuif(t: TransportDto, datum: string) {
    if (t.datum === datum || t.status === 'geleverd' || t.status === 'geannuleerd') return
    setActieFout(null)
    if (t.status === 'bevestigd' || t.status === 'definitief') {
      const contact = leverancierBij(t.leverancier_id)?.transport_contact_naam ?? 'het transport-contact'
      if (!window.confirm(`Dag verschuiven zet de kaart terug naar gereserveerd — ${contact} moet opnieuw bevestigen. Doorgaan?`)) return
    }
    try {
      await verschuifTransport(administratieId, t.id, datum)
      meld(`Transport verschoven naar ${dagLabel(datum)} — terug naar gereserveerd, materiaallijst blijft bewaard.`)
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Verschuiven mislukt.')
    }
  }

  function vindTransport(id: string): TransportDto | null {
    for (const r of data?.projecten ?? []) {
      for (const items of Object.values(r.per_datum)) {
        const t = items.find((x) => x.id === id)
        if (t) return t
      }
    }
    return null
  }

  function celKlik(datum: string) {
    if (verplaats) {
      void verschuif(verplaats, datum)
      setVerplaats(null)
      return
    }
    if (bakSelectie) {
      const chip = bak.find((c) => c.project_id === bakSelectie)
      setBakSelectie(null)
      if (chip) startPlan(chip.project_id, chip.label, datum, null)
    }
  }

  function celDrop(e: ReactDragEvent<HTMLTableCellElement>, datum: string) {
    e.preventDefault()
    setDragOverDag(null)
    const payload = e.dataTransfer.getData('text/plain')
    if (payload.startsWith('t:')) {
      const t = vindTransport(payload.slice(2))
      if (t) void verschuif(t, datum)
    } else if (payload.startsWith('bak:')) {
      const chip = bak.find((c) => c.project_id === payload.slice(4))
      if (chip) startPlan(chip.project_id, chip.label, datum, null)
    }
  }

  function statusRegel(t: TransportDto): string {
    const risico = wachtrisicoKeys.has(`${t.project_id}|${t.datum}`) && t.status === 'gereserveerd'
    const lev = leverancierBij(t.leverancier_id)
    const basis =
      t.status === 'gereserveerd'
        ? 'gereserveerd — klik om te bevestigen'
        : t.status === 'bevestigd'
          ? 'bevestigd — materiaallijst nog invullen'
          : t.status === 'definitief'
            ? `definitief · lijst bij ${lev?.materiaal_contact_naam ?? 'materiaal-contact'}`
            : t.status === 'geleverd'
              ? 'geleverd ✓'
              : `geannuleerd${t.status_reden ? ` — ${t.status_reden}` : ''}`
    return `${basis}${risico ? ' · ⚠ ploeg staat gepland' : ''}`
  }

  function kaartKlik(t: TransportDto) {
    if (t.status === 'gereserveerd') setBevestigKaart(t)
    else if (t.status === 'bevestigd' || t.status === 'definitief') setLijstKaart(t)
  }

  function Kaart({ t }: { t: TransportDto }) {
    const stijl = STATUS_STIJL[t.status]
    const sleepbaar = t.status !== 'geleverd' && t.status !== 'geannuleerd'
    const klikbaar = t.status === 'gereserveerd' || t.status === 'bevestigd' || t.status === 'definitief'
    const meta = [
      t.samenvatting,
      t.leverancier_naam,
      t.tijdstip ? t.tijdstip.slice(0, 5) : null,
      t.voertuig ? VOERTUIG_LABEL[t.voertuig] : null,
      t.transportplanner ? `planner: ${t.transportplanner}` : null,
    ].filter(Boolean)
    return (
      <div
        draggable={sleepbaar}
        onDragStart={(e) => {
          e.dataTransfer.effectAllowed = 'move'
          e.dataTransfer.setData('text/plain', `t:${t.id}`)
        }}
        onClick={(e) => {
          e.stopPropagation()
          kaartKlik(t)
        }}
        style={{
          borderRadius: 9,
          padding: '5px 8px',
          marginBottom: 5,
          fontSize: 11.5,
          lineHeight: 1.3,
          border: `1px solid color-mix(in srgb, ${stijl.rand} 35%, transparent)`,
          background: stijl.bg,
          opacity: t.status === 'geannuleerd' ? 0.5 : 1,
          cursor: klikbaar ? 'pointer' : sleepbaar ? 'grab' : 'default',
          userSelect: 'none',
        }}
        title={klikbaar ? statusRegel(t) : `${t.leverancier_naam} · ${t.status}${t.status_reden ? ` — ${t.status_reden}` : ''}`}
      >
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontWeight: 800 }} aria-hidden>
            {t.soort === 'levering' ? '▲' : '▼'}
          </span>
          <b style={{ flex: 1, fontSize: 12 }}>
            {t.project_naam ?? t.project_id}
            {t.opdrachtgever ? ` · ${t.opdrachtgever}` : ''}
          </b>
        </div>
        <div className="hint" style={{ margin: 0, fontSize: 10.5 }}>{t.project_adres ?? '—'}</div>
        <div className="hint" style={{ margin: 0, fontSize: 10.5 }}>
          {meta.join(' · ')}
          {t.bestelling_nummer ? ` · ${t.bestelling_nummer}` : ''}
        </div>
        <div style={{ fontSize: 10.5, fontWeight: 800, color: stijl.kleur }}>{statusRegel(t)}</div>
        {t.status !== 'geleverd' && t.status !== 'geannuleerd' && (
          <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }} onClick={(e) => e.stopPropagation()}>
            {t.status === 'definitief' && (
              <button className="linkbtn" style={{ fontSize: 10.5 }} onClick={() => void status(t, 'geleverd')}>
                geleverd ✓
              </button>
            )}
            {t.status === 'gereserveerd' && (
              <button className="linkbtn" style={{ fontSize: 10.5 }} onClick={() => setBewerk(t)}>
                wijzig
              </button>
            )}
            <button
              className="linkbtn"
              style={{ fontSize: 10.5, fontWeight: verplaats?.id === t.id ? 800 : undefined }}
              title="Verplaatsen zonder slepen: klik hierna de dagkolom"
              onClick={() => setVerplaats(verplaats?.id === t.id ? null : t)}
            >
              ⇄ {verplaats?.id === t.id ? 'kies dag…' : 'verplaats'}
            </button>
            <button className="linkbtn" style={{ fontSize: 10.5, color: 'var(--danger)' }} onClick={() => void status(t, 'geannuleerd')}>
              ✕
            </button>
          </div>
        )}
      </div>
    )
  }

  const bakResultaten =
    bakZoek.trim().length >= 2
      ? (data?.projecten ?? [])
          .filter((r) => r.is_actief && `${r.project_naam ?? ''} ${r.opdrachtgever ?? ''}`.toLowerCase().includes(bakZoek.trim().toLowerCase()))
          .filter((r) => !bak.some((c) => c.project_id === r.project_id))
          .slice(0, 8)
      : []

  return (
    <>
      {fout && <div className="fout">{fout}</div>}
      {actieFout && <div className="fout">{actieFout}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px', gap: 16, alignItems: 'start' }}>
        <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ alignItems: 'center', borderBottom: '1px solid var(--border)', display: 'flex', flexWrap: 'wrap', gap: 12, padding: '10px 12px' }}>
            <input
              type="search"
              aria-label="Filter projecten"
              placeholder="Filter projecten…"
              value={filterTerm}
              onChange={(e) => setFilterTerm(e.target.value)}
              style={{ background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)', flex: '0 1 220px', font: 'inherit', fontSize: 12.5, padding: '7px 11px' }}
            />
            <span style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontSize: 11, color: 'var(--muted)' }}>
              {(
                [
                  ['var(--danger)', 'gereserveerd'],
                  ['var(--warn)', 'bevestigd'],
                  ['var(--ok)', 'definitief'],
                  ['var(--faint)', 'geleverd'],
                ] as const
              ).map(([kleur, label], i) => (
                <span key={label} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  {i > 0 && <span aria-hidden style={{ marginRight: 6 }}>→</span>}
                  <span aria-hidden style={{ width: 9, height: 9, borderRadius: 99, background: kleur, display: 'inline-block' }} />
                  <b>{label}</b>
                </span>
              ))}
            </span>
            {data && (
              <span style={{ color: 'var(--faint)', fontSize: 11.5, marginLeft: 'auto' }}>
                transporten deze week: {data.aantal_transporten} · {data.wachtrisico.length} wachtrisico
              </span>
            )}
          </div>
          {data === null && !fout && <div style={{ padding: 16 }}><SkeletonRegels /></div>}
          {data !== null && (
            <div className="tabel-scroll">
              <table className="plan-grid" style={{ tableLayout: 'fixed', minWidth: 760 }}>
                <thead>
                  <tr>
                    {werkdagen.map(({ datum }, i) => (
                      <th key={datum}>
                        {dagLabel(datum)}
                        {i === 0 ? ` · wk ${week.weeknummer}` : ''}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    {werkdagen.map(({ datum }) => (
                      <td
                        key={datum}
                        onClick={() => celKlik(datum)}
                        onDragOver={(e) => {
                          e.preventDefault()
                          setDragOverDag(datum)
                        }}
                        onDragLeave={() => setDragOverDag((h) => (h === datum ? null : h))}
                        onDrop={(e) => celDrop(e, datum)}
                        style={{
                          verticalAlign: 'top',
                          padding: 5,
                          height: 220,
                          cursor: bakSelectie || verplaats ? 'copy' : 'default',
                          background: dragOverDag === datum ? 'var(--accent-bg)' : undefined,
                          outline: dragOverDag === datum ? '2px dashed var(--primary)' : undefined,
                          outlineOffset: -3,
                        }}
                        title={bakSelectie ? 'Klik om het geselecteerde project hier te plannen' : verplaats ? 'Klik om het transport naar deze dag te verschuiven' : undefined}
                      >
                        {(tePlannenPerDag.get(datum) ?? []).map((s) => (
                          <button
                            key={s.bestelling_id}
                            onClick={(e) => {
                              e.stopPropagation()
                              planTePlannen(s)
                            }}
                            title="Verstuurde bestelling zonder transportregel — klik om direct een levering te plannen"
                            style={{
                              display: 'block',
                              width: '100%',
                              textAlign: 'left',
                              borderRadius: 9,
                              padding: '5px 8px',
                              marginBottom: 5,
                              fontSize: 11,
                              fontWeight: 700,
                              color: 'var(--danger)',
                              border: '1px dashed var(--danger)',
                              background: 'repeating-linear-gradient(45deg, transparent, transparent 7px, var(--danger-bg) 7px, var(--danger-bg) 14px)',
                              cursor: 'pointer',
                              font: 'inherit',
                            }}
                          >
                            ⚠ nog te plannen — {s.bestelling_nummer} · {s.project_naam ?? '?'} · {s.leverancier_naam}
                          </button>
                        ))}
                        {(perDag.get(datum) ?? []).map((t) => (
                          <Kaart key={t.id} t={t} />
                        ))}
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          )}
          <div style={{ padding: '8px 12px', fontSize: 11, color: 'var(--faint)', borderTop: '1px solid var(--border)' }}>
            Dag-agenda: elke kaart is zelfstandig leesbaar en sleepbaar tussen dagen (verschuiven = terug naar gereserveerd). Nieuw transport: zoek een
            project in het werkbakje rechts en sleep de chip naar een dag — of klik chip en dag.
          </div>
        </div>

        <div>
          <div className="panel">
            <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' }}>
              🧺 Werkbakje — project erbij pakken
            </h2>
            <input
              type="search"
              aria-label="Zoek project voor het werkbakje"
              placeholder="Zoek project… (typ bv. 250)"
              value={bakZoek}
              onChange={(e) => setBakZoek(e.target.value)}
              style={{ width: '100%' }}
            />
            {bakResultaten.length > 0 && (
              <div style={{ border: '1px solid var(--border)', borderRadius: 8, marginTop: 6, overflow: 'hidden' }}>
                {bakResultaten.map((r) => (
                  <button
                    key={r.project_id}
                    className="linkbtn"
                    style={{ display: 'block', width: '100%', textAlign: 'left', padding: '7px 11px', fontSize: 12, borderBottom: '1px solid var(--border)' }}
                    onClick={() => {
                      const label = `${r.project_naam ?? r.project_id}${r.opdrachtgever ? ` — ${r.opdrachtgever}` : ''}`
                      zetBak([{ project_id: r.project_id, label }, ...bak])
                      setBakZoek('')
                    }}
                  >
                    {r.project_naam ?? r.project_id} <span style={{ color: 'var(--faint)' }}>· {r.opdrachtgever ?? '—'}</span>
                  </button>
                ))}
              </div>
            )}
            {bakZoek.trim().length >= 2 && bakResultaten.length === 0 && <p className="hint" style={{ fontSize: 11 }}>Geen actief project gevonden.</p>}
            <div style={{ marginTop: 10 }}>
              {bak.map((c) => (
                <div
                  key={c.project_id}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = 'copy'
                    e.dataTransfer.setData('text/plain', `bak:${c.project_id}`)
                  }}
                  onClick={() => setBakSelectie(bakSelectie === c.project_id ? null : c.project_id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 7,
                    background: 'var(--accent-bg)',
                    border: '1px solid color-mix(in srgb, var(--primary) 30%, transparent)',
                    borderRadius: 9,
                    padding: '7px 9px',
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: 'grab',
                    marginBottom: 6,
                    userSelect: 'none',
                    outline: bakSelectie === c.project_id ? '2px solid var(--primary)' : undefined,
                    outlineOffset: 1,
                  }}
                >
                  <span style={{ flex: 1 }}>🏗 {c.label}</span>
                  <button
                    className="linkbtn"
                    aria-label={`${c.label} uit het bakje`}
                    style={{ color: 'var(--faint)', fontSize: 13 }}
                    onClick={(e) => {
                      e.stopPropagation()
                      if (bakSelectie === c.project_id) setBakSelectie(null)
                      zetBak(bak.filter((x) => x.project_id !== c.project_id))
                    }}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
            <p className="hint" style={{ fontSize: 11, marginTop: 6 }}>
              {bakSelectie
                ? 'Klik nu een dagkolom om het geselecteerde project daar te plannen (gereserveerd).'
                : 'Sleep een chip naar een dag, óf: klik de chip (selecteren) en klik daarna de dag. De chip blijft in het bakje tot je ’m wegklikt — zo plan je hetzelfde project op meerdere dagen.'}
            </p>
          </div>

          <div className="panel">
            <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' }}>🚚 Leveranciers</h2>
            {leveranciers.length === 0 && <p className="hint" style={{ margin: 0, fontSize: 11.5 }}>Nog geen leveranciers — Beheerder: Instellingen → Materiaalcatalogus.</p>}
            {leveranciers.map((l) => (
              <div key={l.id} style={{ padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                <b>{l.naam}</b>
                <span className="hint" style={{ display: 'block', fontSize: 11, margin: 0 }}>
                  transport-contact: {l.transport_contact_naam ? <b>{l.transport_contact_naam}</b> : 'nog niet ingevuld'} (melding bij bevestigen) · materiaal-contact:{' '}
                  {l.materiaal_contact_naam ? <b>{l.materiaal_contact_naam}</b> : 'nog niet ingevuld'} (lijst bij definitief + delta bij wijziging)
                </span>
              </div>
            ))}
          </div>

          {zijProjectId && (
            <>
              {metTransport.length > 1 && (
                <Select value={zijProjectId} onChange={(e) => setZijProject(e.target.value)} className="w-full" aria-label="Project voor materiaalstand" style={{ marginBottom: 8 }}>
                  {metTransport.map((r) => (
                    <option key={r.project_id} value={r.project_id}>
                      {r.project_naam}
                    </option>
                  ))}
                </Select>
              )}
              <MateriaalstandPaneel key={zijProjectId} administratieId={administratieId} projectId={zijProjectId} compact />
            </>
          )}

          <div className="panel">
            <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' }}>
              🧾 Factuurcontrole materiaal {data && data.materiaalmatch_open > 0 && <Badge variant="warn">{data.materiaalmatch_open}</Badge>}
            </h2>
            <p className="hint" style={{ margin: 0, fontSize: 11.5 }}>
              {data && data.materiaalmatch_open > 0
                ? `${data.materiaalmatch_open} inkoopfactuur/facturen van verhuur-crediteuren wijken af van de geregistreerde leveringen — controleren vóór boeken (controlescherm, sectie Materiaalcontrole).`
                : 'Inkoopfacturen van gekoppelde verhuur-crediteuren worden per project gematcht tegen de geregistreerde leveringen/huurperiodes (aantal × huurperiode per item) — zelfde patroon als de uren-factuurmatch.'}
            </p>
          </div>

          {data && data.wachtrisico.length > 0 && (
            <div className="panel">
              <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' }}>⚠ Wachtrisico&apos;s</h2>
              {data.wachtrisico.map((w, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, padding: '7px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                  <span aria-hidden>🟥</span>
                  <span>
                    <b>
                      {w.project_naam ?? '?'} {dagLabel(w.datum)}
                    </b>{' '}
                    — ploeg gepland ({w.aantal_personen} man) maar de materiaallevering is niet bevestigd ({w.samenvatting}
                    {w.leverancier_naam ? ` · ${w.leverancier_naam}` : ''}).
                    <span style={{ display: 'block', color: 'var(--muted)', fontSize: 11 }}>kruissignaal personeel × transport</span>
                  </span>
                </div>
              ))}
            </div>
          )}

          <div className="panel">
            <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
              📋 Bestellingen
              {data && data.bestellingen_concept + data.bestellingen_met_wijzigingen > 0 && (
                <Badge variant="warn">{data.bestellingen_concept + data.bestellingen_met_wijzigingen} concept</Badge>
              )}
              <Button variant="ghost" maat="klein" style={{ marginLeft: 'auto' }} onClick={() => setNieuweBestelling(true)}>
                + Nieuw
              </Button>
            </h2>
            {bestellingen.length === 0 && <p className="hint" style={{ margin: 0, fontSize: 11.5 }}>Nog geen bestellingen — kies een project en leverancier; de catalogus vult zich vanzelf.</p>}
            {bestellingen.map((b) => (
              <button key={b.id} className="linkbtn" style={{ display: 'block', width: '100%', textAlign: 'left', padding: '7px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }} onClick={() => setPopupBestelling(b.id)}>
                <span aria-hidden>{b.status === 'concept' || b.heeft_concept_wijzigingen ? '🟧' : b.status === 'geannuleerd' ? '⬜' : '🟩'}</span>{' '}
                <b>
                  {b.nummer} · {b.project_naam ?? '?'} → {b.leverancier_naam}
                </b>{' '}
                — {b.aantal_regels} regels · {Number(b.m2_totaal).toLocaleString('nl-NL')} m²{b.gewenste_leverdatum ? ` · lever ${dagLabel(b.gewenste_leverdatum)}` : ''}
                <span style={{ display: 'block', color: 'var(--muted)', fontSize: 11 }}>
                  {b.revisie > 0 ? `r${b.revisie} verstuurd` : 'concept'}
                  {b.heeft_concept_wijzigingen ? ` · wijziging r${b.revisie + 1} in concept` : ''} · klik om te openen
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>

      {bevestigKaart && (
        <BevestigDialog
          administratieId={administratieId}
          t={bevestigKaart}
          leverancier={leverancierBij(bevestigKaart.leverancier_id)}
          onSluiten={() => setBevestigKaart(null)}
          onGereed={() => {
            setBevestigKaart(null)
            meld('Transport bevestigd (oranje) — melding aan het transport-contact verstuurd.')
            laad()
          }}
        />
      )}
      {lijstKaart && (
        <MateriaallijstDialog
          administratieId={administratieId}
          t={lijstKaart}
          leverancier={leverancierBij(lijstKaart.leverancier_id)}
          onSluiten={() => setLijstKaart(null)}
          onGereed={(wijzig) => {
            setLijstKaart(null)
            meld(wijzig ? 'Materiaallijst gewijzigd — delta naar het materiaal-contact.' : 'Transport definitief (groen) — lijst naar het materiaal-contact.')
            laad()
          }}
        />
      )}
      {levKeuze && (
        <LeverancierKeuzeDialog
          leveranciers={leveranciers}
          label={levKeuze.label}
          datum={levKeuze.datum}
          onSluiten={() => setLevKeuze(null)}
          onKies={(leverancierId) => {
            const k = levKeuze
            setLevKeuze(null)
            void planNieuw(k.projectId, k.datum, leverancierId, k.bestellingId)
          }}
        />
      )}
      {bewerk && data && (
        <TransportWijzigDialog
          administratieId={administratieId}
          projecten={data.projecten.filter((p) => p.is_actief)}
          bestaand={bewerk}
          onSluiten={() => setBewerk(null)}
          onGereed={() => {
            setBewerk(null)
            meld('Transport gewijzigd — geauditeerd.')
            laad()
          }}
        />
      )}
      {popupBestelling && (
        <BestellingPopup administratieId={administratieId} bestellingId={popupBestelling} onSluiten={() => setPopupBestelling(null)} onGewijzigd={laad} />
      )}
      {nieuweBestelling && data && (
        <NieuweBestellingDialog
          administratieId={administratieId}
          projecten={data.projecten.filter((p) => p.is_actief)}
          leveranciers={leveranciers}
          onSluiten={() => setNieuweBestelling(false)}
          onAangemaakt={(id) => {
            setNieuweBestelling(false)
            setPopupBestelling(id)
            laad()
          }}
        />
      )}
    </>
  )
}

/** Bevestig-popup (rood → oranje, mockup): kantoor legt het door het transport-contact
 * toegezegde voertuig vast; de server mailt het contact. Fouten (422 geen contact / 502
 * mailfout) blijven zichtbaar in de popup — nooit stil. */
function BevestigDialog({
  administratieId,
  t,
  leverancier,
  onSluiten,
  onGereed,
}: {
  administratieId: string
  t: TransportDto
  leverancier: LeverancierDto | null
  onSluiten: () => void
  onGereed: () => void
}) {
  const [voertuig, setVoertuig] = useState<'combi' | 'voorwagen'>('combi')
  const [bezig, setBezig] = useState(false)
  const [foutBericht, setFoutBericht] = useState<string | null>(null)
  const contact = leverancier?.transport_contact_naam ?? 'het transport-contact'

  async function bevestig() {
    setBezig(true)
    setFoutBericht(null)
    try {
      await bevestigTransport(administratieId, t.id, voertuig)
      onGereed()
    } catch (err) {
      setFoutBericht(err instanceof ApiError ? err.message : 'Bevestigen mislukt.')
      setBezig(false)
    }
  }

  return (
    <div className="modal-bg" role="presentation" onClick={() => !bezig && onSluiten()}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
        <h2>Transport bevestigen — {t.project_naam ?? '?'}{t.opdrachtgever ? ` · ${t.opdrachtgever}` : ''}</h2>
        <p className="hint" style={{ marginTop: 2 }}>
          {t.soort === 'levering' ? '▲ levering' : '▼ retour'} · {dagLabel(t.datum)} · {t.project_adres ?? '—'}
        </p>
        <p style={{ fontSize: 12.5, color: 'var(--muted)' }}>
          {contact}
          {leverancier ? ` (${leverancier.naam})` : ''} bevestigt dat het transport definitief doorgaat — leg meteen het voertuig vast dat wordt toegezegd:
        </p>
        <div style={{ display: 'flex', gap: 10 }}>
          {(['combi', 'voorwagen'] as const).map((v) => (
            <label
              key={v}
              style={{
                flex: 1,
                display: 'flex',
                gap: 8,
                alignItems: 'center',
                border: `1px solid ${voertuig === v ? 'var(--primary)' : 'var(--border)'}`,
                background: voertuig === v ? 'var(--accent-bg)' : undefined,
                borderRadius: 9,
                padding: '10px 13px',
                fontWeight: 700,
                cursor: 'pointer',
                fontSize: 12.5,
              }}
            >
              <input type="radio" name="voertuig" value={v} checked={voertuig === v} onChange={() => setVoertuig(v)} /> {VOERTUIG_LABEL[v]}
            </label>
          ))}
        </div>
        <p className="hint" style={{ fontSize: 11.5 }}>
          Na bevestigen kleurt de kaart oranje en krijgt {contact} de melding &quot;transport gaat definitief door&quot; mét datum, adres en voertuig.
          Volgende stap: materiaallijst + transportplanner invullen → groen.
        </p>
        {foutBericht && <div className="fout">{foutBericht}</div>}
        <div className="actions">
          <button className="btn secondary" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </button>
          <button className="btn" onClick={() => void bevestig()} disabled={bezig}>
            {bezig ? 'Bezig…' : `Bevestigen → melding ${contact}`}
          </button>
        </div>
      </div>
    </div>
  )
}

/** Materiaallijst-popup (oranje → groen, of wijzig-modus ná definitief = delta-mail):
 * volledige leverancierscatalogus per categorie mét zoekveld, aantallen invullen = selecteren,
 * live m²-som, transportplanner onderin. */
function MateriaallijstDialog({
  administratieId,
  t,
  leverancier,
  onSluiten,
  onGereed,
}: {
  administratieId: string
  t: TransportDto
  leverancier: LeverancierDto | null
  onSluiten: () => void
  onGereed: (wijzigModus: boolean) => void
}) {
  const wijzigModus = t.status === 'definitief'
  const [regels, setRegels] = useState<Record<string, number>>(Object.fromEntries(t.regels.map((r) => [r.product_id, r.aantal])))
  const [planner, setPlanner] = useState(t.transportplanner ?? '')
  const [catalogus, setCatalogus] = useState<CategorieDto[]>([])
  const [zoek, setZoek] = useState('')
  const [bezig, setBezig] = useState(false)
  const [foutBericht, setFoutBericht] = useState<string | null>(null)
  useEffect(() => {
    haalCatalogus(administratieId, t.leverancier_id).then(setCatalogus).catch(() => setCatalogus([]))
  }, [administratieId, t.leverancier_id])
  const productenMap = useMemo(() => new Map<string, ProductDto>(catalogus.flatMap((c) => c.producten).map((p) => [p.id, p])), [catalogus])
  const m2 = schatM2(regels, productenMap)
  const term = zoek.trim().toLowerCase()
  const contact = leverancier?.materiaal_contact_naam ?? 'materiaal-contact'

  async function versturen() {
    setBezig(true)
    setFoutBericht(null)
    try {
      if (wijzigModus) await wijzigMateriaallijst(administratieId, t.id, regels, planner.trim() || null)
      else await maakTransportDefinitief(administratieId, t.id, regels, planner.trim())
      onGereed(wijzigModus)
    } catch (err) {
      setFoutBericht(err instanceof ApiError ? err.message : 'Versturen mislukt.')
      setBezig(false)
    }
  }

  return (
    <div className="modal-bg" role="presentation" onClick={() => !bezig && onSluiten()}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 680 }}>
        <h2>Materiaallijst — {t.project_naam ?? '?'}{t.opdrachtgever ? ` · ${t.opdrachtgever}` : ''}</h2>
        <p className="hint" style={{ marginTop: 2 }}>
          {t.soort === 'levering' ? '▲ levering' : '▼ retour'} · {dagLabel(t.datum)} · {t.project_adres ?? '—'}
          {t.voertuig ? ` · voertuig: ${t.voertuig}` : ''}
          {wijzigModus ? ` — wijzigen ná definitief: ${contact} krijgt alléén de gewijzigde regels (oud → nieuw)` : ''}
        </p>
        <input
          type="search"
          aria-label="Zoek in catalogus"
          placeholder="Zoek in catalogus…"
          value={zoek}
          onChange={(e) => setZoek(e.target.value)}
          style={{ width: '100%' }}
        />
        <div style={{ maxHeight: '46vh', overflowY: 'auto', marginTop: 6 }}>
          {catalogus.length === 0 && <p className="hint">Catalogus wordt geladen — of de leverancier heeft nog geen producten.</p>}
          {catalogus.map((cat) => {
            const producten = cat.producten.filter((p) => (regels[p.id] ?? 0) > 0 || !term || p.naam.toLowerCase().includes(term))
            if (producten.length === 0) return null
            return (
              <div key={cat.id}>
                <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em', color: 'var(--faint)', fontWeight: 700, margin: '10px 0 4px' }}>{cat.naam}</div>
                {producten.map((p) => (
                  <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--border)', fontSize: 12.5 }}>
                    <span style={{ flex: 1 }}>
                      {p.naam} <span className="hint" style={{ fontSize: 11 }}>{p.verpakking ? `${p.verpakking}` : ''}</span>
                    </span>
                    <input
                      type="number"
                      min={0}
                      aria-label={`Aantal ${p.naam}`}
                      value={regels[p.id] ?? 0}
                      onChange={(e) => {
                        const n = Math.max(0, Math.floor(Number(e.target.value) || 0))
                        setRegels((h) => {
                          const k = { ...h }
                          if (n === 0) delete k[p.id]
                          else k[p.id] = n
                          return k
                        })
                      }}
                      style={{ width: 80, textAlign: 'right' }}
                    />
                  </div>
                ))}
              </div>
            )
          })}
        </div>
        <p className="hint" style={{ fontSize: 11 }}>
          Σ ≈ {m2.toLocaleString('nl-NL')} m² (aantal × lengte ÷ 4,6 — de server rekent bindend) · aantallen invullen is selecteren.
        </p>
        {foutBericht && <div className="fout">{foutBericht}</div>}
        <div className="actions" style={{ justifyContent: 'space-between', display: 'flex', gap: 8 }}>
          <label className="hint" style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            Transportplanner
            <input
              type="text"
              value={planner}
              onChange={(e) => setPlanner(e.target.value)}
              placeholder="bv. De Jong Transport"
              style={{ width: 180 }}
              aria-label="Transportplanner"
            />
          </label>
          <span style={{ display: 'flex', gap: 8 }}>
            <button className="btn secondary" onClick={onSluiten} disabled={bezig}>
              Annuleren
            </button>
            <button className="btn" onClick={() => void versturen()} disabled={bezig || (!wijzigModus && (Object.keys(regels).length === 0 || !planner.trim()))}>
              {bezig ? 'Bezig…' : wijzigModus ? `Wijzigingen versturen → delta naar ${contact}` : `Definitief maken → lijst naar ${contact}`}
            </button>
          </span>
        </div>
      </div>
    </div>
  )
}

/** Meerdere actieve leveranciers: plannen uit het werkbakje vraagt éérst welke leverancier. */
function LeverancierKeuzeDialog({
  leveranciers,
  label,
  datum,
  onSluiten,
  onKies,
}: {
  leveranciers: LeverancierDto[]
  label: string
  datum: string
  onSluiten: () => void
  onKies: (leverancierId: string) => void
}) {
  const [keuze, setKeuze] = useState(leveranciers[0]?.id ?? '')
  return (
    <div className="modal-bg" role="presentation" onClick={onSluiten}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }}>
        <h2>Leverancier kiezen</h2>
        <p className="hint">
          Transport voor {label} op {dagLabel(datum)} — kies de leverancier (levering, materiaal vul je in bij het definitief maken).
        </p>
        <Select value={keuze} onChange={(e) => setKeuze(e.target.value)} className="w-full" aria-label="Leverancier">
          {leveranciers.map((l) => (
            <option key={l.id} value={l.id}>
              {l.naam}
            </option>
          ))}
        </Select>
        <div className="actions">
          <button className="btn secondary" onClick={onSluiten}>
            Annuleren
          </button>
          <button className="btn" disabled={!keuze} onClick={() => onKies(keuze)}>
            Plannen (gereserveerd)
          </button>
        </div>
      </div>
    </div>
  )
}

/** Gereserveerde kaart wijzigen: project, soort (▲/▼ mag zolang gereserveerd), datum/tijd,
 * omschrijving en materiaalregels — datum verschuiven ná bevestigen loopt via verschuiven. */
function TransportWijzigDialog({
  administratieId,
  projecten,
  bestaand,
  onSluiten,
  onGereed,
}: {
  administratieId: string
  projecten: TransportProjectRijDto[]
  bestaand: TransportDto
  onSluiten: () => void
  onGereed: () => void
}) {
  const [projectId, setProjectId] = useState(bestaand.project_id)
  const [soort, setSoort] = useState<'levering' | 'retour'>(bestaand.soort)
  const [datum, setDatum] = useState(bestaand.datum)
  const [tijd, setTijd] = useState(bestaand.tijdstip ? bestaand.tijdstip.slice(0, 5) : '')
  const [omschrijving, setOmschrijving] = useState(bestaand.omschrijving ?? '')
  const [regels, setRegels] = useState<Record<string, number>>(Object.fromEntries(bestaand.regels.map((r) => [r.product_id, r.aantal])))
  const [catalogus, setCatalogus] = useState<CategorieDto[]>([])
  const [zoek, setZoek] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  useEffect(() => {
    haalCatalogus(administratieId, bestaand.leverancier_id).then(setCatalogus).catch(() => setCatalogus([]))
  }, [administratieId, bestaand.leverancier_id])
  const producten = catalogus.flatMap((c) => c.producten)
  const term = zoek.trim().toLowerCase()
  const getoond = producten.filter((p) => (regels[p.id] ?? 0) > 0 || (term && `${p.naam} ${p.categorie_naam}`.toLowerCase().includes(term))).slice(0, 40)

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      await wijzigTransport(administratieId, bestaand.id, {
        datum,
        tijdstip: tijd ? `${tijd}:00` : null,
        regels,
        omschrijving: omschrijving || null,
        project_id: projectId,
        soort,
      })
      onGereed()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div className="modal-bg" role="presentation" onClick={() => !bezig && onSluiten()}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 640 }}>
        <h2>Transport wijzigen</h2>
        <p className="hint" style={{ marginTop: 2 }}>
          Leverancier: {bestaand.leverancier_naam} (vast) — kan alleen zolang de kaart gereserveerd is.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <label className="hint" style={{ margin: 0 }}>
            Project
            <Select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="w-full">
              {projecten.map((p) => (
                <option key={p.project_id} value={p.project_id}>
                  {p.project_naam}
                </option>
              ))}
            </Select>
          </label>
          <label className="hint" style={{ margin: 0 }}>
            Soort
            <Select value={soort} onChange={(e) => setSoort(e.target.value as 'levering' | 'retour')} className="w-full">
              <option value="levering">▲ Levering</option>
              <option value="retour">▼ Retour</option>
            </Select>
          </label>
          <label className="hint" style={{ margin: 0 }}>
            Datum
            <input type="date" value={datum} onChange={(e) => setDatum(e.target.value)} style={{ width: '100%' }} />
          </label>
          <label className="hint" style={{ margin: 0 }}>
            Tijd
            <input type="time" value={tijd} onChange={(e) => setTijd(e.target.value)} style={{ width: '100%' }} />
          </label>
        </div>
        <label className="hint" style={{ display: 'block', marginTop: 8 }}>
          Omschrijving (optioneel, bv. &quot;Levering lift 1×&quot;)
          <input type="text" value={omschrijving} onChange={(e) => setOmschrijving(e.target.value)} style={{ width: '100%' }} />
        </label>
        <div style={{ marginTop: 8 }}>
          <input type="search" placeholder="Materiaal zoeken in de catalogus…" value={zoek} onChange={(e) => setZoek(e.target.value)} style={{ width: '100%' }} aria-label="Materiaal zoeken" />
          <div style={{ maxHeight: 220, overflow: 'auto', marginTop: 6 }}>
            {getoond.map((p) => (
              <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 12.5 }}>
                <span style={{ flex: 1 }}>
                  {p.naam} <span className="hint" style={{ fontSize: 11 }}>{p.categorie_naam}{p.verpakking ? ` · ${p.verpakking}` : ''}</span>
                </span>
                <input
                  type="number"
                  min={0}
                  aria-label={`Aantal ${p.naam}`}
                  value={regels[p.id] ?? 0}
                  onChange={(e) => {
                    const n = Math.max(0, Math.floor(Number(e.target.value) || 0))
                    setRegels((h) => {
                      const k = { ...h }
                      if (n === 0) delete k[p.id]
                      else k[p.id] = n
                      return k
                    })
                  }}
                  style={{ width: 80, textAlign: 'right' }}
                />
              </div>
            ))}
            {term && getoond.length === 0 && <p className="hint">Geen producten gevonden.</p>}
          </div>
        </div>
        {fout && <div className="fout">{fout}</div>}
        <div className="actions">
          <button className="btn secondary" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </button>
          <button className="btn" onClick={() => void opslaan()} disabled={bezig || !projectId || !datum}>
            {bezig ? 'Bezig…' : 'Wijzigen'}
          </button>
        </div>
      </div>
    </div>
  )
}

function NieuweBestellingDialog({ administratieId, projecten, leveranciers, onSluiten, onAangemaakt }: { administratieId: string; projecten: TransportProjectRijDto[]; leveranciers: LeverancierDto[]; onSluiten: () => void; onAangemaakt: (id: string) => void }) {
  const [projectId, setProjectId] = useState(projecten[0]?.project_id ?? '')
  const [leverancierId, setLeverancierId] = useState(leveranciers[0]?.id ?? '')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  return (
    <div className="modal-bg" role="presentation" onClick={() => !bezig && onSluiten()}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h2>Nieuwe bestelling</h2>
        <p className="hint">Bestelling per project × leverancier — daarna vul je de aantallen in de volledige catalogus (0 = niet bestellen).</p>
        <label className="hint" style={{ display: 'block' }}>
          Project
          <Select value={projectId} onChange={(e) => setProjectId(e.target.value)} className="w-full">
            {projecten.map((p) => (
              <option key={p.project_id} value={p.project_id}>
                {p.project_naam}
              </option>
            ))}
          </Select>
        </label>
        <label className="hint" style={{ display: 'block', marginTop: 8 }}>
          Leverancier
          <Select value={leverancierId} onChange={(e) => setLeverancierId(e.target.value)} className="w-full">
            {leveranciers.map((l) => (
              <option key={l.id} value={l.id}>
                {l.naam}
                {l.bestel_email ? '' : ' (geen bestel-mailadres)'}
              </option>
            ))}
          </Select>
        </label>
        {fout && <div className="fout">{fout}</div>}
        <div className="actions">
          <button className="btn secondary" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </button>
          <button
            className="btn"
            disabled={bezig || !projectId || !leverancierId}
            onClick={() => {
              setBezig(true)
              maakBestelling(administratieId, { project_id: projectId, leverancier_id: leverancierId })
                .then((r) => onAangemaakt(r.id))
                .catch((err: unknown) => setFout(err instanceof ApiError ? err.message : 'Aanmaken mislukt.'))
                .finally(() => setBezig(false))
            }}
          >
            {bezig ? 'Bezig…' : 'Aanmaken'}
          </button>
        </div>
      </div>
    </div>
  )
}
