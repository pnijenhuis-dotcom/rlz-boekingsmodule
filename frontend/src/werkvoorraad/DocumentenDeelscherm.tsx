import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type { DocumentActieResponseDto, DocumentListItemDto, DocumentListResponseDto } from '../api/types'
import { Checkbox } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { Breadcrumb } from './Breadcrumb'
import { documentRoute, formatBedrag, formatDatum, formatDatumKort, soortLabel } from './format'
import { extractieActief, statusLabel } from './status'
import { StatusChip } from './StatusChip'
import { VerwijderDialog } from './VerwijderDialog'

/** Ververs-interval zolang er documenten in extractie_wachtrij/extractie_bezig staan. */
const EXTRACTIE_POLL_MS = 3000

const STATUSFILTER_ALLE = 'alle'
/** Sentinel voor het autoboeken-filter — met prefix, zodat het nooit met een echte
 * DocumentStatus-waarde uit de backend kan botsen. */
const STATUSFILTER_AUTOMATISCH = '__automatisch_geboekt'

/* Documenten-deelscherm = WERKEN (IA-besluit 15-08, mockup #scherm-docs): één documentsoort
 * (of alle, incl. geboekt/verwijderd — het herstel-pad mag nooit onbereikbaar zijn),
 * segment-filters op status, zoekveld, verwijderen/herstellen. */
