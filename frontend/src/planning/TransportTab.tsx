import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import { Badge, Button, Select, useToastOptioneel } from '../ui/basis'
import { BestellingPopup } from './BestellingPopup'
import { MateriaalstandPaneel } from './MateriaalstandPaneel'
import {
  haalBestellingen,
  haalCatalogus,
  haalLeveranciers,
  haalTransportWeek,
  maakBestelling,
  planTransport,
  wijzigTransport,
  zetTransportStatus,
  type BestellingDto,
  type CategorieDto,
  type LeverancierDto,
  type TransportDto,
  type TransportProjectRijDto,
  type TransportWeekDto,
} from './transportApi'

/* Transport-tab op /planning (steigerbouw-run D1/D4/D5, mockup planning-steigerbouw.html
 * "TAB 2: TRANSPORT" = norm): zelfde weekgrid-model als Personeel (twee blokken: mét transport
 * deze week bovenaan, overige actieve projecten compact eronder; filter; week in de URL),
 * transport-item = levering (▲) of retour (▼) per project per dag met materiaalregels,
 * leverancier, tijdstip en status gepland → bevestigd → geleverd (kantoor-klikwerk — de
 * verhuursysteem-koppeling landt later op dezelfde seam). Zijbalk: materiaalstand per project,
 * factuurcontrole-teller, wachtrisico's (kruissignaal), bestellingen (popup). */

