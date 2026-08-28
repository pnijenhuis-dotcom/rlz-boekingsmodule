import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, apiFetch, apiJson } from '../api/client'
import type { VendorLijstDto } from '../api/types'
import { Badge, Button, Select, SkeletonPaneel } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { Breadcrumb } from '../werkvoorraad/Breadcrumb'
import { MateriaalstandPaneel } from '../planning/MateriaalstandPaneel'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  beslisOntledingRegel,
  bevestigWerknummer,
  haalProjectDetail,
  ontleedDocument,
  uploadProjectDocument,
  voegStaffelToe,
  voegWerknummerToe,
  wijzigStaffel,
  zetSpecificatie,
  type OntledingRegelDto,
  type ProjectDetailDto,
  type SpecificatieDto,
  type StaffelDto,
  datumMetWeek,
  trekPrijsafspraakIn,
  voegPrijsafspraakToe,
  weekLabel,
  type PrijsafspraakDto,
  type VeldwerkerKeuzeDto,
} from './projectenApi'

/* Projectdetail (mockup projecten-invoer.html view 2, akkoord Peter 22-08): specs-grid
 * (voedt de uitvoerder-app, planning en projectsignalen), documenten (contract/offerte,
 * alleen-lezen door naar de veld-app) mét AI-ontleedvoorstel dat per regel bevestigd wordt
 * (nooit automatisch overgenomen; zonder AI blijft alles handmatig invulbaar),
 * verrekenstaffels (bron van het meerwerk-prijsvoorstel) en leverancier-werknummers
 * (praktijkles factuur↔project-matching). Wijzigen = Beheerder/Boekhouding+Projecten
 * (server-side afgedwongen; een 403 hier toont de nette melding). */