export function DocumentenDeelscherm({
  administratieId,
  administratieNaam,
}: {
  administratieId: string
  administratieNaam: string
}) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const soort = searchParams.get('soort')
  const { naamVoor } = useMedewerkers(administratieId)

  const [documenten, setDocumenten] = useState<DocumentListItemDto[] | null>(null)
  const [lijstFout, setLijstFout] = useState<string | null>(null)
  const [toonVerwijderd, setToonVerwijderd] = useState(false)
  const [zoekterm, setZoekterm] = useState('')
  const [statusFilter, setStatusFilter] = useState(STATUSFILTER_ALLE)
  const [verwijderenVoor, setVerwijderenVoor] = useState<DocumentListItemDto | null>(null)
  const [verwijderenBezig, setVerwijderenBezig] = useState(false)
  const [verwijderenFout, setVerwijderenFout] = useState<string | null>(null)
  const [herstellenBezig, setHerstellenBezig] = useState<string | null>(null)
  const [herstellenFout, setHerstellenFout] = useState<string | null>(null)

  const laadDocumenten = useCallback(() => {
    setLijstFout(null)
    apiJson<DocumentListResponseDto>(
      `/administraties/${administratieId}/documenten${toonVerwijderd ? '?toon_verwijderd=true' : ''}`,
    )
      .then((data) => setDocumenten(data.documenten))
      .catch((err: unknown) => setLijstFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, toonVerwijderd])

  useEffect(() => {
    setDocumenten(null)
    laadDocumenten()
  }, [laadDocumenten])

  // Live extractiestatus (async extractie): zolang er documenten in de wachtrij of bij de
  // worker staan, ververst de lijst vanzelf.
  useEffect(() => {
    if (!documenten?.some((d) => extractieActief(d.status))) return
    const timer = setInterval(laadDocumenten, EXTRACTIE_POLL_MS)
    return () => clearInterval(timer)
  }, [documenten, laadDocumenten])

  const verwijderen = async (reden: string) => {
    if (!verwijderenVoor) return
    setVerwijderenBezig(true)
    setVerwijderenFout(null)
    try {
      await apiPostJson<DocumentActieResponseDto>(
        `/administraties/${administratieId}/documenten/${verwijderenVoor.id}/verwijderen`,
        { reden: reden || null },
      )
      setVerwijderenVoor(null)
      laadDocumenten()
    } catch (err) {
      setVerwijderenFout(err instanceof ApiError ? err.message : 'Verwijderen mislukt.')
    } finally {
      setVerwijderenBezig(false)
    }
  }

  const herstellen = async (documentId: string) => {
    setHerstellenBezig(documentId)
    setHerstellenFout(null)
    try {
      await apiPostJson<DocumentActieResponseDto>(
        `/administraties/${administratieId}/documenten/${documentId}/herstellen`,
        {},
      )
      laadDocumenten()
    } catch (err) {
      setHerstellenFout(err instanceof ApiError ? err.message : 'Herstellen mislukt.')
    } finally {
      setHerstellenBezig(null)
    }
  }

  // Soort-scope (deelscherm = één soort; zonder soort-param alle documenten).
  const inScope = useMemo(
    () => (documenten === null ? null : soort ? documenten.filter((d) => d.soort === soort) : documenten),
    [documenten, soort],
  )

  const gefilterd = useMemo(() => {
    if (inScope === null) return null
    const term = zoekterm.trim().toLowerCase()
    return inScope.filter((d) => {
      if (statusFilter === STATUSFILTER_AUTOMATISCH) {
        if (!d.automatisch_geboekt) return false
      } else if (statusFilter !== STATUSFILTER_ALLE && d.status !== statusFilter) return false
      if (!term) return true
      const doorzoekbaar = [d.bestandsnaam, d.leverancier ?? '', d.totaalbedrag ?? '', statusLabel(d.status)]
        .join(' ')
        .toLowerCase()
      return doorzoekbaar.includes(term)
    })
  }, [inScope, zoekterm, statusFilter])

  const aanwezigeStatussen = useMemo(
    () => Array.from(new Set((inScope ?? []).map((d) => d.status))).sort(),
    [inScope],
  )
  const heeftAutomatischGeboekt = useMemo(() => (inScope ?? []).some((d) => d.automatisch_geboekt), [inScope])
  const aantalMetStatus = useCallback(
    (status: string) => (inScope ?? []).filter((d) => d.status === status).length,
    [inScope],
  )

  return (
    <div>
      <div className="topbar">
        <div>
          <Breadcrumb
            stappen={[
              { label: 'Werkvoorraad', naar: '/' },
              { label: administratieNaam, naar: `/?administratie=${administratieId}` },
            ]}
            huidige={soort ? soortLabel(soort) : 'Alle documenten'}
          />
          <h1>{soort ? soortLabel(soort) : 'Alle documenten'}</h1>
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, margin: 0 }}>
          <Checkbox checked={toonVerwijderd} onChange={(e) => setToonVerwijderd(e.target.checked)} />
          Toon verwijderde documenten
        </label>
      </div>

      <div className="panel">
        {/* Segment-filters (mockup #scherm-docs) + zoekveld. */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="segment" role="group" aria-label="Filter op status" style={{ flexWrap: 'wrap' }}>
            <button
              type="button"
              className={statusFilter === STATUSFILTER_ALLE ? 'actief' : undefined}
              onClick={() => setStatusFilter(STATUSFILTER_ALLE)}
            >
              Alle ({inScope?.length ?? 0})
            </button>
            {aanwezigeStatussen.map((s) => (
              <button
                type="button"
                key={s}
                className={statusFilter === s ? 'actief' : undefined}
                onClick={() => setStatusFilter(s)}
              >
                {statusLabel(s)} ({aantalMetStatus(s)})
              </button>
            ))}
            {heeftAutomatischGeboekt && (
              <button
                type="button"
                className={statusFilter === STATUSFILTER_AUTOMATISCH ? 'actief' : undefined}
                onClick={() => setStatusFilter(STATUSFILTER_AUTOMATISCH)}
              >
                Automatisch geboekt
              </button>
            )}
          </div>
          <input
            placeholder="Zoek op leverancier, bedrag, bestandsnaam…"
            aria-label="Zoek in documenten"
            style={{ maxWidth: 300 }}
            value={zoekterm}
            onChange={(e) => setZoekterm(e.target.value)}
          />
        </div>
        {lijstFout && (
          <FoutMelding
            melding="De documentenlijst kon niet geladen worden."
            detail={lijstFout}
            onOpnieuw={laadDocumenten}
          />
        )}
        {herstellenFout && <FoutMelding melding={herstellenFout} />}
        {documenten === null && !lijstFout && (
          <div className="tabel-scroll">
            <table aria-busy="true">
              <tbody>
                {Array.from({ length: 4 }, (_, r) => (
                  <tr key={r} aria-hidden="true">
                    {Array.from({ length: 6 }, (_, k) => (
                      <td key={k}>
                        <span className="skeleton" style={{ width: k === 0 ? '70%' : '50%' }} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {inScope !== null && inScope.length === 0 && (
          <p className="hint">
            {soort
              ? `Geen ${soortLabel(soort).toLowerCase()} voor deze administratie.`
              : 'Nog geen documenten voor deze administratie. Upload een factuur op de klantpagina of stuur een mail door als .eml-bestand.'}
          </p>
        )}
        {inScope !== null && inScope.length > 0 && gefilterd !== null && gefilterd.length === 0 && (
          <p className="hint">Geen documenten die aan de zoekterm of het statusfilter voldoen.</p>
        )}
        {gefilterd !== null && gefilterd.length > 0 && (
          <div className="tabel-scroll sticky-koppen">
            <table>
              <tbody>
                <tr>
                  <th>Document</th>
                  <th>Leverancier</th>
                  <th>Factuurdatum</th>
                  <th className="amount">Bedrag (incl. btw)</th>
                  <th>Status</th>
                  <th>Toegewezen</th>
                  <th />
                </tr>
                {gefilterd.map((d) => {
                  const isVerwijderd = d.status === 'verwijderd'
                  // Backend blokkeert dit al hard (bewaarplicht/lopende accordering) — de UI mag de
                  // onmogelijke actie dan niet eens aanbieden, ook niet als disabled-knop.
                  const kanNietVerwijderdWorden = d.status === 'geboekt' || d.status === 'ter_accordering'
                  const isKassarapport = d.soort === 'kassarapport'
                  const isVerkoopfactuur = d.soort === 'verkoopfactuur'
                  const isWaarborg = d.soort === 'waarborg'
                  return (
                    <tr key={d.id} className="clickable" onClick={() => navigate(documentRoute(administratieId, d))}>
                      <td>
                        {d.bestandsnaam}
                        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                          {d.bron} · {formatDatum(d.aangemaakt_op)}
                        </div>
                      </td>
                      <td>{d.leverancier ?? '—'}</td>
                      <td>{d.factuurdatum ? formatDatumKort(d.factuurdatum) : '—'}</td>
                      <td className="amount">{formatBedrag(d.totaalbedrag)}</td>
                      <td>
                        {isKassarapport && <span className="chip klaar">omzetboeking</span>}{' '}
                        {isVerkoopfactuur && <span className="chip klaar">verkoopfactuur</span>}{' '}
                        {isWaarborg && <span className="chip klaar">waarborg</span>}{' '}
                        <StatusChip status={d.status} />
                        {d.automatisch_geboekt && (
                          <>
                            {' '}
                            <span className="chip geheugen">automatisch</span>
                          </>
                        )}
                        {d.afwijzing && (
                          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
                            reden: &ldquo;{d.afwijzing.reden}&rdquo; — {naamVoor(d.afwijzing.afgewezen_door)}
                          </div>
                        )}
                        {d.mogelijk_duplicaat_van && (
                          <div style={{ marginTop: 4 }}>
                            <span className="chip vraag">Mogelijk duplicaat</span>{' '}
                            <Link
                              to={`/documenten/${administratieId}/${d.mogelijk_duplicaat_van.document_id}`}
                              onClick={(e) => e.stopPropagation()}
                              style={{ fontSize: 11.5 }}
                            >
                              van {d.mogelijk_duplicaat_van.bestandsnaam} (
                              {formatDatumKort(d.mogelijk_duplicaat_van.aangemaakt_op)})
                            </Link>
                          </div>
                        )}
                        {/* Factuurmatch (fase 2, besluit 3): afwijking als losse chip — zelfde
                            patroon als het duplicaat-signaal, geen status. */}
                        {d.factuurmatch?.uitkomst === 'afwijking' && (
                          <div style={{ marginTop: 4 }}>
                            <span className="chip vraag">Urenmatch wijkt af</span>
                            {d.factuurmatch.verschil_bedrag && (
                              <span style={{ fontSize: 11.5, color: 'var(--muted)', marginLeft: 6 }}>
                                verschil {formatBedrag(d.factuurmatch.verschil_bedrag)}
                              </span>
                            )}
                          </div>
                        )}
                        {d.factuurmatch && d.factuurmatch.uitkomst !== 'afwijking' && d.factuurmatch.tarief_ontbreekt && (
                          <div style={{ marginTop: 4 }}>
                            <span className="chip vraag">Urenmatch: geen tarief bekend</span>
                          </div>
                        )}
                      </td>
                      <td>{d.toegewezen_aan ? naamVoor(d.toegewezen_aan) : '—'}</td>
                      <td>
                        {isVerwijderd ? (
                          <button
                            type="button"
                            className="icon-btn"
                            disabled={herstellenBezig === d.id}
                            onClick={(e) => {
                              e.stopPropagation()
                              void herstellen(d.id)
                            }}
                          >
                            {herstellenBezig === d.id ? 'Bezig…' : '↺ Herstellen'}
                          </button>
                        ) : (
                          !kanNietVerwijderdWorden && (
                            <button
                              type="button"
                              className="icon-btn"
                              aria-label="Document verwijderen"
                              onClick={(e) => {
                                e.stopPropagation()
                                setVerwijderenFout(null)
                                setVerwijderenVoor(d)
                              }}
                            >
                              🗑
                            </button>
                          )
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {verwijderenVoor && (
        <VerwijderDialog
          bestandsnaam={verwijderenVoor.bestandsnaam}
          bezig={verwijderenBezig}
          fout={verwijderenFout}
          onBevestigen={(reden) => void verwijderen(reden)}
          onAnnuleren={() => setVerwijderenVoor(null)}
        />
      )}
    </div>
  )
}
