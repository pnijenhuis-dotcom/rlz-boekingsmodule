import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type { DocumentActieResponseDto, DocumentListItemDto, DocumentListResponseDto, UploadResponseDto } from '../api/types'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { extractieActief } from './status'
import { StatusChip } from './StatusChip'
import { useAdministraties } from './useAdministraties'
import { VerwijderDialog } from './VerwijderDialog'

/** Ververs-interval zolang er documenten in extractie_wachtrij/extractie_bezig staan. */
const EXTRACTIE_POLL_MS = 3000

function formatDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

function formatDatumKort(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { dateStyle: 'medium' })
}

export function WerkvoorraadScreen() {
  const { administraties, fout: administratiesFout } = useAdministraties()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const administratieId = searchParams.get('administratie')
  const bestandInputRef = useRef<HTMLInputElement>(null)
  const { naamVoor } = useMedewerkers(administratieId)

  const [documenten, setDocumenten] = useState<DocumentListItemDto[] | null>(null)
  const [lijstFout, setLijstFout] = useState<string | null>(null)
  const [uploadFout, setUploadFout] = useState<string | null>(null)
  const [uploadBericht, setUploadBericht] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const [sleepActief, setSleepActief] = useState(false)
  const [toonVerwijderd, setToonVerwijderd] = useState(false)
  const [verwijderenVoor, setVerwijderenVoor] = useState<DocumentListItemDto | null>(null)
  const [verwijderenBezig, setVerwijderenBezig] = useState(false)
  const [verwijderenFout, setVerwijderenFout] = useState<string | null>(null)
  const [herstellenBezig, setHerstellenBezig] = useState<string | null>(null)
  const [herstellenFout, setHerstellenFout] = useState<string | null>(null)

  useEffect(() => {
    if (!administratieId && administraties && administraties.length > 0) {
      setSearchParams({ administratie: administraties[0].id }, { replace: true })
    }
  }, [administraties, administratieId, setSearchParams])

  const laadDocumenten = useCallback(() => {
    if (!administratieId) return
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
  // worker staan, ververst de lijst vanzelf — de statuschip loopt mee zonder handmatige reload.
  useEffect(() => {
    if (!documenten?.some((d) => extractieActief(d.status))) return
    const timer = setInterval(laadDocumenten, EXTRACTIE_POLL_MS)
    return () => clearInterval(timer)
  }, [documenten, laadDocumenten])

  const uploadBestand = useCallback(
    async (bestand: File) => {
      if (!administratieId) return
      setBezig(true)
      setUploadFout(null)
      setUploadBericht(null)
      try {
        const formData = new FormData()
        formData.append('bestand', bestand)
        const resultaat = await apiJson<UploadResponseDto>(`/administraties/${administratieId}/documenten`, {
          method: 'POST',
          body: formData,
        })
        setUploadBericht(
          resultaat.mogelijk_duplicaat_van
            ? `"${bestand.name}" geüpload — mogelijk duplicaat, gemarkeerd ter controle in de lijst.`
            : resultaat.status === 'extractie_wachtrij'
              ? `"${bestand.name}" geüpload — groot document, wordt op de achtergrond verwerkt. De status in de lijst loopt vanzelf mee.`
              : `"${bestand.name}" geüpload en in verwerking.`,
        )
        laadDocumenten()
      } catch (err) {
        setUploadFout(err instanceof Error ? err.message : 'Upload mislukt')
      } finally {
        setBezig(false)
      }
    },
    [administratieId, laadDocumenten],
  )

  const opBestandGekozen = (bestanden: FileList | null) => {
    const bestand = bestanden?.[0]
    if (bestand) void uploadBestand(bestand)
  }

  const verwijderen = async (reden: string) => {
    if (!administratieId || !verwijderenVoor) return
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
    if (!administratieId) return
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

  if (administratiesFout) {
    return <div className="fout">Kon administraties niet laden: {administratiesFout}</div>
  }
  if (!administraties) {
    return <p className="hint">Laden…</p>
  }
  if (administraties.length === 0) {
    return <p className="hint">Geen administraties gekoppeld aan uw account.</p>
  }

  return (
    <div>
      <div className="topbar">
        <h1>Werkvoorraad</h1>
        <div className="adm-select">
          <label htmlFor="administratie-select" style={{ margin: 0 }}>
            Administratie
          </label>
          <select
            id="administratie-select"
            value={administratieId ?? ''}
            onChange={(e) => setSearchParams({ administratie: e.target.value })}
          >
            {administraties.map((a) => (
              <option key={a.id} value={a.id}>
                {a.naam}
              </option>
            ))}
          </select>
          {(() => {
            // Vragen-teller (mockup klantenlijst-kolom "Vragen") — de aparte klantenlijst met
            // tellers per klant is BOUWPLAN punt 8-vervolg; tot die er is telt de werkvoorraad
            // van de geselecteerde administratie zelf, klikbaar naar de vragen-view.
            const openVragen = (documenten ?? []).filter((d) => d.status === 'vraag_open').length
            if (openVragen === 0) return null
            return (
              <Link to={`/vragen?administratie=${administratieId}`} style={{ textDecoration: 'none' }}>
                <span className="chip vraag">
                  {openVragen} {openVragen === 1 ? 'vraag' : 'vragen'} open
                </span>
              </Link>
            )
          })()}
        </div>
      </div>

      <div
        className={`upload${sleepActief ? ' dragover' : ''}`}
        onClick={() => bestandInputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setSleepActief(true)
        }}
        onDragLeave={() => setSleepActief(false)}
        onDrop={(e) => {
          e.preventDefault()
          setSleepActief(false)
          opBestandGekozen(e.dataTransfer.files)
        }}
      >
        {bezig ? (
          'Bezig met uploaden…'
        ) : (
          <>
            Sleep hier een PDF- of UBL-bestand naartoe, of <b>blader</b>
            <br />
            <span style={{ fontSize: 12 }}>Sha256-duplicaatcheck bij binnenkomst; UBL wordt automatisch geparst.</span>
          </>
        )}
        <input
          ref={bestandInputRef}
          type="file"
          accept=".pdf,.xml"
          style={{ display: 'none' }}
          onChange={(e) => opBestandGekozen(e.target.files)}
        />
      </div>
      {uploadFout && <div className="fout">{uploadFout}</div>}
      {uploadBericht && <div className="hint" style={{ marginTop: -10, marginBottom: 16 }}>{uploadBericht}</div>}

      <div className="panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <h2 style={{ margin: 0 }}>Documenten</h2>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, margin: 0 }}>
            <input
              type="checkbox"
              style={{ width: 'auto' }}
              checked={toonVerwijderd}
              onChange={(e) => setToonVerwijderd(e.target.checked)}
            />
            Toon verwijderde documenten
          </label>
        </div>
        {lijstFout && <div className="fout">{lijstFout}</div>}
        {herstellenFout && <div className="fout">{herstellenFout}</div>}
        {documenten === null && !lijstFout && <p className="hint">Laden…</p>}
        {documenten !== null && documenten.length === 0 && (
          <p className="hint">
            {toonVerwijderd ? 'Geen documenten voor deze administratie.' : 'Nog geen documenten voor deze administratie.'}
          </p>
        )}
        {documenten !== null && documenten.length > 0 && (
          <table>
            <tbody>
              <tr>
                <th>Document</th>
                <th>Status</th>
                <th>Bron</th>
                <th>Ontvangen</th>
                <th>Toegewezen</th>
                <th />
              </tr>
              {documenten.map((d) => {
                const isVerwijderd = d.status === 'verwijderd'
                // Backend blokkeert dit al hard (bewaarplicht/lopende accordering) — de UI mag de
                // onmogelijke actie dan niet eens aanbieden, ook niet als disabled-knop.
                const kanNietVerwijderdWorden = d.status === 'geboekt' || d.status === 'ter_accordering'
                // Mockup: klik op een vraag-regel opent de vráág, niet het controlescherm — de
                // vragen-view gefilterd op dit document. Een verwijderd document houdt de normale
                // detailnavigatie (herstel-route), nooit een klik naar een niet-actiefbare vraag.
                const isVraagRegel = d.status === 'vraag_open' && !isVerwijderd
                return (
                  <tr
                    key={d.id}
                    className="clickable"
                    onClick={() =>
                      navigate(
                        isVraagRegel
                          ? `/vragen?administratie=${administratieId}&document=${d.id}`
                          : `/documenten/${administratieId}/${d.id}`,
                      )
                    }
                  >
                    <td>{d.bestandsnaam}</td>
                    <td>
                      <StatusChip status={d.status} />
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
                            van {d.mogelijk_duplicaat_van.bestandsnaam} ({formatDatumKort(d.mogelijk_duplicaat_van.aangemaakt_op)})
                          </Link>
                        </div>
                      )}
                    </td>
                    <td>{d.bron}</td>
                    <td>{formatDatum(d.aangemaakt_op)}</td>
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
