// Inzicht › Open vragen — KANTOORBREED (design-ronde 03-09 blok B2; mockup inzicht-kantoorbreed.html paneel 2
// + ontwerpnotities ①④⑨ = bouwnorm; principe minimale mens, maximale autonomie — besluit Peter 02-09).
// Eén server-side lijst (`GET /vragen`) over álle administraties in scope, oudste eerst, paginering 25;
// administratie / toegewezen / ouderdom zijn FILTERS op die set (nooit een poort). Vervangt de client-side
// N+1-fan-out (één GET per administratie mét teller > 0) uit de oude werkvoorraad-dwarsdoorsnede. Per rij één
// primaire handeling: "Beantwoorden →" = de bestaande deep-link naar het vragen-deelscherm van de klantpagina
// (`/?administratie=X&sectie=vragen&document=Y`) — daar leeft de thread (bericht plaatsen, afhandelen).
// Kleur-semantiek (designpass v2): teal = actie (de knop), oranje/grijs op de wacht-chip = status.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { OpenVraagRijDto, OpenVragenAdministratieFacetDto, OpenVragenTellersDto } from '../api/types'
import { Badge, Button, Paginering, Select, SkeletonRegels } from '../ui/basis'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { FoutMelding } from '../ui/FoutMelding'
import { formatBedrag } from '../werkvoorraad/format'
import { haalOpenVragenKantoorbreedOp, type OpenVragenToegewezen } from './vragenApi'

export const PER_PAGINA = 25
/** Vanaf hoeveel dagen wachten de chip oranje wordt (mockup: 8 dagen oranje, 2 dagen grijs; server-constante
 * WACHT_ORANJE_VANAF_DAGEN = 7 — hier alleen presentatie). */
export const WACHT_ORANJE_VANAF_DAGEN = 7
const OUDER_DAN_OPTIES = [2, 7, 14] as const

export function wachtLabel(dagen: number): string {
  if (dagen <= 0) return 'vandaag'
  return dagen === 1 ? '1 dag' : `${dagen} dagen`
}

/** Subregel onder de vraag: leverancier · referentie · bedrag · aan <naam> ("aan u" als het de gebruiker zelf is). */
export function subregel(rij: OpenVraagRijDto): string {
  const delen: string[] = []
  if (rij.leverancier_naam) delen.push(rij.leverancier_naam)
  else delen.push(rij.document_bestandsnaam)
  if (rij.referentie) delen.push(rij.referentie)
  if (rij.totaalbedrag !== null) delen.push(formatBedrag(rij.totaalbedrag))
  delen.push(rij.aan_mij ? 'aan u' : `aan ${rij.aan_de_beurt_naam ?? 'onbekend'}`)
  return delen.join(' · ')
}

export function vraagDeeplink(rij: Pick<OpenVraagRijDto, 'administratie_id' | 'document_id'>): string {
  return `/?administratie=${rij.administratie_id}&sectie=vragen&document=${rij.document_id}`
}