const EENHEID_LABELS: Record<string, string> = { m2: 'm²', m1: 'm¹', stuks: 'stuks', manuren: 'manuren' }
const SOORT_LABELS: Record<string, string> = {
  contract_m2: 'Contract-m²',
  looptijd: 'Looptijd',
  huurtijd: 'Huurtijd inbegrepen',
  doorlopende_huur: 'Doorlopende huur daarna',
  opdrachtgever: 'Opdrachtgever',
  werknummer: 'Werknummer opdrachtgever',
  staffel: 'Staffel',
  boete: 'Boeteclausule',
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

function euro(bedrag: string | number): string {
  return Number(bedrag).toLocaleString('nl-NL', { style: 'currency', currency: 'EUR' })
}

export function ProjectDetailScreen() {
  const navigate = useNavigate()
  const { administratieId = '', projectId = '' } = useParams()
  const { administraties } = useAdministraties()
  const [detail, setDetail] = useState<ProjectDetailDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [melding, setMelding] = useState<string | null>(null)

  const administratieNaam = useMemo(
    () => (administraties ?? []).find((a) => a.id === administratieId)?.naam ?? 'Administratie',
    [administraties, administratieId],
  )

  const laad = useCallback(() => {
    setFout(null)
    haalProjectDetail(administratieId, projectId)
      .then(setDetail)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, projectId])

  useEffect(() => {
    setDetail(null)
    laad()
  }, [laad])

  async function actie(fn: () => Promise<unknown>, geslaagd?: string) {
    setActieFout(null)
    setMelding(null)
    try {
      await fn()
      if (geslaagd) setMelding(geslaagd)
      laad()
    } catch (err) {
      setActieFout(
        err instanceof ApiError || err instanceof Error ? err.message : 'Actie mislukt — probeer het opnieuw.',
      )
    }
  }

  if (fout) return <FoutMelding melding="Het project kon niet geladen worden." detail={fout} onOpnieuw={laad} />
  if (detail === null) return <SkeletonPaneel />

  return (
    <div>
      <div className="topbar">
        <div>
          <Breadcrumb
            stappen={[
              { label: 'Werkvoorraad', naar: '/' },
              { label: administratieNaam, naar: `/?administratie=${administratieId}` },
              { label: 'Projecten', naar: `/projecten?administratie=${administratieId}` },
            ]}
            huidige={detail.naam ?? 'Project'}
          />
          <h1>{detail.naam ?? 'Project'}</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            RLZ-project
            {detail.specificatie?.werknummer_opdrachtgever
              ? ` · gekoppeld werknummer opdrachtgever: ${detail.specificatie.werknummer_opdrachtgever}`
              : ''}
          </div>
        </div>
        <div style={{ marginLeft: 'auto' }}>
          <Button
            variant="secundair"
            maat="klein"
            onClick={() => navigate(`/projecten/${administratieId}/${projectId}/resultaat`)}
          >
            📈 Resultaat
          </Button>
        </div>
      </div>

      {actieFout && <div className="fout">{actieFout}</div>}
      {melding && <p className="hint" style={{ color: 'var(--ok)' }}>{melding}</p>}

      <SpecificatiePaneel
        specificatie={detail.specificatie}
        onOpslaan={(spec) =>
          void actie(() => zetSpecificatie(administratieId, projectId, spec), 'Specificaties opgeslagen.')
        }
      />
      <DocumentenPaneel
        administratieId={administratieId}
        projectId={projectId}
        detail={detail}
        actie={actie}
      />
      <StaffelsPaneel administratieId={administratieId} projectId={projectId} staffels={detail.staffels} actie={actie} />
      <PrijsafsprakenPaneel
        administratieId={administratieId}
        projectId={projectId}
        afspraken={detail.prijsafspraken ?? []}
        veldwerkers={detail.veldwerkers ?? []}
        actie={actie}
      />
      <MateriaalstandPaneel administratieId={administratieId} projectId={projectId} />
      <WerknummersPaneel
        administratieId={administratieId}
        projectId={projectId}
        detail={detail}
        actie={actie}
      />
    </div>
  )
}

function SpecificatiePaneel({
  specificatie,
  onOpslaan,
}: {
  specificatie: SpecificatieDto | null
  onOpslaan: (spec: SpecificatieDto) => void
}) {
  const [vorm, setVorm] = useState<SpecificatieDto>(() => ({
    opdrachtgever: specificatie?.opdrachtgever ?? null,
    werknummer_opdrachtgever: specificatie?.werknummer_opdrachtgever ?? null,
    soort_werk: specificatie?.soort_werk ?? null,
    contract_m2: specificatie?.contract_m2 ?? null,
    looptijd_van: specificatie?.looptijd_van ?? null,
    looptijd_tot: specificatie?.looptijd_tot ?? null,
    huurtijd_omschrijving: specificatie?.huurtijd_omschrijving ?? null,
    doorlopende_huur_omschrijving: specificatie?.doorlopende_huur_omschrijving ?? null,
    locatie_adres: specificatie?.locatie_adres ?? null,
    locatie_lat: specificatie?.locatie_lat ?? null,
    locatie_lon: specificatie?.locatie_lon ?? null,
    zone_straal_m: specificatie?.zone_straal_m ?? null,
  }))
  const zet = (veld: keyof SpecificatieDto) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setVorm((huidig) => ({ ...huidig, [veld]: e.target.value || null }))
  const zoneActief = Boolean(vorm.locatie_lat && vorm.locatie_lon)

  return (
    <div className="panel">
      <h2>Specificaties</h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Deze velden voeden de uitvoerder-app (specs-scherm), de planning en de projectsignalen. Handmatig invullen of
        bevestigen uit de contract-ontleding hieronder.
      </p>
      <div style={{ display: 'grid', gap: '12px 16px', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Opdrachtgever
          <input value={vorm.opdrachtgever ?? ''} onChange={zet('opdrachtgever')} style={veldStijl} />
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Werknummer opdrachtgever
          <input value={vorm.werknummer_opdrachtgever ?? ''} onChange={zet('werknummer_opdrachtgever')} style={veldStijl} />
          <span style={{ color: 'var(--faint)', fontWeight: 400 }}>gebruikt voor factuur↔project-matching</span>
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Soort werk
          <input value={vorm.soort_werk ?? ''} onChange={zet('soort_werk')} style={veldStijl} />
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Contract-m²
          <input value={vorm.contract_m2 ?? ''} onChange={zet('contract_m2')} inputMode="decimal" style={veldStijl} />
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Looptijd van
          <input type="date" value={vorm.looptijd_van ?? ''} onChange={zet('looptijd_van')} style={veldStijl} />
          {vorm.looptijd_van && <span className="hint" style={{ fontSize: 11 }}>{datumMetWeek(vorm.looptijd_van)}</span>}
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Looptijd t/m
          <input type="date" value={vorm.looptijd_tot ?? ''} onChange={zet('looptijd_tot')} style={veldStijl} />
          {vorm.looptijd_tot && <span className="hint" style={{ fontSize: 11 }}>{datumMetWeek(vorm.looptijd_tot)}</span>}
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Huurtijd inbegrepen
          <input value={vorm.huurtijd_omschrijving ?? ''} onChange={zet('huurtijd_omschrijving')} style={veldStijl} />
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Doorlopende huur daarna
          <input
            value={vorm.doorlopende_huur_omschrijving ?? ''}
            onChange={zet('doorlopende_huur_omschrijving')}
            style={veldStijl}
          />
          <span style={{ color: 'var(--faint)', fontWeight: 400 }}>voedt het doorlopende-huur-signaal</span>
        </label>
        {/* Blok C 28-08 (mockup geofence-stempels.html §2): projectlocatie + zone-straal; zonder
            locatie = geen geofence voor dit project (stil, geen verplichting). */}
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Projectlocatie 📍
          <input value={vorm.locatie_adres ?? ''} onChange={zet('locatie_adres')} placeholder="Kanaaldijk 12, Tilburg" style={veldStijl} />
          <span style={{ color: 'var(--faint)', fontWeight: 400 }}>adres ter herkenning; de zone rekent met het punt hieronder</span>
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Breedtegraad (lat)
          <input value={vorm.locatie_lat ?? ''} onChange={zet('locatie_lat')} inputMode="decimal" placeholder="51.560000" style={veldStijl} />
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Lengtegraad (lon)
          <input value={vorm.locatie_lon ?? ''} onChange={zet('locatie_lon')} inputMode="decimal" placeholder="5.083000" style={veldStijl} />
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
          Zone-straal
          <select
            value={vorm.zone_straal_m ?? ''}
            onChange={(e) => setVorm((huidig) => ({ ...huidig, zone_straal_m: e.target.value ? Number(e.target.value) : null }))}
            style={veldStijl}
            aria-label="Zone-straal"
          >
            <option value="">— (default 150 m)</option>
            <option value="100">100 m</option>
            <option value="150">150 m</option>
            <option value="250">250 m</option>
            <option value="500">500 m</option>
          </select>
          <span style={{ color: 'var(--faint)', fontWeight: 400 }}>
            {zoneActief ? '📍 Stempels actief — werkstempels op dit project worden aangenomen' : 'geen locatie = geen werkstempels voor dit project'}
          </span>
        </label>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
        <Button maat="klein" onClick={() => onOpslaan(vorm)}>
          Opslaan
        </Button>
      </div>
    </div>
  )
}

function OntledingRegelRij({
  regel,
  administratieId,
  actie,
}: {
  regel: OntledingRegelDto
  administratieId: string
  actie: (fn: () => Promise<unknown>, geslaagd?: string) => Promise<void>
}) {
  const [eenheid, setEenheid] = useState('m2')
  const waardeTekst =
    regel.soort === 'looptijd'
      ? [regel.waarde?.van, regel.waarde?.tot].filter(Boolean).join(' t/m ')
      : regel.soort === 'staffel'
        ? `${euro(regel.waarde?.waarde ?? '0')} ${regel.waarde?.eenheid ? `/${regel.waarde.eenheid}` : ''}`
        : (regel.waarde?.waarde ?? '')
  const beslist = regel.status !== 'voorstel'
  return (
    <div
      style={{
        alignItems: 'center',
        borderTop: '1px solid var(--border)',
        display: 'flex',
        flexWrap: 'wrap',
        gap: 10,
        opacity: beslist ? 0.65 : 1,
        padding: '9px 14px',
      }}
    >
      <span style={{ flex: 1, minWidth: 220 }}>
        <b>{SOORT_LABELS[regel.soort] ?? regel.soort}</b>
        {regel.soort === 'staffel' || regel.soort === 'boete' ? `: ${regel.omschrijving}` : ''}
        {regel.citaat && <span style={{ color: 'var(--muted)', display: 'block', fontSize: 11 }}>{regel.citaat}</span>}
      </span>
      <b style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}>{waardeTekst}</b>
      {regel.zekerheid !== null && <Badge>{Math.round(Number(regel.zekerheid) * 100)}%</Badge>}
      {beslist && (
        <Badge variant={regel.status === 'bevestigd' ? 'ok' : 'danger'}>
          {regel.status === 'bevestigd' ? '✓ bevestigd' : '✗ afgewezen'}
        </Badge>
      )}
      {!beslist && (
        <span style={{ alignItems: 'center', display: 'inline-flex', gap: 6 }}>
          {regel.soort === 'staffel' && (
            <Select aria-label="Eenheid" value={eenheid} onChange={(e) => setEenheid(e.target.value)}>
              {Object.entries(EENHEID_LABELS).map(([waarde, label]) => (
                <option key={waarde} value={waarde}>
                  {label}
                </option>
              ))}
            </Select>
          )}
          <Button
            maat="klein"
            aria-label={`Bevestig ${regel.omschrijving}`}
            onClick={() =>
              void actie(() =>
                beslisOntledingRegel(administratieId, regel.id, {
                  bevestigen: true,
                  eenheid: regel.soort === 'staffel' ? eenheid : null,
                }),
              )
            }
          >
            ✓
          </Button>
          <Button
            variant="secundair"
            maat="klein"
            aria-label={`Wijs ${regel.omschrijving} af`}
            onClick={() => void actie(() => beslisOntledingRegel(administratieId, regel.id, { bevestigen: false }))}
          >
            ✗
          </Button>
        </span>
      )}
    </div>
  )
}

function DocumentenPaneel({
  administratieId,
  projectId,
  detail,
  actie,
}: {
  administratieId: string
  projectId: string
  detail: ProjectDetailDto
  actie: (fn: () => Promise<unknown>, geslaagd?: string) => Promise<void>
}) {
  const bestandRef = useRef<HTMLInputElement>(null)
  const [soort, setSoort] = useState<'contract' | 'offerte'>('contract')

  const openDocument = async (documentId: string, bestandsnaam: string) => {
    // Bestaande leesroute (uitvoerder + kantoor): Authorization-header vereist → blob.
    const resp = await apiFetch(`/uren/projectdocumenten/${administratieId}/${documentId}`)
    if (!resp.ok) throw new ApiError(resp.status, `Openen mislukt (${resp.status})`)
    const url = URL.createObjectURL(await resp.blob())
    window.open(url, '_blank', 'noopener')
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    void bestandsnaam
  }

  return (
    <div className="panel">
      <h2>Documenten (contract &amp; offerte)</h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Alleen-lezen zichtbaar voor de uitvoerder in de veld-app. Ná upload stelt de ontleding specs en staffels VOOR —
        jij bevestigt per regel, er wordt nooit iets automatisch overgenomen.
      </p>
      {detail.documenten.map((doc) => (
        <div
          key={doc.id}
          style={{
            alignItems: 'center',
            background: 'var(--panel-2)',
            border: '1px solid var(--border)',
            borderRadius: 10,
            display: 'flex',
            flexWrap: 'wrap',
            gap: 10,
            marginBottom: 8,
            padding: '10px 12px',
          }}
        >
          <span aria-hidden>📄</span>
          <span style={{ flex: 1, minWidth: 200 }}>
            <b>{doc.titel}</b>
            <span style={{ color: 'var(--muted)', display: 'block', fontSize: 11.5 }}>
              {doc.bestandsnaam} · geüpload {datumMetWeek(doc.aangemaakt_op)}
              {doc.ontleed ? ' · ontleed ✓' : ''}
            </span>
          </span>
          <Badge variant={doc.soort === 'contract' ? 'ok' : 'stil'}>{doc.soort}</Badge>
          <Button variant="secundair" maat="klein" onClick={() => void actie(() => openDocument(doc.id, doc.bestandsnaam))}>
            Bekijk
          </Button>
          <Button
            variant="secundair"
            maat="klein"
            onClick={() =>
              void actie(
                () => ontleedDocument(administratieId, projectId, doc.id),
                'Ontleed-voorstel klaargezet — bevestig per regel.',
              )
            }
          >
            🧠 Ontleden
          </Button>
        </div>
      ))}
      <div style={{ alignItems: 'center', border: '1.5px dashed var(--border)', borderRadius: 10, color: 'var(--muted)', display: 'flex', flexWrap: 'wrap', gap: 10, fontSize: 12.5, justifyContent: 'center', marginTop: 6, padding: 14 }}>
        <Select aria-label="Documentsoort" value={soort} onChange={(e) => setSoort(e.target.value as 'contract' | 'offerte')}>
          <option value="contract">contract</option>
          <option value="offerte">offerte</option>
        </Select>
        <Button variant="secundair" maat="klein" onClick={() => bestandRef.current?.click()}>
          PDF kiezen…
        </Button>
        <span>ontleding start daarna als voorstel (AI-gate + kostengrens; uit = handmatig invullen)</span>
        <input
          ref={bestandRef}
          type="file"
          accept="application/pdf"
          aria-label="Contract of offerte uploaden"
          style={{ display: 'none' }}
          onChange={(e) => {
            const bestand = e.target.files?.[0]
            e.target.value = ''
            if (!bestand) return
            void actie(
              () => uploadProjectDocument(administratieId, projectId, bestand, soort, bestand.name.replace(/\.pdf$/i, '')),
              'Document geüpload.',
            )
          }}
        />
      </div>

      {detail.ontleding.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 10, marginTop: 12, overflow: 'hidden' }}>
          <div style={{ background: 'var(--info-bg)', color: 'var(--info)', fontSize: 12.5, fontWeight: 700, padding: '10px 14px' }}>
            🧠 Ontleed-voorstel — bevestig per regel (staffels: kies de eenheid, de AI-eenheid is alleen een voorstel)
          </div>
          {detail.ontleding.map((regel) => (
            <OntledingRegelRij key={regel.id} regel={regel} administratieId={administratieId} actie={actie} />
          ))}
        </div>
      )}
    </div>
  )
}

