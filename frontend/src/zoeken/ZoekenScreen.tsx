import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ZoekAccorderingHitDto, ZoekDocumentHitDto, ZoekResponseDto } from '../api/types'
import { FoutMelding } from '../ui/FoutMelding'
import { StatusChip } from '../werkvoorraad/StatusChip'
import { formatBedrag, formatDatumKort, formatDatum } from './format'
import { reviewPad } from './reviewPad'
import { zoek } from './zoekenApi'

/** Zoeken vanaf 2 tekens, met debounce — geen aanroep per toetsaanslag. */
const MIN_TERM_LENGTE = 2
const DEBOUNCE_MS = 300
/** Compacte weergaven: eerste ~60 tekens van een vraag, ~100 tekens audit-detail. */
const VRAAG_MAX_TEKENS = 60
const DETAIL_MAX_TEKENS = 100

function kort(tekst: string, max: number): string {
  return tekst.length > max ? `${tekst.slice(0, max)}…` : tekst
}

/** Audit-detail (vrij JSON-object) compact als "sleutel: waarde · sleutel: waarde". */
function detailSamenvatting(detail: Record<string, unknown> | null): string {
  if (!detail) return '—'
  const tekst = Object.entries(detail)
    .map(
      ([sleutel, waarde]) =>
        `${sleutel}: ${typeof waarde === 'object' && waarde !== null ? JSON.stringify(waarde) : String(waarde)}`,
    )
    .join(' · ')
  return tekst ? kort(tekst, DETAIL_MAX_TEKENS) : '—'
}

/** Mockup-historie: "akkoord S. Bakker (laag 1) 17-06"; een open stap toont 'open', een
 * staande goedkeuring (automatisch akkoord) wordt herkenbaar benoemd. */
function accorderingRegel(stap: ZoekAccorderingHitDto): string {
  const delen = [stap.besluit ?? 'open', stap.accordeur_naam ?? 'onbekende accordeur', `(laag ${stap.volgnummer})`]
  if (stap.besloten_op) delen.push(formatDatumKort(stap.besloten_op))
  const basis = delen.join(' ')
  return stap.besluit_bron === 'staande_goedkeuring' ? `${basis} · staande goedkeuring` : basis
}

function HistorieCel({ hit }: { hit: ZoekDocumentHitDto }) {
  const heeftHistorie = hit.accordering.length > 0 || hit.vragen.length > 0
  return (
    <td style={{ fontSize: 12, color: 'var(--muted)' }}>
      {hit.accordering.map((stap) => (
        <div key={stap.volgnummer}>{accorderingRegel(stap)}</div>
      ))}
      {hit.vragen.map((vraag, i) => (
        <div key={i}>
          vraag: &ldquo;{kort(vraag.vraag_tekst, VRAAG_MAX_TEKENS)}&rdquo; — {vraag.status}
        </div>
      ))}
      {!heeftHistorie && <>ontvangen {formatDatumKort(hit.aangemaakt_op)}</>}
    </td>
  )
}

