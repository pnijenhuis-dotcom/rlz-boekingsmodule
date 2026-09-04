// Reviewscherm verplichting (blok B 04-09, mockup offerte-matching.html blok 1 "Controle kantoor"
// = norm): zelfde veldvoorstel-patroon als het inkoop-controlescherm — herkomst-chips per veld,
// PDF links, checks als inklapregel, één primaire knop ("Ter accordering") + "Afwijzen…".
//
// Een verplichting wordt NOOIT geboekt (①): ná het laatste klant-akkoord staat het document op
// `geaccordeerd` en is het akkoord (wie/wanneer/welk bedrag) het resultaat. Daarna toont dit
// scherm het goedgekeurd-blok mét verbruiksstand en de gematchte facturen, en kan kantoor de
// verplichting laten VERVALLEN (⑥ — reden verplicht; nieuwe matches stoppen, bestaande blijven).
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AccorderingSectie } from '../document/AccorderingSectie'
import { AfwijsModal } from '../document/AfwijsModal'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { useProjectOpties, useProjectVerplicht, useVendorOpties } from '../document/useSyncOpties'
import { ApiError, apiFetch, apiJson } from '../api/client'
import type { DocumentDetailDto } from '../api/types'
import { DatePicker } from '../ui/DatePicker'
import { FoutMelding } from '../ui/FoutMelding'
import {
  AnkerPopup,
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  FormField,
  Select,
  SkeletonBlok,
  SkeletonPaneel,
  useToastOptioneel,
} from '../ui/basis'
import { formatBedrag, formatDatum, formatDatumKort } from '../werkvoorraad/format'
import { StatusChip } from '../werkvoorraad/StatusChip'
import { statusLabel } from '../werkvoorraad/status'
import { VerbruiksBalk } from './VerbruiksBalk'
import {
  SOORT_LABEL_OPTIES,
  SOORT_LABEL_TEKST,
  haalVerplichtingVoorstel,
  laatVerplichtingVervallen,
  slaVerplichtingVoorstelOp,
  voerVerplichtingChecksUit,
  type VerplichtingCheckDto,
  type VerplichtingHerkomst,
  type VerplichtingSoortLabel,
  type VerplichtingVeld,
  type VerplichtingVoorstelDto,
  type VerplichtingVoorstelInput,
} from './verplichtingApi'

/** Statussen waarin het voorstel bewerkbaar is en de verplichting ter accordering kan. */
const BEWERKBARE_STATUSSEN = new Set(['te_controleren', 'klaar_om_te_boeken', 'handmatig_afmaken', 'afgewezen'])
const AFWIJSBARE_STATUSSEN = new Set(['te_controleren', 'klaar_om_te_boeken', 'handmatig_afmaken'])

const HERKOMST_TITEL: Record<VerplichtingHerkomst, string> = {
  ai: 'Gelezen door de AI-extractie uit dit document — controleer de waarde.',
  template:
    'Deterministisch gelezen via het geleerde template van deze leverancier (lokale code, geen AI). De harde checks blijven de poort.',
  mens: 'Door een medewerker opgeslagen — geen voorstel meer, maar een vastgelegde keuze.',
}

/** Herkomst-chip naast een vooringevuld veld (zelfde bedoeling als de AI-chip op het
 * inkoop-controlescherm): AI onder de drempel = oranje, template/mens = groen. Verdwijnt zodra
 * de controleur het veld aanpast — de herkomst beschrijft de inhoud dan niet meer. */
function HerkomstChip({
  herkomst,
  zekerheid,
  drempel,
}: {
  herkomst: VerplichtingHerkomst | null | undefined
  zekerheid?: number
  drempel: number
}) {
  if (!herkomst) return null
  if (herkomst === 'ai') {
    const laag = typeof zekerheid === 'number' && zekerheid < drempel
    return (
      <span className={`chip ${laag ? 'afwijking' : 'ok'}`} title={HERKOMST_TITEL.ai}>
        AI{typeof zekerheid === 'number' ? ` ${Math.round(zekerheid * 100)}%` : ''}
      </span>
    )
  }
  return (
    <span className="chip ok" title={HERKOMST_TITEL[herkomst]}>
      {herkomst === 'template' ? 'uit template' : 'vastgelegd'}
    </span>
  )
}

