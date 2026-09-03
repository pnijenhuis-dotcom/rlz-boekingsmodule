import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { apiFetch } from '../api/client'
import type { ArchiefKantoorbreedDocumentDto, ArchiefKantoorbreedResponseDto } from '../api/types'
import { AnkerPopup, Paginering } from '../ui/basis'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  type ArchiefSorteerKolom,
  archiefSorteringNaarParam,
  archiefSorteringUitParam,
  volgendeArchiefSortering,
} from './archiefSortering'
import { amountKlasse, formatBedrag, formatDatum, formatDatumKort } from './format'
import { reviewPad } from './reviewPad'
import { ARCHIEF_PER_PAGINA, haalArchiefKantoorbreedOp } from './zoekenApi'

/** Blob-URL's van geopende PDF's na een ruime marge weer vrijgeven — het nieuwe tabblad heeft
 * het bestand dan allang geladen. */
const BLOB_OPRUIM_MS = 60_000
/** Zoekveld: pas ná een korte rust naar de server (één request per zoekopdracht, niet per toets). */
const ZOEK_DEBOUNCE_MS = 300

/** Archief — KANTOORBREED bladeren (B4 design-ronde 03-09, mockup inzicht-kantoorbreed.html ⑥ =
 * bouwnorm; principe minimale mens 02-09): één lijst over álle administraties in scope, de
 * administratie is een facet-filter (leeg = alle) en nooit een poort. Server-side paginering (25),
 * datumvenster (default 12 maanden op boekmoment — door de server ingevuld en hier zichtbaar),
 * zoekveld, sorteerbare koppen (conventie punt 21: oplopend → aflopend → uit, pijl + aria-sort,
 * `sort=<kolom>:<richting>`). Álle filters + sortering + pagina staan in de URL (deelbaar,
 * terugweg-vast; `/archief?administratie=X` = voorgevulde facet vanaf de klantpagina). Elke rij
 * draagt zijn eigen administratie: rij-klik en het ⋯-menu (PDF openen, Tegenboeken…) werken dáármee. */