export function ZoekenScreen() {
  const navigate = useNavigate()
  const [term, setTerm] = useState('')
  const [resultaat, setResultaat] = useState<ZoekResponseDto | null>(null)
  const [laden, setLaden] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  // Ophogen = het zoek-effect opnieuw laten lopen met dezelfde term ("Opnieuw proberen").
  const [poging, setPoging] = useState(0)

  useEffect(() => {
    const schoon = term.trim()
    if (schoon.length < MIN_TERM_LENGTE) {
      setResultaat(null)
      setLaden(false)
      setFout(null)
      return
    }
    setLaden(true)
    setFout(null)
    let actief = true
    const timer = setTimeout(() => {
      zoek(schoon)
        .then((data) => {
          if (!actief) return
          setResultaat(data)
          setLaden(false)
        })
        .catch((err: unknown) => {
          if (!actief) return
          setFout(err instanceof Error ? err.message : 'Onbekende fout')
          setLaden(false)
        })
    }, DEBOUNCE_MS)
    return () => {
      actief = false
      clearTimeout(timer)
    }
  }, [term, poging])

  const geenResultaten =
    resultaat !== null && !laden && resultaat.documenten.length === 0 && resultaat.audit.length === 0

  return (
    <div>
      <div className="topbar">
        <h1>Zoeken</h1>
      </div>
      <div className="panel">
        <input
          placeholder="Zoek op leverancier, factuurnummer, boekstuknummer, bedrag…"
          aria-label="Globaal zoeken"
          autoFocus
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          style={{ fontSize: 15, padding: '12px 14px', marginBottom: 16 }}
        />

        {fout && (
          <FoutMelding
            melding="Het zoeken is mislukt. Controleer de verbinding en probeer het opnieuw."
            detail={fout}
            onOpnieuw={() => setPoging((p) => p + 1)}
          />
        )}

        {term.trim().length < MIN_TERM_LENGTE && (
          <p className="hint">Typ minimaal {MIN_TERM_LENGTE} tekens om te zoeken.</p>
        )}

        {laden && (
          <table aria-busy="true">
            <tbody>
              {Array.from({ length: 3 }, (_, r) => (
                <tr key={r} aria-hidden="true">
                  {Array.from({ length: 5 }, (_, k) => (
                    <td key={k}>
                      <span className="skeleton" style={{ width: k === 0 ? '70%' : '50%' }} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {geenResultaten && (
          <p className="hint">Geen resultaten voor &ldquo;{resultaat.term || term.trim()}&rdquo;.</p>
        )}

        {resultaat !== null && !laden && !geenResultaten && (
          <>
            <h2>Boekingen ({resultaat.documenten.length})</h2>
            {resultaat.documenten.length === 0 ? (
              <p className="hint">Geen boekingen gevonden.</p>
            ) : (
              <table>
                <tbody>
                  <tr>
                    <th>Document</th>
                    <th>Klant</th>
                    <th className="amount">Bedrag</th>
                    <th>Status</th>
                    <th>Historie</th>
                  </tr>
                  {resultaat.documenten.map((hit) => {
                    const kop = [hit.referentie, hit.leverancier].filter(Boolean).join(' · ') || hit.bestandsnaam
                    return (
                      <tr
                        key={hit.document_id}
                        className="clickable"
                        onClick={() => navigate(reviewPad(hit.soort, hit.administratie_id, hit.document_id))}
                      >
                        <td>
                          {kop}
                          {kop !== hit.bestandsnaam && (
                            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{hit.bestandsnaam}</div>
                          )}
                        </td>
                        <td>{hit.administratie_naam}</td>
                        <td className="amount">{formatBedrag(hit.totaalbedrag)}</td>
                        <td>
                          {hit.status === 'geboekt' && hit.rlz_boekstuknummer ? (
                            <span className="chip geboekt">Geboekt · {hit.rlz_boekstuknummer}</span>
                          ) : (
                            <StatusChip status={hit.status} />
                          )}
                          {hit.automatisch_geboekt && (
                            <>
                              {' '}
                              <span className="chip geheugen">automatisch</span>
                            </>
                          )}
                        </td>
                        <HistorieCel hit={hit} />
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}

            <h2 style={{ marginTop: 18 }}>Audit-gebeurtenissen ({resultaat.audit.length})</h2>
            {resultaat.audit.length === 0 ? (
              <p className="hint">Geen audit-gebeurtenissen gevonden.</p>
            ) : (
              <table>
                <tbody>
                  <tr>
                    <th>Tijdstip</th>
                    <th>Gebruiker</th>
                    <th>Actie</th>
                    <th>Detail</th>
                  </tr>
                  {resultaat.audit.map((hit, i) => (
                    <tr key={i}>
                      <td>{formatDatum(hit.tijdstip)}</td>
                      <td>{hit.actor_naam ?? 'systeem'}</td>
                      <td>{hit.actie}</td>
                      <td style={{ fontSize: 12, color: 'var(--muted)' }}>
                        {hit.administratie_naam} · {detailSamenvatting(hit.detail)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}

        <div className="hint" style={{ marginTop: 14 }}>
          Doorzoekt alles in één keer: boekingen (ook gearchiveerd, mét RLZ-boekstuk), accorderingshistorie (wie
          keurde wanneer, welke laag), vragen &amp; antwoorden en audit-gebeurtenissen.
        </div>
      </div>
    </div>
  )
}