function StaffelsPaneel({
  administratieId,
  projectId,
  staffels,
  actie,
}: {
  administratieId: string
  projectId: string
  staffels: StaffelDto[]
  actie: (fn: () => Promise<unknown>, geslaagd?: string) => Promise<void>
}) {
  const [bewerk, setBewerk] = useState<StaffelDto | 'nieuw' | null>(null)
  return (
    <div className="panel">
      <h2>
        Verrekenstaffels{' '}
        <Button variant="secundair" maat="klein" style={{ float: 'right' }} onClick={() => setBewerk('nieuw')}>
          + Regel
        </Button>
      </h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Bron voor het prijsvoorstel bij meerwerk-beoordeling. &quot;Verrekenbaar nee&quot; = meerwerk op dit item wordt
        standaard afgeraden (eigen rekening) — de mens beslist altijd.
      </p>
      {staffels.length === 0 && <p className="hint">Nog geen staffels — voeg een regel toe of ontleed het contract.</p>}
      {staffels.length > 0 && (
        <div className="tabel-scroll">
          <table>
            <thead>
              <tr>
                <th>Omschrijving</th>
                <th>Eenheid</th>
                <th>Prijs</th>
                <th>Verrekenbaar</th>
                <th>Bron</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {staffels.map((staffel) => (
                <tr key={staffel.id}>
                  <td>{staffel.omschrijving}</td>
                  <td>{EENHEID_LABELS[staffel.eenheid] ?? staffel.eenheid}</td>
                  <td>{euro(staffel.prijs_per_eenheid)}</td>
                  <td>{staffel.verrekenbaar ? <Badge variant="ok">ja</Badge> : <Badge variant="warn">nee</Badge>}</td>
                  <td>{staffel.bron ?? '—'}</td>
                  <td>
                    <Button variant="secundair" maat="klein" onClick={() => setBewerk(staffel)}>
                      wijzig
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {bewerk !== null && (
        <StaffelVorm
          staffel={bewerk === 'nieuw' ? null : bewerk}
          onOpslaan={(waarden) => {
            setBewerk(null)
            if (bewerk === 'nieuw') {
              void actie(() => voegStaffelToe(administratieId, projectId, waarden), 'Staffel toegevoegd.')
            } else {
              void actie(() => wijzigStaffel(administratieId, bewerk.id, waarden), 'Staffel gewijzigd.')
            }
          }}
          onAnnuleren={() => setBewerk(null)}
        />
      )}
    </div>
  )
}

function StaffelVorm({
  staffel,
  onOpslaan,
  onAnnuleren,
}: {
  staffel: StaffelDto | null
  onOpslaan: (waarden: { omschrijving: string; eenheid: string; prijs_per_eenheid: string; verrekenbaar: boolean; bron?: string | null }) => void
  onAnnuleren: () => void
}) {
  const [omschrijving, setOmschrijving] = useState(staffel?.omschrijving ?? '')
  const [eenheid, setEenheid] = useState(staffel?.eenheid ?? 'm2')
  const [prijs, setPrijs] = useState(staffel?.prijs_per_eenheid ?? '')
  const [verrekenbaar, setVerrekenbaar] = useState(staffel?.verrekenbaar ?? true)
  return (
    <div style={{ alignItems: 'end', background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 10, display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 10, padding: 12 }}>
      <label style={{ flex: 2, fontSize: 11.5, fontWeight: 600, color: 'var(--muted)', minWidth: 180 }}>
        Omschrijving
        <input value={omschrijving} onChange={(e) => setOmschrijving(e.target.value)} style={veldStijl} />
      </label>
      <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
        Eenheid
        <Select value={eenheid} onChange={(e) => setEenheid(e.target.value)}>
          {Object.entries(EENHEID_LABELS).map(([waarde, label]) => (
            <option key={waarde} value={waarde}>
              {label}
            </option>
          ))}
        </Select>
      </label>
      <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)', width: 110 }}>
        Prijs
        <input value={prijs} onChange={(e) => setPrijs(e.target.value)} inputMode="decimal" style={veldStijl} />
      </label>
      <label style={{ alignItems: 'center', display: 'inline-flex', fontSize: 12, gap: 6 }}>
        <input type="checkbox" checked={verrekenbaar} onChange={(e) => setVerrekenbaar(e.target.checked)} />
        verrekenbaar
      </label>
      <Button
        maat="klein"
        disabled={!omschrijving.trim() || !prijs.trim()}
        onClick={() =>
          onOpslaan({
            omschrijving: omschrijving.trim(),
            eenheid,
            prijs_per_eenheid: prijs.replace(',', '.').trim(),
            verrekenbaar,
            bron: staffel?.bron ?? 'handmatig',
          })
        }
      >
        Opslaan
      </Button>
      <Button variant="secundair" maat="klein" onClick={onAnnuleren}>
        Annuleren
      </Button>
    </div>
  )
}

/** Prijsafspraken veldwerkers — dit project (steigerbouw-run B1, mockup projecten-invoer =
 * norm): projectafspraak wint in de factuurmatch van het koppeling-tarief; eenheid uur óf m²;
 * geldigheid in ISO-weken; wijzigen = intrekken (reden) + nieuwe afspraak (append-only). */
function PrijsafsprakenPaneel({
  administratieId,
  projectId,
  afspraken,
  veldwerkers,
  actie,
}: {
  administratieId: string
  projectId: string
  afspraken: PrijsafspraakDto[]
  veldwerkers: VeldwerkerKeuzeDto[]
  actie: (fn: () => Promise<unknown>, geslaagd?: string) => Promise<void>
}) {
  const [nieuw, setNieuw] = useState<PrijsafspraakDto | 'nieuw' | null>(null)
  const [intrek, setIntrek] = useState<PrijsafspraakDto | null>(null)
  const [reden, setReden] = useState('')
  const [toonHistorie, setToonHistorie] = useState(false)
  const actief = afspraken.filter((a) => a.ingetrokken_op === null)
  const historie = afspraken.filter((a) => a.ingetrokken_op !== null)
  const tariefLabel = (a: { tarief: string; eenheid: string }) => `${euro(a.tarief)} /${a.eenheid === 'm2' ? 'm²' : 'u'}`
  const geldigLabel = (a: PrijsafspraakDto) => {
    const van = weekLabel(a.geldig_vanaf_jaar, a.geldig_vanaf_week)
    const tm = weekLabel(a.geldig_tm_jaar, a.geldig_tm_week)
    if (!van && !tm) return 'hele project'
    if (van && tm) return `${van} t/m ${tm}`
    return van ? `vanaf ${van}` : `t/m ${tm}`
  }
  return (
    <div className="panel">
      <h2>
        Prijsafspraken veldwerkers — dit project{' '}
        <Button variant="secundair" maat="klein" style={{ float: 'right' }} onClick={() => setNieuw('nieuw')} disabled={veldwerkers.length === 0}>
          + Afspraak
        </Button>
      </h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Projectspecifieke tarieven die afwijken van het standaardtarief op de veldwerker-koppeling. De factuurmatch rekent
        per week: <b>projectafspraak wint</b> → anders het koppeling-tarief → anders &quot;onbepaalbaar&quot; (oranje, nooit
        gokken). Eenheid m² rekent met de goedgekeurde m² uit de weekstaten in plaats van uren. Wijzigen = intrekken (reden)
        + nieuwe afspraak; alles geauditeerd.
      </p>
      {veldwerkers.length === 0 && <p className="hint">Nog geen ZZP'ers aan dit project gekoppeld — koppelen gebeurt via Gebruikers &amp; toegang of de planning.</p>}
      {actief.length === 0 && veldwerkers.length > 0 && <p className="hint">Geen afspraak — het koppeling-tarief geldt.</p>}
      {actief.length > 0 && (
        <div className="tabel-scroll">
          <table>
            <thead>
              <tr>
                <th>Veldwerker</th>
                <th>Eenheid</th>
                <th>Tarief</th>
                <th>Standaard (koppeling)</th>
                <th>Geldig</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {actief.map((a) => (
                <tr key={a.id}>
                  <td>
                    <b>{a.veldwerker_naam ?? a.gebruiker_id}</b>{' '}
                    <Badge variant="paars">{a.via_bureau_naam ? `via ${a.via_bureau_naam} (bureau)` : "ZZP'er"}</Badge>
                    {a.toelichting && <div className="hint" style={{ fontSize: 11 }}>{a.toelichting}</div>}
                  </td>
                  <td>{a.eenheid === 'm2' ? 'm²' : 'uur'}</td>
                  <td>{tariefLabel(a)}</td>
                  <td className="hint">{a.standaard_tarief ? `${euro(a.standaard_tarief)} /u` : 'geen tarief'}</td>
                  <td>{geldigLabel(a)}</td>
                  <td style={{ whiteSpace: 'nowrap' }}>
                    <Button variant="secundair" maat="klein" onClick={() => setNieuw(a)}>
                      wijzig
                    </Button>{' '}
                    <Button variant="ghost" maat="klein" onClick={() => { setIntrek(a); setReden('') }}>
                      intrekken
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {historie.length > 0 && (
        <p className="hint" style={{ marginBottom: 0 }}>
          <button type="button" className="linkbtn" onClick={() => setToonHistorie((t) => !t)}>
            {toonHistorie ? 'Historie verbergen' : `${historie.length} ingetrokken afspraak/afspraken tonen`}
          </button>
        </p>
      )}
      {toonHistorie &&
        historie.map((a) => (
          <div key={a.id} className="hint" style={{ fontSize: 11.5 }}>
            {a.veldwerker_naam} · {tariefLabel(a)} · {geldigLabel(a)} — ingetrokken {datumMetWeek(a.ingetrokken_op)}: {a.ingetrokken_reden}
          </div>
        ))}
      {nieuw !== null && (
        <PrijsafspraakVorm
          basis={nieuw === 'nieuw' ? null : nieuw}
          veldwerkers={veldwerkers}
          onOpslaan={(waarden) => {
            const oud = nieuw
            setNieuw(null)
            void actie(async () => {
              if (oud !== 'nieuw') {
                await trekPrijsafspraakIn(administratieId, oud.id, 'vervangen door nieuwe afspraak')
              }
              await voegPrijsafspraakToe(administratieId, projectId, waarden)
            }, oud === 'nieuw' ? 'Prijsafspraak toegevoegd.' : 'Prijsafspraak vervangen (oude ingetrokken).')
          }}
          onAnnuleren={() => setNieuw(null)}
        />
      )}
      {intrek && (
        <div style={{ alignItems: 'end', background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 10, display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 10, padding: 12 }}>
          <label style={{ flex: 1, fontSize: 11.5, fontWeight: 600, color: 'var(--muted)', minWidth: 220 }}>
            Reden intrekken — {intrek.veldwerker_naam} {tariefLabel(intrek)}
            <input value={reden} onChange={(e) => setReden(e.target.value)} style={veldStijl} placeholder="bijv. tarief herzien per wk 41" />
          </label>
          <Button maat="klein" variant="gevaar" disabled={reden.trim().length < 3} onClick={() => { const a = intrek; setIntrek(null); void actie(() => trekPrijsafspraakIn(administratieId, a.id, reden.trim()), 'Prijsafspraak ingetrokken.') }}>
            Intrekken
          </Button>
          <Button variant="secundair" maat="klein" onClick={() => setIntrek(null)}>
            Annuleren
          </Button>
        </div>
      )}
    </div>
  )
}

function PrijsafspraakVorm({
  basis,
  veldwerkers,
  onOpslaan,
  onAnnuleren,
}: {
  basis: PrijsafspraakDto | null
  veldwerkers: VeldwerkerKeuzeDto[]
  onOpslaan: (waarden: {
    gebruiker_id: string
    eenheid: 'uur' | 'm2'
    tarief: string
    geldig_vanaf_jaar: number | null
    geldig_vanaf_week: number | null
    geldig_tm_jaar: number | null
    geldig_tm_week: number | null
    toelichting: string | null
  }) => void
  onAnnuleren: () => void
}) {
  const [gebruikerId, setGebruikerId] = useState(basis?.gebruiker_id ?? veldwerkers[0]?.gebruiker_id ?? '')
  const [eenheid, setEenheid] = useState<'uur' | 'm2'>(basis?.eenheid ?? 'uur')
  const [tarief, setTarief] = useState(basis?.tarief ?? '')
  const [vanaf, setVanaf] = useState(basis?.geldig_vanaf_week ? `${basis.geldig_vanaf_jaar}-W${String(basis.geldig_vanaf_week).padStart(2, '0')}` : '')
  const [tm, setTm] = useState(basis?.geldig_tm_week ? `${basis.geldig_tm_jaar}-W${String(basis.geldig_tm_week).padStart(2, '0')}` : '')
  const [toelichting, setToelichting] = useState(basis?.toelichting ?? '')
  const gekozen = veldwerkers.find((v) => v.gebruiker_id === gebruikerId)
  const parseWeek = (w: string): [number, number] | null => {
    const m = /^(\d{4})-W(\d{2})$/.exec(w)
    return m ? [Number(m[1]), Number(m[2])] : null
  }
  const v = parseWeek(vanaf)
  const t = parseWeek(tm)
  return (
    <div style={{ alignItems: 'end', background: 'var(--panel-2)', border: '1px solid var(--border)', borderRadius: 10, display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 10, padding: 12 }}>
      <label style={{ flex: 2, fontSize: 11.5, fontWeight: 600, color: 'var(--muted)', minWidth: 200 }}>
        Veldwerker
        <Select value={gebruikerId} onChange={(e) => setGebruikerId(e.target.value)} disabled={basis !== null}>
          {veldwerkers.map((w) => (
            <option key={w.gebruiker_id} value={w.gebruiker_id}>
              {w.naam}
              {w.via_bureau_naam ? ` (via ${w.via_bureau_naam})` : ''}
              {w.standaard_tarief ? ` — standaard ${euro(w.standaard_tarief)}/u` : ' — geen koppeling-tarief'}
            </option>
          ))}
        </Select>
      </label>
      <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
        Eenheid
        <Select value={eenheid} onChange={(e) => setEenheid(e.target.value as 'uur' | 'm2')}>
          <option value="uur">uur</option>
          <option value="m2">m² (goedgekeurde weekstaat-m²)</option>
        </Select>
      </label>
      <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)', width: 110 }}>
        Tarief (€)
        <input value={tarief} onChange={(e) => setTarief(e.target.value)} inputMode="decimal" style={veldStijl} />
      </label>
      <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
        Vanaf week (optioneel)
        <input type="week" value={vanaf} onChange={(e) => setVanaf(e.target.value)} style={veldStijl} />
      </label>
      <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>
        T/m week (optioneel)
        <input type="week" value={tm} onChange={(e) => setTm(e.target.value)} style={veldStijl} />
      </label>
      <label style={{ flex: 2, fontSize: 11.5, fontWeight: 600, color: 'var(--muted)', minWidth: 160 }}>
        Toelichting
        <input value={toelichting} onChange={(e) => setToelichting(e.target.value)} style={veldStijl} />
      </label>
      <Button
        maat="klein"
        disabled={!gebruikerId || !tarief.trim() || (vanaf !== '' && !v) || (tm !== '' && !t)}
        onClick={() =>
          onOpslaan({
            gebruiker_id: gebruikerId,
            eenheid,
            tarief: tarief.replace(',', '.').trim(),
            geldig_vanaf_jaar: v?.[0] ?? null,
            geldig_vanaf_week: v?.[1] ?? null,
            geldig_tm_jaar: t?.[0] ?? null,
            geldig_tm_week: t?.[1] ?? null,
            toelichting: toelichting.trim() || null,
          })
        }
      >
        Opslaan
      </Button>
      <Button variant="secundair" maat="klein" onClick={onAnnuleren}>
        Annuleren
      </Button>
      {gekozen && !gekozen.standaard_tarief && (
        <span className="hint" style={{ width: '100%', margin: 0 }}>
          Zonder koppeling-tarief is deze afspraak de enige prijsbron — buiten het venster wordt de match &quot;onbepaalbaar&quot;.
        </span>
      )}
    </div>
  )
}

function WerknummersPaneel({
  administratieId,
  projectId,
  detail,
  actie,
}: {
  administratieId: string
  projectId: string
  detail: ProjectDetailDto
  actie: (fn: () => Promise<unknown>, geslaagd?: string) => Promise<void>
}) {
  const [crediteuren, setCrediteuren] = useState<VendorLijstDto | null>(null)
  const [vendorId, setVendorId] = useState('')
  const [werknummer, setWerknummer] = useState('')

  useEffect(() => {
    apiJson<VendorLijstDto>(`/administraties/${administratieId}/crediteuren`)
      .then(setCrediteuren)
      .catch(() => setCrediteuren({ crediteuren: [] }))
  }, [administratieId])

  return (
    <div className="panel">
      <h2>Leverancier-werknummers</h2>
      <p className="hint" style={{ marginTop: 0 }}>
        Leveranciers hanteren eigen werknummers op hun facturen — deze mapping koppelt ze aan dit project (eerste keer
        bevestigen, daarna automatisch; bestaande praktijkles).
      </p>
      {detail.werknummers.length > 0 && (
        <div className="tabel-scroll">
          <table>
            <thead>
              <tr>
                <th>Leverancier</th>
                <th>Hun werknummer</th>
                <th>Bron</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {detail.werknummers.map((rij) => (
                <tr key={rij.id}>
                  <td>{rij.leverancier_naam ?? rij.vendor_id}</td>
                  <td>{rij.werknummer}</td>
                  <td>
                    {rij.bron}{' '}
                    {rij.bevestigd ? <Badge variant="ok">bevestigd</Badge> : <Badge variant="warn">bevestigen</Badge>}
                  </td>
                  <td>
                    {!rij.bevestigd && (
                      <Button
                        maat="klein"
                        onClick={() => void actie(() => bevestigWerknummer(administratieId, rij.id), 'Werknummer bevestigd.')}
                      >
                        Bevestig
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div style={{ alignItems: 'end', display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 10 }}>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)', minWidth: 220 }}>
          Leverancier
          <Select aria-label="Leverancier" value={vendorId} onChange={(e) => setVendorId(e.target.value)}>
            <option value="">— kies een crediteur —</option>
            {(crediteuren?.crediteuren ?? []).map((vendor) => (
              <option key={vendor.id} value={vendor.id}>
                {vendor.naam ?? vendor.id}
              </option>
            ))}
          </Select>
        </label>
        <label style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)', width: 160 }}>
          Werknummer
          <input value={werknummer} onChange={(e) => setWerknummer(e.target.value)} style={veldStijl} />
        </label>
        <Button
          maat="klein"
          disabled={!vendorId || !werknummer.trim()}
          onClick={() => {
            const nummer = werknummer.trim()
            setWerknummer('')
            void actie(
              () => voegWerknummerToe(administratieId, projectId, { vendor_id: vendorId, werknummer: nummer }),
              'Werknummer gekoppeld.',
            )
          }}
        >
          + Koppel
        </Button>
      </div>
    </div>
  )
}
