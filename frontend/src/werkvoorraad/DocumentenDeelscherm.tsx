import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type { DocumentActieResponseDto, DocumentListItemDto, DocumentListResponseDto, VraagDto } from '../api/types'
import { haalRekeningen, type RekeningenDto } from '../bank/bankApi'
import { haalUrenStand, type UrenStandDto } from '../meerwerk/meerwerkApi'
import { Checkbox } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { haalVragenOp } from '../vragen/vragenApi'
import { Breadcrumb } from './Breadcrumb'
import { documentRoute, formatBedrag, formatDatum, formatDatumKort, isOpenstaand, soortLabel } from './format'
import { KlantUpload } from './KlantStanden'
import { extractieActief, statusLabel } from './status'
import { StatusChip } from './StatusChip'
import { VerwijderDialog } from './VerwijderDialog'

/** Ververs-interval zolang er documenten in extractie_wachtrij/extractie_bezig staan. */
const EXTRACTIE_POLL_MS = 3000

const STATUSFILTER_ALLE = 'alle'
/** Sentinel voor het autoboeken-filter — met prefix, zodat het nooit met een echte
 * DocumentStatus-waarde uit de backend kan botsen. */
const STATUSFILTER_AUTOMATISCH = '__automatisch_geboekt'
/** Sentinel voor het duplicaatsignaal-filter (besluit 25-08, deel 2 punt 6) — zelfde prefix-regel. */
export const STATUSFILTER_DUPLICAAT = '__mogelijk_duplicaat'

/** Vaste tab-volgorde (mockup-norm 25-08: minimaal Inkoopfacturen / Verkoopfacturen); onbekende
 * soorten volgen alfabetisch achteraan. Alleen soorten met teller > 0 krijgen een tab. */
const SOORT_VOLGORDE = ['inkoopfactuur', 'verkoopfactuur', 'kassarapport', 'waarborg']
/** Expliciete "alle documenten"-tab (incl. geboekt/verwijderd — het herstel-pad mag nooit
 * onbereikbaar zijn); zonder `soort`-param kiest het scherm de eerste tab met open werk. */
export const SOORT_ALLE = 'alle'

/** Eén duplicaat-begrip voor filter en teller: het gecachete RLZ-signaal óf de bestandsinhoud-
 * match bij upload (`mogelijk_duplicaat_van`). */
function isMogelijkDuplicaat(d: DocumentListItemDto): boolean {
  return d.duplicaatsignaal?.uitkomst === 'mogelijk_duplicaat' || d.mogelijk_duplicaat_van !== null
}

/* Klantlanding = documentenlijst (besluit Peter 25-08, feedbackronde punt C — herziet het
 * IA-besluit 15-08 "klantpagina = standen-tussenlaag"): klik op een klant landt hier, met tabs
 * per soort (alleen soorten met teller > 0), een compacte klikbare chip-rij met de overige
 * standen (bank per rekening, vragen, bij klant, afgewezen, IBAN, meerwerk, standen-overzicht) en
 * de klant-upload. Daaronder het bestaande deelscherm: segment-filters op status (voorkiesbaar
 * via `?status=`), zoekveld, verwijderen/herstellen. */