function checkChip(status: VerplichtingCheckDto['status']) {
  if (status === 'ok') return <span className="chip ok">OK</span>
  if (status === 'blokkerend') return <span className="chip blokkerend">Blokkerend</span>
  if (status === 'signaal') return <span className="chip afwijking">Signaal</span>
  return <span className="chip geheugen">n.v.t.</span>
}

interface Velden {
  soortLabel: VerplichtingSoortLabel | null
  vendorId: string | null
  projectId: string | null
  offertenummer: string
  datum: string | null
  totaalbedragExcl: string
  geldigTot: string | null
  omschrijving: string
}

function veldenUitDto(v: VerplichtingVoorstelDto): Velden {
  return {
    soortLabel: v.soort_label,
    vendorId: v.vendor_id,
    projectId: v.project_id,
    offertenummer: v.offertenummer ?? '',
    datum: v.datum,
    totaalbedragExcl: v.totaalbedrag_excl ?? '',
    geldigTot: v.geldig_tot,
    omschrijving: v.omschrijving ?? '',
  }
}

function naarInvoer(v: Velden): VerplichtingVoorstelInput {
  const bedrag = v.totaalbedragExcl.trim().replace(',', '.')
  return {
    soort_label: v.soortLabel,
    vendor_id: v.vendorId,
    project_id: v.projectId,
    offertenummer: v.offertenummer.trim() || null,
    datum: v.datum,
    totaalbedrag_excl: bedrag === '' ? null : bedrag,
    geldig_tot: v.geldigTot,
    omschrijving: v.omschrijving.trim() || null,
  }
}

