import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { Badge, Button } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { Breadcrumb } from '../werkvoorraad/Breadcrumb'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  haalProjecten,
  haalVolgendNummer,
  maakProject,
  type ProjectenLijstDto,
  type ProjectLijstRijDto,
} from './projectenApi'

/* Projectenlijst (mockup projecten-invoer.html view 1, akkoord Peter 22-08): sync-projecten
 * mét compleetheids-badges (specs/contract/staffels) en m²-voortgang uit de goedgekeurde
 * weekstaten; zoeken op nummer/plaats/opdrachtgever; "+ Nieuw project" maakt via de bestaande
 * RLZ-projectmotor aan (naamconventie "26xxx Plaats (Opdrachtgever)", RLZ blijft de bron).
 * De "zonder specs"-teller telt alleen projecten mét uren-/meerwerk-activiteit (keuze 5). */

function specsBadge(status: string) {
  if (status === 'compleet') return <Badge variant="ok">compleet</Badge>
  if (status === 'onvolledig') return <Badge variant="warn">onvolledig</Badge>
  return <Badge variant="warn">geen</Badge>
}

function contractBadge(documenten: Record<string, number>) {
  const contract = documenten.contract ?? 0
  const offerte = documenten.offerte ?? 0
  if (contract && offerte) return <Badge variant="ok">contract + offerte</Badge>
  if (contract) return <Badge variant="ok">contract</Badge>
  if (offerte) return <Badge variant="ok">offerte</Badge>
  return <Badge variant="warn">geen documenten</Badge>
}

function voortgang(rij: ProjectLijstRijDto) {
  if (rij.doorlopende_huur) return <Badge variant="info">doorlopende huur</Badge>
  if (rij.contract_m2 === null) return <span className="hint">— geen contract-m²</span>
  const gebouwd = Number(rij.gebouwd_m2)
  const contract = Number(rij.contract_m2)
  const pct = contract > 0 ? Math.round((gebouwd / contract) * 100) : 0
  return (
    <span>
      {gebouwd.toLocaleString('nl-NL')} / {contract.toLocaleString('nl-NL')} m²
      <span style={{ color: 'var(--muted)', display: 'block', fontSize: 11 }}>{pct}% · uit weekstaten</span>
    </span>
  )
}