export function DocumentenDeelscherm({
  administratieId,
  administratieNaam,
}: {
  administratieId: string
  administratieNaam: string
}) {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const soortParam = searchParams.get('soort')
  const statusParam = searchParams.get('status')
  const { naamVoor } = useMedewerkers(administratieId)

  const [documenten, setDocumenten] = useState<DocumentListItemDto[] | null>(null)
  const [lijstFout, setLijstFout] = useState<string | null>(null)
  const [toonVerwijderd, setToonVerwijderd] = useState(false)
  const [zoekterm, setZoekterm] = useState('')
  const [statusFilter, setStatusFilter] = useState(statusParam ?? STATUSFILTER_ALLE)
  // Chip-rij-standen (verrijking — een fout hier blokkeert de lijst nooit, zelfde patroon als de
  // standen-pagina).
  const [rekeningen, setRekeningen] = useState<RekeningenDto | null>(null)
  const [vragen, setVragen] = useState<VraagDto[] | null>(null)
  const [urenStand, setUrenStand] = useState<UrenStandDto | null>(null)
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

  // `?status=` uit een chip (Bij klant / Afgewezen / IBAN) kiest het segment-filter voor.
  useEffect(() => {
    setStatusFilter(statusParam ?? STATUSFILTER_ALLE)
  }, [statusParam])

  useEffect(() => {
    let actueel = true
    setRekeningen(null)
    setVragen(null)
    setUrenStand(null)
    haalRekeningen(administratieId)
      .then((data) => {
        if (actueel) setRekeningen(data)
      })
      .catch(() => undefined)
    haalVragenOp(administratieId, { status: 'open' })
      .then((data) => {
        if (actueel) setVragen(data.vragen)
      })
      .catch(() => undefined)
    // Uren & meerwerk: 403/409 = blok bestaat niet voor deze gebruiker/administratie (toon-regel).
    haalUrenStand(administratieId)
      .then((data) => {
        if (actueel) setUrenStand(data)
      })
      .catch(() => undefined)
    return () => {
      actueel = false
    }
  }, [administratieId])

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

  // Tabs per soort: alleen soorten met openstaand werk (toon-regel), in vaste volgorde.
  const openPerSoort = useMemo(() => {
    const tellers = new Map<string, number>()
    for (const d of documenten ?? []) {
      if (isOpenstaand(d)) tellers.set(d.soort, (tellers.get(d.soort) ?? 0) + 1)
    }
    return tellers
  }, [documenten])
  const tabs = useMemo(
    () =>
      Array.from(openPerSoort.keys()).sort((a, b) => {
        const ia = SOORT_VOLGORDE.indexOf(a)
        const ib = SOORT_VOLGORDE.indexOf(b)
        return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b)
      }),
    [openPerSoort],
  )
  // Zonder soort-param: de eerste tab met open werk; niets open → alle documenten.
  const soort: string | null =
    soortParam === SOORT_ALLE ? null : soortParam ?? (documenten === null ? null : (tabs[0] ?? null))
  const toontAlle = documenten !== null && soort === null

  // Soort-scope (tab = één soort; "alle" = alle documenten incl. geboekt/verwijderd).
  const inScope = useMemo(
    () => (documenten === null ? null : soort ? documenten.filter((d) => d.soort === soort) : documenten),
    [documenten, soort],
  )

  // Chip-rij-standen.
  // Status-tellers over álle documenten (niet alleen "openstaand": bij-klant/afgewezen zijn
  // eigen standen, ongeacht hoe isOpenstaand ze indeelt).
  const alle = documenten ?? []
  const terAccordering = alle.filter((d) => d.status === 'ter_accordering').length
  const afgewezen = alle.filter((d) => d.status === 'afgewezen').length
  const ibanWachtend = alle.filter((d) => d.status === 'wacht_op_iban_accordering').length
  const openVragen = vragen?.length ?? 0
  const openRekeningen = (rekeningen?.rekeningen ?? []).filter((r) => r.open_mutaties > 0)
  const meerwerkOpen = urenStand
    ? urenStand.meerwerk_te_beoordelen + urenStand.meerwerk_nog_doorbelasten + urenStand.urenstaten_wachten_op_keuring
    : 0
  const naarTab = (s: string) => navigate(`/?administratie=${administratieId}&soort=${s}`)
  const naarStatus = (status: string) =>
    navigate(`/?administratie=${administratieId}${soortParam ? `&soort=${soortParam}` : ''}&status=${status}`)

  const gefilterd = useMemo(() => {
    if (inScope === null) return null
    const term = zoekterm.trim().toLowerCase()
    return inScope.filter((d) => {
      if (statusFilter === STATUSFILTER_AUTOMATISCH) {
        if (!d.automatisch_geboekt) return false
      } else if (statusFilter === STATUSFILTER_DUPLICAAT) {
        if (!isMogelijkDuplicaat(d)) return false
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
  const aantalMogelijkDuplicaat = useMemo(() => (inScope ?? []).filter(isMogelijkDuplicaat).length, [inScope])
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
            huidige={soort ? soortLabel(soort) : toontAlle ? 'Alle documenten' : 'Te verwerken'}
          />
          <h1>{administratieNaam}</h1>
        </div>
        {ibanWachtend > 0 && (
          <span className="chip blokkerend">
            {ibanWachtend} IBAN-{ibanWachtend === 1 ? 'accordering' : 'accorderingen'} wachtend
          </span>
        )}
      </div>

      {/* Chip-rij met de overige standen (besluit 25-08, C2): klikbaar naar de bestaande deelschermen;
          alleen chips met teller > 0 (toon-regel) + de vaste ingang naar het standen-overzicht. */}
      <div className="standen-chips" role="navigation" aria-label="Overige standen">
        {openRekeningen.map((r) => (
          <button
            type="button"
            key={r.id}
            className="chip klaar klikbaar"
            onClick={() => navigate(`/bank/${administratieId}?rekening=${r.id}`)}
            title={r.iban ?? undefined}
          >
            🏦 {r.naam}: {r.open_mutaties} af te letteren
          </button>
        ))}
        {openVragen > 0 && (
          <button
            type="button"
            className="chip vraag klikbaar"
            onClick={() => navigate(`/?administratie=${administratieId}&sectie=vragen`)}
          >
            ❓ {openVragen} {openVragen === 1 ? 'open vraag' : 'open vragen'} — blokkeert boeken
          </button>
        )}
        {terAccordering > 0 && (
          <button type="button" className="chip geheugen klikbaar" onClick={() => naarStatus('ter_accordering')}>
            👤 {terAccordering} bij klant ter accordering
          </button>
        )}
        {afgewezen > 0 && (
          <button type="button" className="chip vraag klikbaar" onClick={() => naarStatus('afgewezen')}>
            ✕ {afgewezen} afgewezen — ter controle
          </button>
        )}
        {ibanWachtend > 0 && (
          <button
            type="button"
            className="chip blokkerend klikbaar"
            onClick={() => naarStatus('wacht_op_iban_accordering')}
          >
            IBAN-wissel: {ibanWachtend} wacht op accordering
          </button>
        )}
        {urenStand && meerwerkOpen > 0 && (
          <button
            type="button"
            className="chip klaar klikbaar"
            onClick={() => navigate(`/meerwerk?administratie=${administratieId}`)}
          >
            🛠 {meerwerkOpen} meerwerk/urenstaten te beoordelen
          </button>
        )}
        <Link className="chip klikbaar" to={`/?administratie=${administratieId}&sectie=standen`}>
          Standen &amp; overzicht ›
        </Link>
      </div>

      <KlantUpload administratieId={administratieId} onGeupload={laadDocumenten} />

      <div className="panel">
        {/* Tabs per soort (besluit 25-08, C1): alleen soorten met teller > 0; "Alle documenten"
            houdt het herstel-pad (geboekt/verwijderd) bereikbaar. */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <div className="segment tabs-soort" role="tablist" aria-label="Documentsoort">
            {tabs.map((t) => (
              <button
                type="button"
                role="tab"
                key={t}
                aria-selected={soort === t}
                className={soort === t ? 'actief' : undefined}
                onClick={() => naarTab(t)}
              >
                {soortLabel(t)} ({openPerSoort.get(t) ?? 0})
              </button>
            ))}
            <button
              type="button"
              role="tab"
              aria-selected={toontAlle}
              className={toontAlle ? 'actief' : undefined}
              onClick={() => naarTab(SOORT_ALLE)}
              title="Alle documenten van deze klant, incl. geboekt en verwijderd (herstel-pad)"
            >
              Alle documenten
            </button>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, margin: 0 }}>
            <Checkbox checked={toonVerwijderd} onChange={(e) => setToonVerwijderd(e.target.checked)} />
            Toon verwijderde documenten
          </label>
        </div>
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
            {aantalMogelijkDuplicaat > 0 && (
              <button
                type="button"
                className={statusFilter === STATUSFILTER_DUPLICAAT ? 'actief' : undefined}
                onClick={() => setStatusFilter(STATUSFILTER_DUPLICAAT)}
                title="Documenten waarvan de gecachete RLZ-duplicaatcheck een bestaande factuur met dezelfde crediteur, referentie en bedrag vond (of met dezelfde bestandsinhoud)"
              >
                Mogelijk duplicaat ({aantalMogelijkDuplicaat})
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
              : 'Nog geen documenten voor deze administratie. Upload hierboven een factuur of stuur een mail door als .eml-bestand.'}
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
                        {/* Duplicaatsignaal (besluit 25-08, deel 2 punt 6): de gecachete
                            RLZ-duplicaatuitkomst als chip ónder de status — signalering, de
                            live check bij het boeken blijft bindend. */}
                        {d.duplicaatsignaal?.uitkomst === 'mogelijk_duplicaat' && (
                          <div style={{ marginTop: 4 }}>
                            <span
                              className="chip vraag"
                              title={`${d.duplicaatsignaal.aantal_treffers} bestaande factuur/facturen in RLZ met dezelfde crediteur, referentie en bedrag (getoetst ${formatDatumKort(d.duplicaatsignaal.berekend_op)}). De live check bij het boeken is bindend.`}
                            >
                              Mogelijk duplicaat in RLZ
                            </span>
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