export function ArchiefScreen() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { administraties, fout: administratiesFout } = useAdministraties()

  const administratieId = searchParams.get('administratie') ?? ''
  const van = searchParams.get('van') ?? ''
  const tot = searchParams.get('tot') ?? ''
  const q = searchParams.get('q') ?? ''
  const sortParam = searchParams.get('sort')
  const sortering = useMemo(() => archiefSorteringUitParam(sortParam), [sortParam])
  const pagina = Math.max(1, Number(searchParams.get('pagina') ?? '1') || 1)

  const [resultaat, setResultaat] = useState<ArchiefKantoorbreedResponseDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bestandFout, setBestandFout] = useState<string | null>(null)
  const [herlaad, setHerlaad] = useState(0)
  // Zoekveld: lokale invoer, met debounce naar de URL (die de request stuurt).
  const [zoekInvoer, setZoekInvoer] = useState(q)
  // ⋯-menu per rij (tegenboek-mockup 22-08): PDF openen + "Tegenboeken…" als tweede ingang.
  const [menuOpen, setMenuOpen] = useState<string | null>(null)
  // Anker per rij: het menu rendert via AnkerPopup op documentniveau (portal + fixed) — als
  // absoluut kind van de cel kapt `table { overflow: hidden }` het af (feedbackronde 26-08 punt 2).
  const menuKnoppen = useRef<Record<string, HTMLButtonElement | null>>({})

  /** Eén schrijver voor de URL-state: filters wijzigen = terug naar pagina 1 (tenzij anders). */
  const zetParams = (wijzigingen: Record<string, string | null>, opties: { houdPagina?: boolean } = {}) => {
    const p = new URLSearchParams(searchParams)
    for (const [sleutel, waarde] of Object.entries(wijzigingen)) {
      if (waarde) p.set(sleutel, waarde)
      else p.delete(sleutel)
    }
    if (!opties.houdPagina) p.delete('pagina')
    setSearchParams(p, { replace: true })
  }

  useEffect(() => {
    if (zoekInvoer === q) return
    const timer = setTimeout(() => zetParams({ q: zoekInvoer.trim() || null }), ZOEK_DEBOUNCE_MS)
    return () => clearTimeout(timer)
    // zetParams sluit over searchParams; bewust alleen op de invoer triggeren.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoekInvoer])

  useEffect(() => {
    setResultaat(null)
    setFout(null)
    let actief = true
    haalArchiefKantoorbreedOp({ pagina, van, tot, q, sort: sortParam, administratieId })
      .then((data) => {
        if (actief) setResultaat(data)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, van, tot, q, sortParam, pagina, herlaad])

  const sorteerOp = (kolom: ArchiefSorteerKolom) => {
    zetParams({ sort: archiefSorteringNaarParam(volgendeArchiefSortering(sortering, kolom)) })
  }

  /** Klikbare kolomkop (punt 21): oplopend → aflopend → uit, mét pijl-indicator en aria-sort. */
  const sorteerKop = (kolom: ArchiefSorteerKolom, label: string, className?: string) => {
    const actief = sortering?.kolom === kolom ? sortering.richting : null
    return (
      <th className={className} aria-sort={actief === 'asc' ? 'ascending' : actief === 'desc' ? 'descending' : 'none'}>
        <button
          type="button"
          className={`th-sort${actief ? ' actief' : ''}`}
          onClick={() => sorteerOp(kolom)}
          title={
            actief === 'asc'
              ? `Gesorteerd oplopend op ${label.toLowerCase()} — klik voor aflopend`
              : actief === 'desc'
                ? `Gesorteerd aflopend op ${label.toLowerCase()} — klik om de sortering op te heffen`
                : `Sorteer oplopend op ${label.toLowerCase()}`
          }
        >
          {label}
          <span className="th-sort-pijl" aria-hidden="true">
            {actief === 'asc' ? '▲' : actief === 'desc' ? '▼' : '↕'}
          </span>
        </button>
      </th>
    )
  }

  const openBestand = async (doc: ArchiefKantoorbreedDocumentDto) => {
    setBestandFout(null)
    try {
      const resp = await apiFetch(`/administraties/${doc.administratie_id}/documenten/${doc.document_id}/bestand`)
      if (!resp.ok) throw new Error(`Bestand ophalen mislukt (${resp.status})`)
      const url = URL.createObjectURL(await resp.blob())
      window.open(url, '_blank', 'noopener')
      setTimeout(() => URL.revokeObjectURL(url), BLOB_OPRUIM_MS)
    } catch (err) {
      setBestandFout(
        err instanceof Error ? `${doc.bestandsnaam}: ${err.message}` : `${doc.bestandsnaam}: openen mislukt.`,
      )
    }
  }

  // Facet-kiezer: álle administraties in scope, mét het aantal uit de facetwaarden waar bekend —
  // zo blijft een administratie zonder documenten in dit venster wél kiesbaar (en herkenbaar leeg).
  const facetOpties = useMemo(() => {
    const aantallen = new Map((resultaat?.facet ?? []).map((f) => [f.administratie_id, f.aantal] as const))
    return (administraties ?? []).map((a) => ({
      id: a.id,
      naam: aantallen.has(a.id) ? `${a.naam} (${aantallen.get(a.id)})` : a.naam,
    }))
  }, [administraties, resultaat])

  if (administratiesFout) {
    return (
      <FoutMelding
        melding="Uw administraties konden niet geladen worden. Controleer de verbinding en probeer het opnieuw."
        detail={administratiesFout}
        onOpnieuw={() => window.location.reload()}
      />
    )
  }

  const documenten = resultaat?.documenten ?? null
  const totaal = resultaat?.totaal ?? 0
  const meerdereAdministraties = (administraties?.length ?? 0) > 1

  return (
    <div>
      <div className="topbar">
        <h1>Archief</h1>
        {meerdereAdministraties && (
          <div className="adm-select">
            <span style={{ margin: 0 }}>Administratie</span>
            <AdministratieCombobox
              label="Administratie"
              toonLabel={false}
              administraties={facetOpties}
              waarde={administratieId || null}
              onWijzig={(id) => zetParams({ administratie: id })}
              placeholder="Alle administraties"
            />
            {administratieId && (
              <button type="button" className="linkbtn" onClick={() => zetParams({ administratie: null })}>
                Alle administraties
              </button>
            )}
          </div>
        )}
      </div>

      <div className="panel">
        {fout && (
          <FoutMelding
            melding="Het archief kon niet geladen worden."
            detail={fout}
            onOpnieuw={() => setHerlaad((h) => h + 1)}
          />
        )}
        {bestandFout && <FoutMelding melding={bestandFout} />}

        <div className="filters" style={{ display: 'flex', alignItems: 'flex-end', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
          <label style={{ display: 'grid', gap: 4, fontSize: 12, margin: 0 }}>
            Zoeken
            <input
              type="search"
              value={zoekInvoer}
              onChange={(e) => setZoekInvoer(e.target.value)}
              placeholder="leverancier, referentie, boekstuk of bedrag"
              style={{ width: 260, maxWidth: '100%' }}
            />
          </label>
          <label style={{ display: 'grid', gap: 4, fontSize: 12, margin: 0 }}>
            Geboekt van
            <input type="date" value={van || resultaat?.van || ''} onChange={(e) => zetParams({ van: e.target.value || null })} />
          </label>
          <label style={{ display: 'grid', gap: 4, fontSize: 12, margin: 0 }}>
            tot en met
            <input type="date" value={tot || resultaat?.tot || ''} onChange={(e) => zetParams({ tot: e.target.value || null })} />
          </label>
          {resultaat && (
            <span className="hint" style={{ margin: 0 }}>
              {totaal} {totaal === 1 ? 'document' : 'documenten'}
              {!administratieId && meerdereAdministraties && (
                <>
                  {' '}
                  over {resultaat.administraties_met_documenten}{' '}
                  {resultaat.administraties_met_documenten === 1 ? 'administratie' : 'administraties'}
                </>
              )}
            </span>
          )}
        </div>

        {!fout && documenten === null && (
          <table aria-busy="true">
            <tbody>
              {Array.from({ length: 4 }, (_, r) => (
                <tr key={r} aria-hidden="true">
                  {Array.from({ length: 7 }, (_, k) => (
                    <td key={k}>
                      <span className="skeleton" style={{ width: k === 0 ? '70%' : '50%' }} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {documenten !== null && documenten.length === 0 && (
          <p className="hint">
            {totaal === 0
              ? 'Geen geboekte documenten in dit datumvenster. Verruim het venster of pas het zoekfilter aan — elk geboekt stuk blijft hier 7 jaar terugvindbaar mét PDF (bewaarplicht).'
              : 'Deze pagina is leeg — ga terug naar een eerdere pagina.'}
          </p>
        )}

        {documenten !== null && documenten.length > 0 && (
          <div className="tabel-scroll">
            <table>
              <tbody>
                <tr>
                  {sorteerKop('leverancier', 'Document')}
                  <th>Referentie</th>
                  {sorteerKop('boekstuk', 'Boekstuk')}
                  {sorteerKop('bedrag', 'Bedrag', 'amount')}
                  {sorteerKop('factuurdatum', 'Factuurdatum')}
                  {sorteerKop('geboekt_op', 'Geboekt op')}
                  {meerdereAdministraties && sorteerKop('administratie', 'Administratie')}
                  <th />
                </tr>
                {documenten.map((doc) => (
                  <tr
                    key={doc.document_id}
                    className="clickable"
                    onClick={() => navigate(reviewPad(doc.soort, doc.administratie_id, doc.document_id))}
                  >
                    <td>
                      {doc.leverancier ?? doc.bestandsnaam}
                      {doc.leverancier && (
                        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{doc.bestandsnaam}</div>
                      )}
                    </td>
                    <td>{doc.referentie ?? '—'}</td>
                    <td>{doc.rlz_boekstuknummer ?? '—'}</td>
                    <td className={amountKlasse(doc.totaalbedrag)}>{formatBedrag(doc.totaalbedrag)}</td>
                    <td>{formatDatumKort(doc.factuurdatum)}</td>
                    <td>
                      {doc.geboekt_op ? formatDatum(doc.geboekt_op) : '—'}
                      {doc.automatisch_geboekt && (
                        <>
                          {' '}
                          <span className="chip geheugen">automatisch</span>
                        </>
                      )}
                      {doc.tegengeboekt && (
                        <>
                          {' '}
                          <span
                            className="chip afwijking"
                            title="Deze boeking is tegengeboekt — kruisverwijzing op de documentpagina"
                          >
                            TEGENGEBOEKT
                          </span>
                        </>
                      )}
                    </td>
                    {meerdereAdministraties && <td>{doc.administratie_naam}</td>}
                    <td>
                      <button
                        ref={(el) => {
                          menuKnoppen.current[doc.document_id] = el
                        }}
                        type="button"
                        className="icon-btn"
                        aria-label={`Acties voor ${doc.bestandsnaam}`}
                        aria-expanded={menuOpen === doc.document_id}
                        onClick={(e) => {
                          e.stopPropagation()
                          setMenuOpen((h) => (h === doc.document_id ? null : doc.document_id))
                        }}
                      >
                        ⋯
                      </button>
                      <AnkerPopup
                        open={menuOpen === doc.document_id}
                        anker={menuKnoppen.current[doc.document_id] ?? null}
                        kant="onder"
                        uitlijning="eind"
                        className="rijmenu"
                        role="menu"
                        onAnkerUitBeeld={() => setMenuOpen(null)}
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          type="button"
                          className="linkbtn"
                          role="menuitem"
                          onClick={() => {
                            setMenuOpen(null)
                            void openBestand(doc)
                          }}
                        >
                          PDF openen
                        </button>
                        {/* Tegenboek-ingang (mockup 22-08): opent het controlescherm mét de tegenboek-flow
                            open; alleen zinvol op inkoopfacturen — de sectie zelf toetst server-side of
                            storno écht geblokkeerd is. */}
                        {doc.soort === 'inkoopfactuur' && !doc.tegengeboekt && (
                          <button
                            type="button"
                            className="linkbtn"
                            role="menuitem"
                            onClick={() => {
                              setMenuOpen(null)
                              navigate(`${reviewPad(doc.soort, doc.administratie_id, doc.document_id)}?tegenboeken=1`)
                            }}
                          >
                            Tegenboeken…
                          </button>
                        )}
                      </AnkerPopup>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {documenten !== null && (
          <Paginering
            pagina={pagina}
            totaal={totaal}
            grootte={ARCHIEF_PER_PAGINA}
            onPagina={(p) => zetParams({ pagina: String(p) }, { houdPagina: true })}
            label="documenten"
          />
        )}
      </div>
    </div>
  )
}