export function ProjectenScreen() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const administratieId = searchParams.get('administratie')
  const { administraties } = useAdministraties()
  const [data, setData] = useState<ProjectenLijstDto | null>(null)
  const [zoek, setZoek] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [herlaad, setHerlaad] = useState(0)
  const [nieuwOpen, setNieuwOpen] = useState(false)

  const administratieNaam = useMemo(
    () => (administraties ?? []).find((a) => a.id === administratieId)?.naam ?? 'Administratie',
    [administraties, administratieId],
  )

  useEffect(() => {
    if (!administratieId) return
    setFout(null)
    const timer = window.setTimeout(
      () => {
        haalProjecten(administratieId, zoek.trim())
          .then(setData)
          .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
      },
      zoek ? 250 : 0,
    )
    return () => window.clearTimeout(timer)
  }, [administratieId, zoek, herlaad])

  if (!administratieId) {
    return <p className="hint">Geen administratie gekozen — open de projecten vanaf de klantpagina.</p>
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <Breadcrumb
            stappen={[
              { label: 'Werkvoorraad', naar: '/' },
              { label: administratieNaam, naar: `/?administratie=${administratieId}` },
            ]}
            huidige="Projecten"
          />
          <h1>Projecten — {administratieNaam}</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Specificaties, contracten en verrekenstaffels · gesynct met RLZ
            {data ? ` (${data.projecten.length} projecten)` : ''}
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <Button
            variant="secundair"
            maat="klein"
            onClick={() => navigate(`/projecten-resultaat?administratie=${administratieId}`)}
          >
            📈 Resultaat alle projecten
          </Button>
          <Button maat="klein" onClick={() => setNieuwOpen(true)}>
            + Nieuw project
          </Button>
        </div>
      </div>

      {fout && <FoutMelding melding="De projecten konden niet geladen worden." detail={fout} onOpnieuw={() => setHerlaad((h) => h + 1)} />}

      <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ alignItems: 'center', borderBottom: '1px solid var(--border)', display: 'flex', flexWrap: 'wrap', gap: 10, padding: '12px 14px' }}>
          <input
            type="search"
            aria-label="Zoek projecten"
            placeholder="Zoek op nummer, plaats of opdrachtgever…"
            value={zoek}
            onChange={(e) => setZoek(e.target.value)}
            style={{ background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 9, color: 'var(--text)', font: 'inherit', maxWidth: 340, padding: '8px 12px', width: '100%' }}
          />
          {data !== null && data.zonder_specs > 0 && <Badge variant="warn">{data.zonder_specs} zonder specs</Badge>}
          <Badge>alleen actieve</Badge>
        </div>
        {data === null && !fout && (
          <p className="hint" aria-busy="true" style={{ padding: 16 }}>
            Laden…
          </p>
        )}
        {data !== null && data.projecten.length === 0 && (
          <p className="hint" style={{ padding: 16 }}>
            Geen projecten gevonden{zoek ? ` voor "${zoek.trim()}"` : ''}.
          </p>
        )}
        {data !== null && data.projecten.length > 0 && (
          <div className="tabel-scroll">
            <table>
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Opdrachtgever</th>
                  <th>Specs</th>
                  <th>Contract</th>
                  <th>Staffels</th>
                  <th>Voortgang</th>
                </tr>
              </thead>
              <tbody>
                {data.projecten.map((rij) => (
                  <tr
                    key={rij.project_id}
                    className="clickable"
                    onClick={() => navigate(`/projecten/${administratieId}/${rij.project_id}`)}
                  >
                    <td>
                      <b>{rij.naam ?? rij.project_id}</b>
                      {rij.werknummer_opdrachtgever && (
                        <div style={{ color: 'var(--muted)', fontSize: 11.5, marginTop: 2 }}>
                          werknr {rij.werknummer_opdrachtgever}
                        </div>
                      )}
                    </td>
                    <td>{rij.opdrachtgever ?? '—'}</td>
                    <td>{specsBadge(rij.specs_status)}</td>
                    <td>{contractBadge(rij.documenten)}</td>
                    <td>{rij.staffels > 0 ? <Badge variant="ok">{rij.staffels} regels</Badge> : <Badge variant="warn">geen</Badge>}</td>
                    <td>{voortgang(rij)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <p className="hint" style={{ marginTop: 12, maxWidth: 980 }}>
        ℹ️ Projecten komen uit de RLZ-sync — hier voeg je de steigerbouw-inhoud toe: specs, documenten en staffels.
        &quot;Zonder specs&quot; telt alleen projecten met uren-&amp;-meerwerk-activiteit; de rest mag leeg blijven.
      </p>

      {nieuwOpen && (
        <NieuwProjectModal
          administratieId={administratieId}
          onKlaar={(projectId) => {
            setNieuwOpen(false)
            navigate(`/projecten/${administratieId}/${projectId}`)
          }}
          onAnnuleren={() => setNieuwOpen(false)}
        />
      )}
    </div>
  )
}

function NieuwProjectModal({
  administratieId,
  onKlaar,
  onAnnuleren,
}: {
  administratieId: string
  onKlaar: (projectId: string) => void
  onAnnuleren: () => void
}) {
  const [nummer, setNummer] = useState('')
  const [plaats, setPlaats] = useState('')
  const [opdrachtgever, setOpdrachtgever] = useState('')
  const [startdatum, setStartdatum] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    haalVolgendNummer(administratieId)
      .then((r) => setNummer((huidig) => huidig || r.projectnummer))
      .catch(() => undefined) // voorstel is verrijking — handmatig invullen kan altijd
  }, [administratieId])

  const naam = nummer && plaats && opdrachtgever ? `${nummer.trim()} ${plaats.trim()} (${opdrachtgever.trim()})` : null

  const aanmaken = async () => {
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await maakProject(administratieId, {
        projectnummer: nummer.trim(),
        plaats: plaats.trim(),
        opdrachtgever: opdrachtgever.trim(),
        startdatum: startdatum || null,
      })
      onKlaar(resultaat.rlz_project_id)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Aanmaken mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const veldStijl = {
    background: 'var(--panel-2)',
    border: '1px solid var(--border)',
    borderRadius: 9,
    color: 'var(--text)',
    font: 'inherit',
    padding: '8px 11px',
    width: '100%',
  } as const

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Nieuw project"
      style={{ background: 'rgba(10,16,15,.45)', display: 'grid', inset: 0, placeItems: 'center', position: 'fixed', zIndex: 50 }}
      onClick={(e) => {
        if (e.target === e.currentTarget && !bezig) onAnnuleren()
      }}
    >
      <div className="panel" style={{ margin: 0, width: 'min(520px, 92vw)' }}>
        <h2>Nieuw project</h2>
        <p className="hint" style={{ marginTop: 0 }}>
          Wordt volgens de naamconventie aangemaakt in RLZ (projectmotor, idempotent) en daarna hierheen gesynct —
          één bron van waarheid.
        </p>
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
          <label style={{ fontSize: 12, fontWeight: 600 }}>
            Projectnummer
            <input value={nummer} onChange={(e) => setNummer(e.target.value)} placeholder="26xxx" style={veldStijl} />
            <span style={{ color: 'var(--faint)', fontSize: 11, fontWeight: 400 }}>volgende vrije nummer voorgesteld</span>
          </label>
          <label style={{ fontSize: 12, fontWeight: 600 }}>
            Plaats
            <input value={plaats} onChange={(e) => setPlaats(e.target.value)} placeholder="bijv. Tilburg" style={veldStijl} />
          </label>
          <label style={{ fontSize: 12, fontWeight: 600 }}>
            Opdrachtgever
            <input
              value={opdrachtgever}
              onChange={(e) => setOpdrachtgever(e.target.value)}
              placeholder="bijv. Heijmans"
              style={veldStijl}
            />
          </label>
          <label style={{ fontSize: 12, fontWeight: 600 }}>
            Startdatum
            <input type="date" value={startdatum} onChange={(e) => setStartdatum(e.target.value)} style={veldStijl} />
          </label>
        </div>
        {naam && (
          <p className="hint" style={{ background: 'var(--accent-bg)', borderRadius: 8, color: 'var(--primary)', marginTop: 12, padding: '10px 13px' }}>
            Naam wordt: <b>{naam}</b> — conform de naamconventie, max 50 tekens (RLZ-grens).
          </p>
        )}
        {fout && <div className="fout" style={{ marginTop: 8 }}>{fout}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 12 }}>
          <Button variant="secundair" maat="klein" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </Button>
          <Button maat="klein" onClick={() => void aanmaken()} disabled={bezig || !naam}>
            {bezig ? 'Bezig…' : 'Aanmaken in RLZ'}
          </Button>
        </div>
      </div>
    </div>
  )
}