function dagLabel(iso: string): string {
  return new Date(`${iso}T12:00:00`).toLocaleDateString('nl-NL', { weekday: 'short', day: 'numeric', month: 'numeric' })
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
  const [planCel, setPlanCel] = useState<{ projectId: string; projectNaam: string | null; datum: string } | null>(null)
  const [bewerk, setBewerk] = useState<TransportDto | null>(null)
  const [zijProject, setZijProject] = useState<string | null>(null)
  const [bestellingen, setBestellingen] = useState<BestellingDto[]>([])
  const [popupBestelling, setPopupBestelling] = useState<string | null>(null)
  const [nieuweBestelling, setNieuweBestelling] = useState(false)

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
  const metTransport = (data?.projecten ?? []).filter((r) => r.week_transporten > 0 && zichtbaar(r))
  const zonder = (data?.projecten ?? []).filter((r) => r.week_transporten === 0 && r.is_actief && zichtbaar(r))
  const wachtrisicoKeys = useMemo(() => new Set((data?.wachtrisico ?? []).map((w) => `${w.project_id}|${w.datum}`)), [data])
  const werkdagen = dagen.slice(0, 5)
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

  function Kaart({ t }: { t: TransportDto }) {
    const risico = wachtrisicoKeys.has(`${t.project_id}|${t.datum}`) && t.status === 'gepland'
    return (
      <div
        style={{
          borderRadius: 9,
          padding: '5px 8px',
          marginBottom: 4,
          fontSize: 11.5,
          border: `1px solid ${risico ? 'var(--danger)' : 'var(--border)'}`,
          background: risico ? 'var(--danger-bg)' : t.status === 'geleverd' ? 'var(--panel-2)' : t.status === 'bevestigd' ? 'var(--ok-bg)' : 'var(--warn-bg)',
          opacity: t.status === 'geannuleerd' ? 0.5 : 1,
        }}
        title={`${t.leverancier_naam} · ${t.status}${t.status_reden ? ` — ${t.status_reden}` : ''}`}
      >
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontWeight: 800 }}>{t.soort === 'levering' ? '▲' : '▼'}</span>
          <b style={{ flex: 1 }}>{t.samenvatting}</b>
        </div>
        <div className="hint" style={{ margin: 0, fontSize: 10.5 }}>
          {t.leverancier_naam}
          {t.tijdstip ? ` · ${t.tijdstip.slice(0, 5)}` : ''} · {t.status === 'gepland' && risico ? 'NIET bevestigd · ⚠ ploeg staat gepland' : t.status}
          {t.bestelling_nummer ? ` · ${t.bestelling_nummer}` : ''}
        </div>
        {t.status !== 'geleverd' && t.status !== 'geannuleerd' && (
          <div style={{ display: 'flex', gap: 4, marginTop: 4, flexWrap: 'wrap' }}>
            {t.status === 'gepland' && (
              <button className="linkbtn" style={{ fontSize: 10.5 }} onClick={() => void status(t, 'bevestigd')}>
                bevestigen
              </button>
            )}
            <button className="linkbtn" style={{ fontSize: 10.5 }} onClick={() => void status(t, 'geleverd')}>
              geleverd ✓
            </button>
            <button className="linkbtn" style={{ fontSize: 10.5 }} onClick={() => setBewerk(t)}>
              wijzig
            </button>
            <button className="linkbtn" style={{ fontSize: 10.5, color: 'var(--danger)' }} onClick={() => void status(t, 'geannuleerd')}>
              ✕
            </button>
          </div>
        )}
      </div>
    )
  }

  function Rij({ r, compact }: { r: TransportProjectRijDto; compact: boolean }) {
    return (
      <tr style={compact ? { opacity: 0.85 } : undefined}>
        <th style={{ textAlign: 'left', fontWeight: 600, fontSize: compact ? 12 : 13, padding: compact ? '6px 10px' : '10px' }}>
          {r.project_naam ?? r.project_id}
          <span className="hint" style={{ display: 'block', fontSize: 11, margin: 0 }}>
            {r.opdrachtgever ?? ''}
            {r.ploeg_label ? ` · ${r.ploeg_label}` : ''}
          </span>
        </th>
        {werkdagen.map(({ datum }) => {
          const items = r.per_datum[datum] ?? []
          const risico = wachtrisicoKeys.has(`${r.project_id}|${datum}`)
          return (
            <td
              key={datum}
              onClick={() => setPlanCel({ projectId: r.project_id, projectNaam: r.project_naam, datum })}
              style={{ verticalAlign: 'top', cursor: 'pointer', minHeight: 44, padding: 6, background: risico && items.length === 0 ? 'var(--danger-bg)' : undefined }}
              title="Klik om een transport te plannen"
            >
              {items.map((t) => (
                <Kaart key={t.id} t={t} />
              ))}
              {risico && items.length === 0 && <span className="hint" style={{ fontSize: 10.5, color: 'var(--danger)' }}>⚠ ploeg gepland, geen bevestigde levering</span>}
            </td>
          )
        })}
      </tr>
    )
  }

  return (
    <>
      {fout && <div className="fout">{fout}</div>}
      {actieFout && <div className="fout">{actieFout}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px', gap: 16, alignItems: 'start' }}>
        <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ alignItems: 'center', borderBottom: '1px solid var(--border)', display: 'flex', flexWrap: 'wrap', gap: 10, padding: '10px 12px' }}>
            <input
              type="search"
              aria-label="Filter projecten"
              placeholder="Filter projecten…"
              value={filterTerm}
              onChange={(e) => setFilterTerm(e.target.value)}
              style={{ background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text)', flex: '0 1 280px', font: 'inherit', fontSize: 12.5, padding: '7px 11px' }}
            />
            {data && (
              <span style={{ color: 'var(--faint)', fontSize: 11.5 }}>
                transporten deze week: {data.aantal_transporten} · {data.wachtrisico.length} wachtrisico
              </span>
            )}
            <Button maat="klein" style={{ marginLeft: 'auto' }} onClick={() => setPlanCel({ projectId: metTransport[0]?.project_id ?? zonder[0]?.project_id ?? '', projectNaam: null, datum: werkdagen[0]?.datum ?? '' })} disabled={!data}>
              + Transport plannen
            </Button>
          </div>
          {data === null && !fout && <p className="hint" style={{ padding: 16 }}>Laden…</p>}
          {data !== null && (
            <div className="tabel-scroll">
              <table className="plan-grid" style={{ tableLayout: 'fixed', minWidth: 760 }}>
                <thead>
                  <tr>
                    <th style={{ width: 200, textAlign: 'left' }}>Project</th>
                    {werkdagen.map(({ datum }, i) => (
                      <th key={datum}>
                        {dagLabel(datum)}
                        {i === 0 ? ` · wk ${week.weeknummer}` : ''}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {metTransport.map((r) => (
                    <Rij key={r.project_id} r={r} compact={false} />
                  ))}
                  {zonder.length > 0 && (
                    <tr>
                      <th colSpan={6} style={{ textAlign: 'left', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)', padding: '8px 10px', background: 'var(--panel-2)' }}>
                        Overige actieve projecten — geen transport deze week
                      </th>
                    </tr>
                  )}
                  {zonder.map((r) => (
                    <Rij key={r.project_id} r={r} compact />
                  ))}
                  {metTransport.length === 0 && zonder.length === 0 && (
                    <tr>
                      <td colSpan={6} className="hint" style={{ padding: 16 }}>
                        Geen projecten gevonden voor dit filter.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div>
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

      {planCel && data && (
        <TransportPlanDialog
          administratieId={administratieId}
          projecten={data.projecten.filter((p) => p.is_actief)}
          leveranciers={leveranciers}
          start={planCel}
          bestaand={null}
          onSluiten={() => setPlanCel(null)}
          onGereed={() => {
            setPlanCel(null)
            meld('Transport gepland — geauditeerd.')
            laad()
          }}
        />
      )}
      {bewerk && data && (
        <TransportPlanDialog
          administratieId={administratieId}
          projecten={data.projecten.filter((p) => p.is_actief)}
          leveranciers={leveranciers}
          start={{ projectId: bewerk.project_id, projectNaam: bewerk.project_naam, datum: bewerk.datum }}
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

/** Transport plannen/wijzigen: project, leverancier, soort, datum/tijd, materiaalregels uit de
 * catalogus (zoekbaar) of alleen een omschrijving. */
function TransportPlanDialog({
  administratieId,
  projecten,
  leveranciers,
  start,
  bestaand,
  onSluiten,
  onGereed,
}: {
  administratieId: string
  projecten: TransportProjectRijDto[]
  leveranciers: LeverancierDto[]
  start: { projectId: string; projectNaam: string | null; datum: string }
  bestaand: TransportDto | null
  onSluiten: () => void
  onGereed: () => void
}) {
  const [projectId, setProjectId] = useState(start.projectId || projecten[0]?.project_id || '')
  const [leverancierId, setLeverancierId] = useState(bestaand?.leverancier_id ?? leveranciers[0]?.id ?? '')
  const [soort, setSoort] = useState<'levering' | 'retour'>(bestaand?.soort ?? 'levering')
  const [datum, setDatum] = useState(start.datum)
  const [tijd, setTijd] = useState(bestaand?.tijdstip ? bestaand.tijdstip.slice(0, 5) : '')
  const [omschrijving, setOmschrijving] = useState(bestaand?.omschrijving ?? '')
  const [regels, setRegels] = useState<Record<string, number>>(Object.fromEntries((bestaand?.regels ?? []).map((r) => [r.product_id, r.aantal])))
  const [catalogus, setCatalogus] = useState<CategorieDto[]>([])
  const [zoek, setZoek] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  useEffect(() => {
    if (!leverancierId) return
    haalCatalogus(administratieId, leverancierId).then(setCatalogus).catch(() => setCatalogus([]))
  }, [administratieId, leverancierId])
  const producten = catalogus.flatMap((c) => c.producten)
  const term = zoek.trim().toLowerCase()
  const getoond = producten.filter((p) => (regels[p.id] ?? 0) > 0 || (term && `${p.naam} ${p.categorie_naam}`.toLowerCase().includes(term))).slice(0, 40)

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      if (bestaand) {
        await wijzigTransport(administratieId, bestaand.id, { datum, tijdstip: tijd ? `${tijd}:00` : null, regels, omschrijving: omschrijving || null, project_id: projectId })
      } else {
        await planTransport(administratieId, { project_id: projectId, leverancier_id: leverancierId, soort, datum, tijdstip: tijd ? `${tijd}:00` : null, regels, omschrijving: omschrijving || null })
      }
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
        <h2>{bestaand ? 'Transport wijzigen' : 'Transport plannen'}</h2>
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
            Leverancier
            <Select value={leverancierId} onChange={(e) => setLeverancierId(e.target.value)} className="w-full" disabled={bestaand !== null}>
              {leveranciers.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.naam}
                </option>
              ))}
            </Select>
          </label>
          <label className="hint" style={{ margin: 0 }}>
            Soort
            <Select value={soort} onChange={(e) => setSoort(e.target.value as 'levering' | 'retour')} className="w-full" disabled={bestaand !== null}>
              <option value="levering">▲ Levering</option>
              <option value="retour">▼ Retour</option>
            </Select>
          </label>
          <div style={{ display: 'flex', gap: 8 }}>
            <label className="hint" style={{ margin: 0, flex: 1 }}>
              Datum
              <input type="date" value={datum} onChange={(e) => setDatum(e.target.value)} style={{ width: '100%' }} />
            </label>
            <label className="hint" style={{ margin: 0, width: 100 }}>
              Tijd
              <input type="time" value={tijd} onChange={(e) => setTijd(e.target.value)} style={{ width: '100%' }} />
            </label>
          </div>
        </div>
        <label className="hint" style={{ display: 'block', marginTop: 8 }}>
          Omschrijving (optioneel, bv. &quot;Levering lift 1×&quot;)
          <input type="text" value={omschrijving} onChange={(e) => setOmschrijving(e.target.value)} style={{ width: '100%' }} />
        </label>
        <div style={{ marginTop: 8 }}>
          <input type="search" placeholder="Materiaal zoeken in de catalogus…" value={zoek} onChange={(e) => setZoek(e.target.value)} style={{ width: '100%' }} aria-label="Materiaal zoeken" />
          {leveranciers.length === 0 && <p className="hint">Nog geen leveranciers/catalogus — Beheerder: Instellingen → Materiaalcatalogus.</p>}
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
          <button className="btn" onClick={() => void opslaan()} disabled={bezig || !projectId || !leverancierId || !datum || (Object.keys(regels).length === 0 && !omschrijving.trim())}>
            {bezig ? 'Bezig…' : bestaand ? 'Wijzigen' : 'Plannen'}
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
