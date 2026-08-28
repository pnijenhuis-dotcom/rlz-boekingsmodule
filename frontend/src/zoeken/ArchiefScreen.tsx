import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../api/client'
import type { ArchiefDocumentDto } from '../api/types'
import { AnkerPopup } from '../ui/basis'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { amountKlasse, formatBedrag, formatDatum, formatDatumKort } from './format'
import { reviewPad } from './reviewPad'
import { haalArchiefOp } from './zoekenApi'

/** Blob-URL's van geopende PDF's na een ruime marge weer vrijgeven — het nieuwe tabblad heeft
 * het bestand dan allang geladen. */
const BLOB_OPRUIM_MS = 60_000

/** Archief per administratie (mockup #zoeken-hint + CLAUDE.md "Archief"): geboekte documenten
 * 7 jaar terugvindbaar mét PDF (bewaarplicht). Rij-klik opent het reviewscherm van de juiste
 * soort; de PDF/UBL komt via het bestaande bestand-endpoint als blob in een nieuw tabblad. */
export function ArchiefScreen() {
  const navigate = useNavigate()
  const { administraties, fout: administratiesFout } = useAdministraties()
  const [administratieId, setAdministratieId] = useState('')
  const [documenten, setDocumenten] = useState<ArchiefDocumentDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bestandFout, setBestandFout] = useState<string | null>(null)
  const [herlaad, setHerlaad] = useState(0)
  // ⋯-menu per rij (tegenboek-mockup 22-08): PDF openen + "Tegenboeken…" als tweede ingang.
  const [menuOpen, setMenuOpen] = useState<string | null>(null)
  // Anker per rij voor het ⋯-menu: het menu rendert via AnkerPopup op documentniveau (portal +
  // fixed) — als absoluut kind van de cel werd het door `table { overflow: hidden }` afgekapt
  // (zelfde fout als de verzamelbak-preview, feedbackronde 26-08 punt 2).
  const menuKnoppen = useRef<Record<string, HTMLButtonElement | null>>({})

  // Eén administratie in scope (bv. klant-accordeur): meteen die kiezen, geen lege select.
  useEffect(() => {
    if (administraties?.length === 1) setAdministratieId(administraties[0].id)
  }, [administraties])

  useEffect(() => {
    if (!administratieId) {
      setDocumenten(null)
      return
    }
    setDocumenten(null)
    setFout(null)
    let actief = true
    haalArchiefOp(administratieId)
      .then((data) => {
        if (actief) setDocumenten(data.documenten)
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, herlaad])

  const openBestand = async (doc: ArchiefDocumentDto) => {
    setBestandFout(null)
    try {
      const resp = await apiFetch(`/administraties/${administratieId}/documenten/${doc.document_id}/bestand`)
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

  if (administratiesFout) {
    return (
      <FoutMelding
        melding="Uw administraties konden niet geladen worden. Controleer de verbinding en probeer het opnieuw."
        detail={administratiesFout}
        onOpnieuw={() => window.location.reload()}
      />
    )
  }

  return (
    <div>
      <div className="topbar">
        <h1>Archief</h1>
        <div className="adm-select">
          <span style={{ margin: 0 }}>Administratie</span>
          <AdministratieCombobox
            label="Administratie"
            toonLabel={false}
            administraties={administraties ?? []}
            waarde={administratieId}
            onWijzig={setAdministratieId}
            placeholder="— kies een administratie —"
          />
        </div>
      </div>

      <div className="panel">
        {!administratieId && (
          <p className="hint">
            Kies een administratie om het archief te openen: alle geboekte documenten, 7 jaar terugvindbaar mét PDF
            (bewaarplicht).
          </p>
        )}

        {administratieId && fout && (
          <FoutMelding
            melding="Het archief kon niet geladen worden."
            detail={fout}
            onOpnieuw={() => setHerlaad((h) => h + 1)}
          />
        )}
        {bestandFout && <FoutMelding melding={bestandFout} />}

        {administratieId && !fout && documenten === null && (
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
        )}

        {administratieId && documenten !== null && documenten.length === 0 && (
          <p className="hint">
            Nog geen geboekte documenten voor deze administratie. Zodra er geboekt wordt, blijft elk stuk hier 7 jaar
            terugvindbaar mét PDF (bewaarplicht).
          </p>
        )}

        {administratieId && documenten !== null && documenten.length > 0 && (
          <table>
            <tbody>
              <tr>
                <th>Document</th>
                <th>Referentie</th>
                <th>Boekstuk</th>
                <th className="amount">Bedrag</th>
                <th>Geboekt op</th>
                <th />
              </tr>
              {documenten.map((doc) => (
                <tr
                  key={doc.document_id}
                  className="clickable"
                  onClick={() => navigate(reviewPad(doc.soort, administratieId, doc.document_id))}
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
                  <td>
                    {doc.geboekt_op ? formatDatum(doc.geboekt_op) : formatDatumKort(doc.factuurdatum)}
                    {doc.automatisch_geboekt && (
                      <>
                        {' '}
                        <span className="chip geheugen">automatisch</span>
                      </>
                    )}
                    {doc.tegengeboekt && (
                      <>
                        {' '}
                        <span className="chip afwijking" title="Deze boeking is tegengeboekt — kruisverwijzing op de documentpagina">
                          TEGENGEBOEKT
                        </span>
                      </>
                    )}
                  </td>
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
                        {/* Tegenboek-ingang (mockup 22-08): opent het controlescherm mét de
                            tegenboek-flow open; alleen zinvol op inkoopfacturen — de sectie
                            zelf toetst server-side of storno écht geblokkeerd is. */}
                        {doc.soort === 'inkoopfactuur' && !doc.tegengeboekt && (
                          <button
                            type="button"
                            className="linkbtn"
                            role="menuitem"
                              onClick={() => {
                              setMenuOpen(null)
                              navigate(`${reviewPad(doc.soort, administratieId, doc.document_id)}?tegenboeken=1`)
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
        )}
      </div>
    </div>
  )
}