export function OpenVragenKantoorbreed({ onStand }: { onStand?: (t: OpenVragenTellersDto) => void }) {
  const navigate = useNavigate()
  const [administratieId, setAdministratieId] = useState<string | null>(null)
  const [toegewezen, setToegewezen] = useState<OpenVragenToegewezen>('alle')
  const [ouderDan, setOuderDan] = useState<number | null>(null)
  const [pagina, setPagina] = useState(1)
  const [rijen, setRijen] = useState<OpenVraagRijDto[] | null>(null)
  const [totaal, setTotaal] = useState(0)
  const [tellers, setTellers] = useState<OpenVragenTellersDto | null>(null)
  const [facet, setFacet] = useState<OpenVragenAdministratieFacetDto[]>([])
  const [fout, setFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)

  useEffect(() => {
    let actueel = true
    setFout(null)
    haalOpenVragenKantoorbreedOp({ pagina, administratieId, toegewezen, ouderDanDagen: ouderDan })
      .then((dto) => {
        if (!actueel) return
        setRijen(dto.rijen ?? [])
        setTotaal(dto.totaal ?? 0)
        setTellers(dto.tellers ?? null)
        setFacet(dto.administraties ?? [])
        if (dto.tellers) onStand?.(dto.tellers)
      })
      .catch((err: unknown) => {
        if (actueel) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
    // onStand bewust niet in de deps (inline callback zou elke render een refetch geven) — kandidaten-patroon.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pagina, administratieId, toegewezen, ouderDan, versie])

  const herlaad = () => setVersie((v) => v + 1)
  const paginas = Math.max(1, Math.ceil(totaal / PER_PAGINA))
  const gefilterd = administratieId !== null || toegewezen !== 'alle' || ouderDan !== null
  const facetOpties = facet.map((f) => ({ id: f.administratie_id, naam: `${f.administratie_naam} (${f.aantal})` }))

  return (
    <div className="panel inst-paneel" data-testid="open-vragen-kantoorbreed" style={{ padding: 0 }}>
      <div
        className="p-kop"
        style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '13px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}
      >
        <h2 style={{ margin: 0, fontSize: 12, letterSpacing: '1.1px', textTransform: 'uppercase', color: 'var(--muted)', fontWeight: 800 }}>
          Inzicht › Open vragen
        </h2>
        {tellers && (
          <>
            <Badge variant={tellers.open > 0 ? 'warn' : 'stil'} data-testid="chip-open">
              {tellers.open} open
            </Badge>
            <Badge variant="stil" data-testid="chip-aan-mij">
              {tellers.aan_mij} aan mij
            </Badge>
            {tellers.blokkeert_boeken > 0 && tellers.blokkeert_boeken !== tellers.open && (
              <span className="hint" style={{ margin: 0 }}>
                {tellers.blokkeert_boeken} blokkeren boeken
              </span>
            )}
          </>
        )}
        <span style={{ marginLeft: 'auto' }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="hint" style={{ margin: 0, whiteSpace: 'nowrap' }}>
            Administratie:
          </span>
          <div style={{ minWidth: 220 }}>
            <AdministratieCombobox
              label="Administratie (filter)"
              toonLabel={false}
              administraties={facetOpties}
              waarde={administratieId}
              placeholder={administratieId ? undefined : 'alle'}
              onWijzig={(id) => {
                setAdministratieId(id)
                setPagina(1)
              }}
            />
          </div>
          {administratieId && (
            <button
              type="button"
              className="linkbtn"
              onClick={() => {
                setAdministratieId(null)
                setPagina(1)
              }}
            >
              alle
            </button>
          )}
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, fontSize: 12 }}>
          <span className="hint" style={{ margin: 0 }}>
            Toegewezen:
          </span>
          <Select
            aria-label="Toegewezen"
            value={toegewezen}
            onChange={(e) => {
              setToegewezen(e.target.value as OpenVragenToegewezen)
              setPagina(1)
            }}
          >
            <option value="alle">alle</option>
            <option value="mij">aan mij</option>
          </Select>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0, fontSize: 12 }}>
          <span className="hint" style={{ margin: 0 }}>
            Ouder dan:
          </span>
          <Select
            aria-label="Ouder dan"
            value={ouderDan === null ? 'alles' : String(ouderDan)}
            onChange={(e) => {
              setOuderDan(e.target.value === 'alles' ? null : Number(e.target.value))
              setPagina(1)
            }}
          >
            <option value="alles">alles</option>
            {OUDER_DAN_OPTIES.map((d) => (
              <option key={d} value={String(d)}>
                {d} dagen
              </option>
            ))}
          </Select>
        </label>
      </div>

      {fout && <FoutMelding melding="De open vragen konden niet geladen worden." detail={fout} onOpnieuw={herlaad} />}
      {rijen === null && !fout && <SkeletonRegels />}
      {rijen !== null && rijen.length === 0 && (
        <p className="hint" style={{ padding: '14px 18px' }} data-testid="lege-stand">
          {gefilterd ? (
            <>
              Geen open vragen binnen dit filter.{' '}
              <button
                type="button"
                className="linkbtn"
                onClick={() => {
                  setAdministratieId(null)
                  setToegewezen('alle')
                  setOuderDan(null)
                  setPagina(1)
                }}
              >
                Filters wissen
              </button>
            </>
          ) : (
            'Geen open vragen — nergens. Alles is beantwoord.'
          )}
        </p>
      )}
      {rijen !== null && rijen.length > 0 && (
        <div className="tabel-scroll">
          <table>
            <thead>
              <tr>
                <th style={{ width: '38%' }}>Vraag</th>
                <th>Administratie</th>
                <th>Wacht sinds</th>
                <th style={{ width: 190 }} />
              </tr>
            </thead>
            <tbody>
              {rijen.map((rij) => (
                <tr key={rij.vraag_id} data-testid="open-vraag-rij">
                  <td>
                    <div style={{ fontWeight: 700 }}>&ldquo;{rij.vraag_tekst}&rdquo;</div>
                    <div className="hint" style={{ margin: '2px 0 0', fontSize: 11.5 }}>
                      {subregel(rij)}
                    </div>
                    {rij.laatste_bericht && (
                      <div className="hint" style={{ margin: '2px 0 0', fontSize: 11.5 }}>
                        laatste bericht{rij.laatste_bericht_door ? ` van ${rij.laatste_bericht_door}` : ''}: &ldquo;{rij.laatste_bericht}&rdquo;
                      </div>
                    )}
                  </td>
                  <td>{rij.administratie_naam}</td>
                  <td>
                    <Badge variant={rij.wacht_dagen >= WACHT_ORANJE_VANAF_DAGEN ? 'warn' : 'stil'}>{wachtLabel(rij.wacht_dagen)}</Badge>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    <Button maat="klein" aria-label={`Beantwoorden: ${rij.vraag_tekst}`} onClick={() => navigate(vraagDeeplink(rij))}>
                      Beantwoorden →
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div
        className="voet"
        style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 18px', fontSize: 12, color: 'var(--faint)', flexWrap: 'wrap' }}
      >
        <span>
          ‹ {pagina} van {paginas} › · oudste eerst
          {tellers ? ` · ${tellers.open} open over ${tellers.administraties} administratie${tellers.administraties === 1 ? '' : 's'}` : ''}
        </span>
        <span style={{ marginLeft: 'auto' }} />
        <Paginering pagina={pagina} totaal={totaal} grootte={PER_PAGINA} onPagina={setPagina} label="vragen" />
      </div>
    </div>
  )
}