export function VerplichtingReviewScreen() {
  const { administratieId, documentId } = useParams<{ administratieId: string; documentId: string }>()
  const toast = useToastOptioneel()

  const [detail, setDetail] = useState<DocumentDetailDto | null>(null)
  const [voorstel, setVoorstel] = useState<VerplichtingVoorstelDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [velden, setVelden] = useState<Velden | null>(null)
  const [vuil, setVuil] = useState(false)
  const [opslaanBezig, setOpslaanBezig] = useState(false)
  const [opslaanFout, setOpslaanFout] = useState<string | null>(null)
  const [checks, setChecks] = useState<VerplichtingCheckDto[] | null>(null)
  const [geblokkeerd, setGeblokkeerd] = useState(true)
  const [bijlage, setBijlage] = useState<{ url: string; contentType: string } | null>(null)
  const [aanbiedBezig, setAanbiedBezig] = useState(false)
  const [aanbiedFout, setAanbiedFout] = useState<string | null>(null)
  const [afwijsOpen, setAfwijsOpen] = useState(false)
  const [vervalOpen, setVervalOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuKnop = useRef<HTMLButtonElement | null>(null)
  const [herlaadTeller, setHerlaadTeller] = useState(0)

  const vendors = useVendorOpties(administratieId ?? '')
  const projecten = useProjectOpties(administratieId ?? '')
  const projectVerplicht = useProjectVerplicht(administratieId ?? '')

  const laad = useCallback(() => setHerlaadTeller((t) => t + 1), [])

  useEffect(() => {
    if (!administratieId || !documentId) return
    let actief = true
    setLaadFout(null)
    Promise.all([
      apiJson<DocumentDetailDto>(`/administraties/${administratieId}/documenten/${documentId}`),
      haalVerplichtingVoorstel(administratieId, documentId),
    ])
      .then(([documentDetail, voorstelData]) => {
        if (!actief) return
        setDetail(documentDetail)
        setVoorstel(voorstelData)
        setChecks(voorstelData.checks)
        setGeblokkeerd(voorstelData.checks.some((c) => c.status === 'blokkerend'))
        setVelden((huidig) => (huidig !== null && vuil ? huidig : veldenUitDto(voorstelData)))
      })
      .catch((err: unknown) => {
        if (actief) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
    // `vuil` bewust buiten de deps: een herlaad ná opslaan/aanbieden mag de velden overschrijven,
    // maar een lopende herlaad tijdens typen niet.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administratieId, documentId, herlaadTeller])

  // PDF/beeld links, zoals het controlescherm — Authorization-header vereist, dus via blob.
  useEffect(() => {
    if (!administratieId || !documentId) return
    let actief = true
    let objectUrl: string | null = null
    setBijlage(null)
    void apiFetch(`/administraties/${administratieId}/documenten/${documentId}/bestand`).then(async (resp) => {
      if (!resp.ok || !actief) return
      const blob = await resp.blob()
      objectUrl = URL.createObjectURL(blob)
      if (actief) setBijlage({ url: objectUrl, contentType: blob.type || resp.headers.get('content-type') || '' })
    })
    return () => {
      actief = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [administratieId, documentId])

  const wijzig = (patch: Partial<Velden>) => {
    setVelden((h) => (h === null ? h : { ...h, ...patch }))
    setVuil(true)
    setOpslaanFout(null)
  }

  const opslaan = async (): Promise<VerplichtingVoorstelDto | null> => {
    if (!administratieId || !documentId || !velden) return null
    setOpslaanBezig(true)
    setOpslaanFout(null)
    try {
      const nieuw = await slaVerplichtingVoorstelOp(administratieId, documentId, naarInvoer(velden))
      setVoorstel(nieuw)
      setVelden(veldenUitDto(nieuw))
      setVuil(false)
      const rapport = await voerVerplichtingChecksUit(administratieId, documentId)
      setChecks(rapport.checks)
      setGeblokkeerd(rapport.geblokkeerd)
      return nieuw
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
      return null
    } finally {
      setOpslaanBezig(false)
    }
  }

  const terAccordering = async () => {
    if (!administratieId || !documentId) return
    setAanbiedFout(null)
    if (vuil) {
      const bewaard = await opslaan()
      if (bewaard === null) return
    }
    setAanbiedBezig(true)
    try {
      // Bestaande accorderingsroute (⑥): dezelfde lagen/drempels, de service vertakt op soort.
      const resp = await apiFetch(
        `/administraties/${administratieId}/accordering/documenten/${documentId}/aanbieden`,
        { method: 'POST' },
      )
      const body: unknown = await resp.json().catch(() => null)
      if (!resp.ok) {
        const d = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
        if (d && typeof d === 'object' && 'checks' in d) {
          const rapport = (d as { checks: { checks?: VerplichtingCheckDto[] } }).checks
          if (rapport?.checks) {
            setChecks(rapport.checks)
            setGeblokkeerd(true)
          }
          setAanbiedFout('De harde checks blokkeren het aanbieden — zie Controles.')
        } else {
          setAanbiedFout(typeof d === 'string' ? d : resp.statusText || `Aanbieden mislukt (${resp.status})`)
        }
        return
      }
      toast.meld('Verplichting ter accordering aangeboden.')
      laad()
    } catch (err) {
      setAanbiedFout(err instanceof ApiError ? err.message : 'Aanbieden mislukt.')
    } finally {
      setAanbiedBezig(false)
    }
  }

  if (laadFout) {
    return <FoutMelding melding="De verplichting kon niet geladen worden." detail={laadFout} onOpnieuw={laad} />
  }
  if (!detail || !voorstel || !velden || !administratieId || !documentId) return <SkeletonPaneel />

  const bewerkbaar = BEWERKBARE_STATUSSEN.has(detail.status)
  const isGeaccordeerd = detail.status === 'geaccordeerd'
  const vervallen = voorstel.vervallen
  const drempel = voorstel.zekerheid_drempel
  const herkomstVan = (veld: VerplichtingVeld) => (vuil ? null : (voorstel.herkomst[veld] ?? null))

  return (
    <div>
      <div className="topbar">
        <h1>
          <Link to={`/?administratie=${administratieId}&soort=verplichting`}>← Werkvoorraad</Link>{' '}
          <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span> {detail.bestandsnaam}
        </h1>
        <div className="adm-select" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="chip klaar">
            verplichting{voorstel.soort_label ? ` · ${SOORT_LABEL_TEKST[voorstel.soort_label].toLowerCase()}` : ''}
          </span>
          <StatusChip status={detail.status} soort="verplichting" />
          {vervallen?.op && <Badge variant="stil">vervallen</Badge>}
          {isGeaccordeerd && !vervallen?.op && (
            <>
              <button
                ref={menuKnop}
                type="button"
                className="icon-btn"
                aria-label="Meer acties"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((o) => !o)}
              >
                ⋯
              </button>
              <AnkerPopup
                open={menuOpen}
                anker={menuKnop.current}
                kant="onder"
                uitlijning="eind"
                className="rijmenu"
                role="menu"
                onAnkerUitBeeld={() => setMenuOpen(false)}
              >
                <button
                  type="button"
                  className="linkbtn"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false)
                    setVervalOpen(true)
                  }}
                >
                  Laten vervallen…
                </button>
              </AnkerPopup>
            </>
          )}
        </div>
      </div>

      <div className="membanner">
        <div className="icon">📄</div>
        <div>
          <b>Verplichting — geen boeking.</b> Deze offerte/prijsopgave/opdrachtbevestiging gaat door de bestaande
          klant-accorderingsflow; ná het laatste akkoord staat vast wie wat op welke datum heeft goedgekeurd. Latere
          inkoopfacturen van deze leverancier worden er cumulatief tegen gematcht — de grens ís het offertebedrag.
        </div>
      </div>

      <div className="review">
        <div className="docpane">
          <div className="panel">
            <h2 style={{ marginBottom: 14 }}>Document</h2>
            <div className="bijlage-inhoud">
              {!bijlage && <SkeletonBlok />}
              {bijlage?.contentType.includes('pdf') && (
                <object key={bijlage.url} data={bijlage.url} type="application/pdf" data-testid="verplichting-pdf">
                  <p className="hint">
                    Geen inline PDF-weergave in deze browser —{' '}
                    <a href={bijlage.url} download={detail.bestandsnaam}>
                      open het bestand direct
                    </a>
                    .
                  </p>
                </object>
              )}
              {bijlage && !bijlage.contentType.includes('pdf') && (
                <p className="hint">Geen inline weergave voor dit bestandstype.</p>
              )}
            </div>
            {bijlage && (
              <p style={{ marginTop: 10 }}>
                <a className="btn secondary" href={bijlage.url} download={detail.bestandsnaam}>
                  Downloaden
                </a>
              </p>
            )}
          </div>
        </div>

        <div className="formpane">
          <AccorderingSectie
            administratieId={administratieId}
            documentId={documentId}
            documentStatus={detail.status}
            onGewijzigd={laad}
          />

          {/* Goedgekeurd-blok (mockup blok 1 "akkoord = vastgelegd wie/wanneer/welk bedrag") +
              verbruiksstand (③) + de facturen die er tegen gematcht zijn. */}
          {voorstel.goedgekeurd && (
            <div className="panel" data-testid="goedgekeurd-blok">
              <h2>
                Goedgekeurd{' '}
                {vervallen?.op ? (
                  <Badge variant="stil">vervallen</Badge>
                ) : (
                  <Badge variant="ok">akkoord vastgelegd</Badge>
                )}
              </h2>
              <p className="hint" style={{ marginTop: 0 }}>
                {formatBedrag(voorstel.goedgekeurd.bedrag_excl)} excl. — akkoord door{' '}
                <b>{voorstel.goedgekeurd.door_naam ?? 'onbekend'}</b>
                {voorstel.goedgekeurd.op ? ` op ${formatDatum(voorstel.goedgekeurd.op)}` : ''}. De opdrachtverstrekking
                is daarmee herleidbaar.
              </p>
              {voorstel.verbruik && (
                <VerbruiksBalk
                  verbruikt={voorstel.verbruik.verbruikt_excl}
                  totaal={voorstel.verbruik.totaal_excl}
                  percentage={voorstel.verbruik.percentage}
                  over={voorstel.verbruik.over_excl}
                />
              )}
              {vervallen?.op && (
                <p className="hint" data-testid="vervallen-regel">
                  Vervallen op {formatDatum(vervallen.op)} door {vervallen.door_naam ?? 'onbekend'} —{' '}
                  &ldquo;{vervallen.reden}&rdquo;. Nieuwe facturen worden hier niet meer tegen gematcht; de al
                  gematchte facturen blijven ongemoeid.
                </p>
              )}
              <h3 style={{ fontSize: 13, margin: '14px 0 6px' }}>Gekoppelde facturen</h3>
              {voorstel.gekoppelde_facturen.length === 0 ? (
                <p className="hint" style={{ margin: 0 }}>
                  Nog geen facturen tegen deze verplichting gematcht.
                </p>
              ) : (
                <div className="tabel-scroll">
                  <table className="lines" data-testid="gekoppelde-facturen">
                    <tbody>
                      <tr>
                        <th>Factuur</th>
                        <th>Datum</th>
                        <th className="amount">Bedrag excl.</th>
                        <th>Stand</th>
                      </tr>
                      {voorstel.gekoppelde_facturen.map((f) => (
                        <tr key={f.document_id}>
                          <td>
                            <Link to={`/documenten/${administratieId}/${f.document_id}`}>
                              {f.referentie ?? f.document_id.slice(0, 8)}
                            </Link>
                          </td>
                          <td>{f.factuurdatum ? formatDatumKort(f.factuurdatum) : '—'}</td>
                          <td className="amount">{formatBedrag(f.bedrag_excl)}</td>
                          <td>
                            {f.verrekend ? (
                              <Badge variant="ok">verrekend</Badge>
                            ) : (
                              <Badge variant="stil">{statusLabel(f.status)}</Badge>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          <div className="panel">
            <h2>
              Verplichting{' '}
              {voorstel.opgeslagen ? (
                <Badge variant="ok">opgeslagen</Badge>
              ) : (
                <Badge variant="warn">nog niet opgeslagen</Badge>
              )}
            </h2>
            {voorstel.ai_overgeslagen_reden && (
              <p className="hint" data-testid="ai-overgeslagen">
                AI-extractie overgeslagen: {voorstel.ai_overgeslagen_reden} — vul de velden zelf in.
              </p>
            )}

            <FormField label="Leverancier" htmlFor="verplichting-leverancier">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <SearchableCombobox
                    label="Leverancier"
                    toonLabel={false}
                    opties={vendors.opties}
                    waarde={velden.vendorId}
                    onWijzig={(id) => wijzig({ vendorId: id })}
                    placeholder="Kies crediteur…"
                    vereist
                  />
                </div>
                <HerkomstChip
                  herkomst={herkomstVan('leverancier')}
                  zekerheid={voorstel.zekerheid.leverancier}
                  drempel={drempel}
                />
              </div>
            </FormField>
            {voorstel.vendor_suggestie && velden.vendorId !== voorstel.vendor_suggestie.vendor_id && (
              <p className="hint" data-testid="vendor-suggestie">
                Voorstel uit de extractie: <b>{voorstel.vendor_suggestie.naam ?? 'onbekend'}</b>
                {voorstel.vendor_suggestie.match ? ` (herkend op ${voorstel.vendor_suggestie.match})` : ''}{' '}
                <button
                  type="button"
                  className="linkbtn"
                  onClick={() => wijzig({ vendorId: voorstel.vendor_suggestie?.vendor_id ?? null })}
                >
                  overnemen
                </button>
              </p>
            )}

            <FormField label="Soort" htmlFor="verplichting-soort">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Select
                  id="verplichting-soort"
                  value={velden.soortLabel ?? ''}
                  onChange={(e) =>
                    wijzig({ soortLabel: (e.target.value || null) as VerplichtingSoortLabel | null })
                  }
                >
                  <option value="">— kies soort —</option>
                  {SOORT_LABEL_OPTIES.map((s) => (
                    <option key={s} value={s}>
                      {SOORT_LABEL_TEKST[s]}
                    </option>
                  ))}
                </Select>
                <HerkomstChip
                  herkomst={herkomstVan('soort_label')}
                  zekerheid={voorstel.zekerheid.soort_label}
                  drempel={drempel}
                />
              </div>
            </FormField>

            <FormField label="Offertenummer" htmlFor="verplichting-nummer">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  id="verplichting-nummer"
                  value={velden.offertenummer}
                  onChange={(e) => wijzig({ offertenummer: e.target.value })}
                  placeholder="bv. 26140-OFF-01"
                />
                <HerkomstChip
                  herkomst={herkomstVan('offertenummer')}
                  zekerheid={voorstel.zekerheid.offertenummer}
                  drempel={drempel}
                />
              </div>
              <p className="hint" style={{ marginBottom: 0 }}>
                Staat dit nummer later op een factuur, dan versterkt dat de match (②).
              </p>
            </FormField>

            <FormField label="Datum" htmlFor="verplichting-datum">
              <DatePicker
                id="verplichting-datum"
                aria-label="Datum"
                value={velden.datum}
                onChange={(iso) => wijzig({ datum: iso })}
              />
            </FormField>

            <FormField label="Project" htmlFor="verplichting-project">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <SearchableCombobox
                    label="Project"
                    toonLabel={false}
                    opties={projecten.opties}
                    waarde={velden.projectId}
                    onWijzig={(id) => wijzig({ projectId: id })}
                    placeholder={projectVerplicht ? 'Kies project (verplicht)…' : 'Kies project…'}
                    vereist={projectVerplicht}
                  />
                </div>
                <HerkomstChip
                  herkomst={herkomstVan('project')}
                  zekerheid={voorstel.zekerheid.project}
                  drempel={drempel}
                />
              </div>
            </FormField>
            {voorstel.project_suggestie && velden.projectId !== voorstel.project_suggestie.project_id && (
              <p className="hint" data-testid="project-suggestie">
                Voorstel uit de extractie: <b>{voorstel.project_suggestie.naam ?? 'onbekend'}</b>
                {voorstel.project_suggestie.match ? ` (op ${voorstel.project_suggestie.match})` : ''}{' '}
                <button
                  type="button"
                  className="linkbtn"
                  onClick={() => wijzig({ projectId: voorstel.project_suggestie?.project_id ?? null })}
                >
                  overnemen
                </button>
              </p>
            )}

            <FormField label="Totaalbedrag excl. btw" htmlFor="verplichting-bedrag">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  id="verplichting-bedrag"
                  inputMode="decimal"
                  value={velden.totaalbedragExcl}
                  onChange={(e) => wijzig({ totaalbedragExcl: e.target.value })}
                  placeholder="0,00"
                />
                <HerkomstChip
                  herkomst={herkomstVan('totaalbedrag_excl')}
                  zekerheid={voorstel.zekerheid.totaalbedrag_excl}
                  drempel={drempel}
                />
              </div>
              <p className="hint" style={{ marginBottom: 0 }}>
                Dit bedrag ís de grens: facturen moeten er cumulatief binnen blijven (③, geen tolerantiemarge).
              </p>
            </FormField>

            <FormField label="Geldig t/m" htmlFor="verplichting-geldig">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <DatePicker
                  id="verplichting-geldig"
                  aria-label="Geldig t/m"
                  value={velden.geldigTot}
                  onChange={(iso) => wijzig({ geldigTot: iso })}
                />
                <HerkomstChip
                  herkomst={herkomstVan('geldig_tot')}
                  zekerheid={voorstel.zekerheid.geldig_tot}
                  drempel={drempel}
                />
              </div>
            </FormField>

            <FormField label="Omschrijving van het werk" htmlFor="verplichting-omschrijving">
              <textarea
                id="verplichting-omschrijving"
                rows={3}
                value={velden.omschrijving}
                onChange={(e) => wijzig({ omschrijving: e.target.value })}
                style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
              />
            </FormField>

            {opslaanFout && <div className="fout">{opslaanFout}</div>}
            {bewerkbaar && (
              <div className="actions">
                <Button variant="secundair" disabled={!vuil || opslaanBezig} onClick={() => void opslaan()}>
                  {opslaanBezig ? 'Opslaan…' : 'Opslaan'}
                </Button>
                {vuil && <span className="hint">Nog niet opgeslagen — "Ter accordering" bewaart eerst.</span>}
              </div>
            )}
          </div>

          <div className="inklap-rijen">
            <details data-testid="checks-inklap" open={geblokkeerd}>
              <summary>
                Controles{' '}
                {checks === null ? (
                  <span className="chip">automatisch</span>
                ) : geblokkeerd ? (
                  <span className="chip blokkerend">blokkerend</span>
                ) : (
                  <span className="chip ok">alle controles groen ✓</span>
                )}
              </summary>
              <div className="inklap-inhoud">
                {checks === null && <p className="hint">De harde controles draaien bij het openen en na opslaan.</p>}
                {checks !== null && (
                  <table className="lines">
                    <tbody>
                      {checks.map((c) => (
                        <tr key={c.naam}>
                          <td>{checkChip(c.status)}</td>
                          <td>
                            <b>{c.naam}</b>
                          </td>
                          <td>{c.melding}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </details>
          </div>

          {aanbiedFout && <div className="fout">{aanbiedFout}</div>}
          {!isGeaccordeerd && (
            <div className="panel">
              <div className="actions">
                {AFWIJSBARE_STATUSSEN.has(detail.status) && (
                  <Button variant="secundair" onClick={() => setAfwijsOpen(true)}>
                    Afwijzen…
                  </Button>
                )}
                {bewerkbaar && (
                  <Button
                    disabled={geblokkeerd || aanbiedBezig || opslaanBezig}
                    title={
                      geblokkeerd
                        ? 'De harde controles blokkeren het aanbieden — zie Controles'
                        : 'Biedt de verplichting ter accordering aan de klant-accordeurs aan'
                    }
                    onClick={() => void terAccordering()}
                  >
                    {aanbiedBezig ? 'Bezig…' : 'Ter accordering →'}
                  </Button>
                )}
              </div>
              {detail.status === 'ter_accordering' && (
                <p className="hint" style={{ marginBottom: 0 }}>
                  Ligt bij de klant-accordeur. Ná het laatste akkoord staat de verplichting op
                  &ldquo;Geaccordeerd&rdquo; — er wordt niets geboekt.
                </p>
              )}
            </div>
          )}
        </div>
      </div>

      {afwijsOpen && (
        <AfwijsModal
          administratieId={administratieId}
          documentId={documentId}
          referentie={voorstel.offertenummer}
          onAfgewezen={() => {
            setAfwijsOpen(false)
            toast.meld('Verplichting afgewezen — blijft zichtbaar ter controle.')
            laad()
          }}
          onAnnuleren={() => setAfwijsOpen(false)}
        />
      )}

      {vervalOpen && (
        <VervalDialoog
          administratieId={administratieId}
          documentId={documentId}
          offertenummer={voorstel.offertenummer}
          onKlaar={(nieuw) => {
            setVervalOpen(false)
            setVoorstel(nieuw)
            toast.meld('Verplichting laten vervallen — er worden geen nieuwe facturen meer tegen gematcht.')
          }}
          onAnnuleren={() => setVervalOpen(false)}
        />
      )}
    </div>
  )
}

/** ⑥ "Laten vervallen…" — reden VERPLICHT (niets verdwijnt stil); het document blijft geaccordeerd
 * en de al gematchte facturen blijven ongemoeid, alleen nieuwe matches stoppen. */
function VervalDialoog({
  administratieId,
  documentId,
  offertenummer,
  onKlaar,
  onAnnuleren,
}: {
  administratieId: string
  documentId: string
  offertenummer: string | null
  onKlaar: (nieuw: VerplichtingVoorstelDto) => void
  onAnnuleren: () => void
}) {
  const [reden, setReden] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const versturen = async () => {
    setBezig(true)
    setFout(null)
    try {
      onKlaar(await laatVerplichtingVervallen(administratieId, documentId, reden.trim()))
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Laten vervallen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent data-testid="verval-dialoog">
        <DialogTitle>Verplichting laten vervallen{offertenummer ? ` — ${offertenummer}` : ''}</DialogTitle>
        <DialogDescription>
          Vanaf nu worden er geen nieuwe facturen meer tegen deze verplichting gematcht. Facturen die er al aan
          gekoppeld zijn blijven ongemoeid, en het akkoord blijft in het dossier staan. De reden is verplicht.
        </DialogDescription>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void versturen()
          }}
        >
          <FormField label="Reden" htmlFor="verval-reden">
            <textarea
              id="verval-reden"
              required
              rows={3}
              value={reden}
              onChange={(e) => setReden(e.target.value)}
              placeholder="bv. opdracht is niet doorgegaan"
              style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
            />
          </FormField>
          {fout && <div className="fout">{fout}</div>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onAnnuleren} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" variant="gevaar" disabled={bezig || reden.trim() === ''}>
              {bezig ? 'Bezig…' : 'Laten vervallen'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
