import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, apiFetch, apiJson, apiPostJson } from '../api/client'
import type { AfwijzingDto, DocumentActieResponseDto, DocumentDetailDto, HerkomstMailDto, VraagDto } from '../api/types'
import { BevestigDialog } from '../instellingen/BevestigDialog'
import { StatusChip } from '../werkvoorraad/StatusChip'
import { extractieActief, statusLabel } from '../werkvoorraad/status'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { haalVragenOp } from '../vragen/vragenApi'
import { VraagModal } from '../vragen/VraagModal'
import { VraagThread } from '../vragen/VraagThread'
import { DoorbelastenNaBoeken, type KlaargezetteDoorbelasting } from '../doorbelasting/DoorbelastenNaBoeken'
import { DoorbelastenSectie } from '../doorbelasting/DoorbelastenSectie'
import { TegenboekSectie } from './TegenboekSectie'
import { AfwijsModal } from './AfwijsModal'
import { AlBetaaldSignaal } from './AlBetaaldSignaal'
import { alsAiVoorstel, zekerheidPct, type AiVoorstel } from './aiVoorstel'
import { AccorderingSectie } from './AccorderingSectie'
import { BoekvoorstelPanel } from './BoekvoorstelPanel'
import { MatchSectie } from './MatchSectie'
import { IbanAccorderingSectie } from './IbanAccorderingSectie'
import { SOORT_LABELS } from './ibanAccorderingApi'
import { ReviewSplitter, ReviewVergrootKnop, useReviewSplitter } from '../ui/ReviewSplitter'

/** Statussen waaruit een vraag gesteld kan worden (spiegel van de backend-poort
 * _HERSTELBARE_HERKOMSTEN in app/documenten/vragen.py — de backend blijft de waarheid). */
const VRAAG_STELLEN_STATUSSEN = new Set(['te_controleren', 'handmatig_afmaken', 'klaar_om_te_boeken'])

/** Statussen waaruit afgewezen kan worden (spiegel van app/documenten/afwijzen.py —
 * zelfde herstelbare herkomsten als bij vragen; de backend blijft de waarheid). */
const AFWIJZEN_STATUSSEN = VRAAG_STELLEN_STATUSSEN

/** Ververs-interval zolang de achtergrondextractie loopt (wachtrij/bezig). */
const EXTRACTIE_POLL_MS = 3000

function formatDatum(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { dateStyle: 'medium', timeStyle: 'short' })
}

function formatDatumKort(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { dateStyle: 'medium' })
}

function veldnaam(sleutel: string): string {
  const namen: Record<string, string> = {
    factuurnummer: 'Factuurnummer',
    factuurdatum: 'Factuurdatum',
    vervaldatum: 'Vervaldatum',
    valuta: 'Valuta',
    totaal_excl: 'Totaal excl. btw',
    totaal_incl: 'Totaal incl. btw',
    btw_bedrag: 'Btw-bedrag',
    leverancier_naam: 'Leverancier',
    regelaantal: 'Aantal regels',
  }
  return namen[sleutel] ?? sleutel
}

/** Vertaalslag voor de tijdlijn: waarom de AI-extractie een PDF niet heeft verwerkt. */
function aiOvergeslagenLabel(reden: string): string {
  const labels: Record<string, string> = {
    ai_extractie_uitgeschakeld: 'AI-extractie staat uit voor deze administratie (AVG-gate)',
    geen_api_key: 'geen Claude-API-key geconfigureerd',
    geen_administratie: 'document is niet aan een administratie toegewezen',
    ai_limiet_bereikt: 'AI-maandlimiet bereikt — handmatig verwerken',
  }
  return labels[reden] ?? reden
}

const AI_KOPVELDEN = [
  'leverancier_naam',
  'factuurnummer',
  'factuurdatum',
  'vervaldatum',
  'totaal_excl',
  'totaal_incl',
  'btw_bedrag',
  'valuta',
] as const

interface AiVoorstelPanelProps {
  voorstel: AiVoorstel
  /** UX-fix 2026-07-11: "opnieuw extraheren" ook op een gesláágd voorstel (alleen PDF's in
   * te_controleren — de aanroeper bepaalt dat en geeft anders undefined; de klik opent eerst
   * een bevestigingsvraag omdat de her-run het huidige voorstel overschrijft). */
  onOpnieuwExtraheren?: () => void
}

/** Weergave van het AI-veldvoorstel: per veld de gelezen waarde + zekerheidsscore (oranje onder
 * de drempel — "bij twijfel nooit gokken", de controleur kijkt daar extra naar), plus de
 * signalen van de deterministische controlelaag (regelsom, onparseerbare velden, BSN-filter). */
function AiVoorstelPanel({ voorstel, onOpnieuwExtraheren }: AiVoorstelPanelProps) {
  const controle = voorstel.controle
  return (
    <div className="panel">
      <h2>
        Veldvoorstel (AI) <span className="chip ai">AI-voorstel — mens boekt</span>
      </h2>
      <table className="lines">
        <tbody>
          {AI_KOPVELDEN.map((sleutel) => {
            const waarde = voorstel[sleutel]
            const score = voorstel.zekerheid[sleutel]
            const laag = score !== undefined && score < voorstel.zekerheid_drempel
            return (
              <tr key={sleutel}>
                <td style={{ color: 'var(--muted)', whiteSpace: 'nowrap' }}>{veldnaam(sleutel)}</td>
                <td style={{ fontVariantNumeric: 'tabular-nums' }}>{waarde ?? '—'}</td>
                <td style={{ textAlign: 'right' }}>
                  {waarde !== null && score !== undefined && (
                    <span className={`chip ${laag ? 'afwijking' : 'ok'}`}>{zekerheidPct(score)}</span>
                  )}
                </td>
              </tr>
            )
          })}
          <tr>
            <td style={{ color: 'var(--muted)' }}>{veldnaam('regelaantal')}</td>
            <td>{voorstel.regelaantal}</td>
            <td style={{ textAlign: 'right' }}>
              {controle.regelsom !== null && controle.regelsom_wijkt_af !== null && (
                <span className={`chip ${controle.regelsom_wijkt_af ? 'afwijking' : 'ok'}`}>
                  {controle.regelsom_wijkt_af ? `som € ${controle.regelsom} wijkt af` : 'regelsom sluit aan'}
                </span>
              )}
            </td>
          </tr>
        </tbody>
      </table>
      {controle.onvolledig && (
        <div className="hint" style={{ color: 'var(--orange)' }}>
          De regelset is mogelijk incompleet (extractie kon niet aantoonbaar alle regels ophalen) — controleer
          de regels tegen de bijlage; de regelsom-check hierboven is daarbij het vangnet.
        </div>
      )}
      {controle.bsn_verwijderd > 0 && (
        <div className="hint" style={{ color: 'var(--orange)' }}>
          AVG-filter: {controle.bsn_verwijderd} BSN-patroon
          {controle.bsn_verwijderd === 1 ? '' : 'en'} uit de AI-output verwijderd — er is niets van
          gepersisteerd.
        </div>
      )}
      {controle.onparseerbaar.length > 0 && (
        <div className="hint" style={{ color: 'var(--orange)' }}>
          Gelezen maar niet overgenomen (geen valide waarde): {controle.onparseerbaar.join(', ')} — handmatig
          invullen.
        </div>
      )}
      <div className="hint">
        De AI leest alleen voor; bedragen, datums en suggesties zijn door de controlelaag geparst en getoetst.
        Grootboek en btw-code komen uitsluitend uit de sync-cache — boeken blijft een menselijke actie.
      </div>
      {onOpnieuwExtraheren && (
        <div className="actions">
          <button type="button" className="btn secondary" onClick={onOpnieuwExtraheren}>
            ↻ Opnieuw extraheren
          </button>
        </div>
      )}
    </div>
  )
}

/** Puur cosmetisch: legt de XML in nette, ingesprongen regels voor de bron-weergave (geen
 * DOM-parsing/uitvoering — React rendert dit altijd als platte tekst in een <pre>, dus geen
 * XSS-risico). Werkt op basis van eenvoudige tag-grenzen; bedoeld voor leesbaarheid, geen
 * volwaardige XML-formatter. Geëxporteerd voor hergebruik in het verkoopreview-scherm
 * (UBL-bron in het linkerpaneel). */
export function formatteerXml(xml: string): string {
  const zonderWhitespaceTussenTags = xml.replace(/>\s*</g, '><').trim()
  const tokens = zonderWhitespaceTussenTags.split(/(?=<)/g).filter(Boolean)
  let diepte = 0
  const regels: string[] = []
  for (const token of tokens) {
    const isSluitend = token.startsWith('</')
    const isZelfsluitendOfDeclaratie = /\/>\s*$/.test(token) || token.startsWith('<?')
    if (isSluitend) diepte = Math.max(0, diepte - 1)
    regels.push('  '.repeat(diepte) + token)
    if (!isSluitend && !isZelfsluitendOfDeclaratie) diepte += 1
  }
  return regels.join('\n')
}

interface Bijlage {
  url: string
  contentType: string
  xmlTekst: string | null
}

/** Laatste extractie-uitkomst: de foutmelding (ai_extractie_fout) of onvolledig-melding
 * (ai_extractie_onvolledig, waarborg projectadministratie) van de meest recente overgang naar
 * te_controleren of handmatig_afmaken — null als de laatste extractie een voorstel opleverde. */
function laatsteExtractieProbleem(detail: DocumentDetailDto): string | null {
  for (let i = detail.tijdlijn.length - 1; i >= 0; i--) {
    const g = detail.tijdlijn[i]
    if (g.naar_status === 'te_controleren' || g.naar_status === 'handmatig_afmaken') {
      if (g.detail && 'ai_extractie_fout' in g.detail) return String(g.detail.ai_extractie_fout)
      if (g.detail && 'ai_extractie_onvolledig' in g.detail) return String(g.detail.ai_extractie_onvolledig)
      return null
    }
  }
  return null
}

/** Inklapbaar blok "Uit de e-mail" (feedbackronde 25-08 deel 3 punt 1b): afzender, onderwerp en
 * de platte mail-body van het intake-bericht — context voor het boekingsvoorstel (casus: collega
 * mailt "dit is voor Oirschot"). Standaard ingeklapt; géén body (bericht van vóór 0069 of mail
 * zonder tekst) = dat staat er eerlijk bij. */
function UitDeEmail({ herkomst }: { herkomst: HerkomstMailDto }) {
  const ontvangen = herkomst.ontvangen_op ? new Date(herkomst.ontvangen_op).toLocaleString('nl-NL') : null
  return (
    <details className="panel uit-de-email" data-testid="uit-de-email">
      <summary style={{ cursor: 'pointer' }}>
        <h2 style={{ display: 'inline', margin: 0 }}>Uit de e-mail</h2>
        <span className="hint" style={{ marginLeft: 8 }}>
          {herkomst.afzender ?? 'onbekende afzender'}
          {herkomst.onderwerp ? ` · ${herkomst.onderwerp}` : ''}
        </span>
      </summary>
      <dl className="grid2" style={{ marginTop: 10 }}>
        <div>
          <dt className="hint">Afzender</dt>
          <dd>{herkomst.afzender ?? '—'}</dd>
        </div>
        <div>
          <dt className="hint">Onderwerp</dt>
          <dd>{herkomst.onderwerp ?? '—'}</dd>
        </div>
        <div>
          <dt className="hint">Ontvangen</dt>
          <dd>
            {ontvangen ?? '—'} <span className="hint">({herkomst.bron === 'imap' ? 'postvak' : '.eml-upload'})</span>
          </dd>
        </div>
      </dl>
      <div className="hint" style={{ marginTop: 8 }}>
        Begeleidend schrijven
      </div>
      {herkomst.body_tekst ? (
        <pre className="mail-body">{herkomst.body_tekst}</pre>
      ) : (
        <p className="hint" style={{ margin: 0 }}>
          Geen mailtekst beschikbaar (mail zonder tekst, of verwerkt vóór de mail-body bewaard werd).
        </p>
      )}
    </details>
  )
}

export function DocumentDetailScreen() {
  const { administratieId, documentId } = useParams<{ administratieId: string; documentId: string }>()
  const [detail, setDetail] = useState<DocumentDetailDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [bijlage, setBijlage] = useState<Bijlage | null>(null)
  const [opnieuwBezig, setOpnieuwBezig] = useState(false)
  const [opnieuwFout, setOpnieuwFout] = useState<string | null>(null)
  // UX-fix 2026-07-11: her-extractie vanaf een gesláágd voorstel vraagt eerst bevestiging —
  // de her-run overschrijft het huidige voorstel (nieuwste extractie wint).
  const [herExtractieBevestigen, setHerExtractieBevestigen] = useState(false)
  const [vraagModalOpen, setVraagModalOpen] = useState(false)
  // Alle vragen van dit document (dialoog-threads, besluit Peter 25-08): voeden de open-vraag-
  // banner én het tabblad "Opmerkingen" naast de tijdlijn.
  const [documentVragen, setDocumentVragen] = useState<VraagDto[] | null>(null)
  const [tijdlijnTab, setTijdlijnTab] = useState<'tijdlijn' | 'opmerkingen'>('tijdlijn')
  const downloadOrigineel = async () => {
    if (!detail?.bron_bestandsnaam) return
    const resp = await apiFetch(`/administraties/${administratieId}/documenten/${documentId}/bronbestand`)
    if (!resp.ok) return
    const url = URL.createObjectURL(await resp.blob())
    const a = document.createElement('a')
    a.href = url
    a.download = detail.bron_bestandsnaam
    a.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
  const opmerkingenRef = useRef<HTMLDivElement | null>(null)
  // Doorbelasten in de boekflow (besluit Peter 25-08): het blok meldt of er een klaargezette run
  // is en of die groen staat — de boekknop wordt dan "Boeken + doorbelasten" (poort in het paneel).
  const [doorbelastingKlaargezet, setDoorbelastingKlaargezet] = useState<KlaargezetteDoorbelasting | null>(null)
  const [boekvoorstelVersie, setBoekvoorstelVersie] = useState(0)
  const onVoorstelOpgeslagen = useCallback(() => setBoekvoorstelVersie((v) => v + 1), [])
  const [afwijsModalOpen, setAfwijsModalOpen] = useState(false)
  const [heropenenBezig, setHeropenenBezig] = useState(false)
  const [heropenenFout, setHeropenenFout] = useState<string | null>(null)
  const splitter = useReviewSplitter()
  const { naamVoor } = useMedewerkers(administratieId ?? null)

  const laadDetail = useCallback(() => {
    if (!administratieId || !documentId) return
    setFout(null)
    apiJson<DocumentDetailDto>(`/administraties/${administratieId}/documenten/${documentId}`)
      .then(setDetail)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratieId, documentId])

  useEffect(() => {
    setDetail(null)
    laadDetail()
  }, [laadDetail])

  // Live extractiestatus (async extractie): in wachtrij → bezig → klaar loopt vanzelf mee —
  // geen blokkerende spinner, de gebruiker kan intussen de bijlage en tijdlijn gewoon bekijken.
  useEffect(() => {
    if (!detail || !extractieActief(detail.status)) return
    const timer = setInterval(laadDetail, EXTRACTIE_POLL_MS)
    return () => clearInterval(timer)
  }, [detail, laadDetail])

  // Vragen van dit document (dialoog): herladen bij elke detail-verversing zodat een nieuw
  // bericht of afhandeling direct zichtbaar is in banner en Opmerkingen-tab.
  const laadVragen = useCallback(() => {
    if (!administratieId || !documentId) return
    haalVragenOp(administratieId, { documentId })
      .then((data) => setDocumentVragen(data.vragen))
      .catch(() => {
        // Banner degradeert naar alleen de statuschip — de vraag zelf blijft via de
        // vragen-view bereikbaar.
        setDocumentVragen(null)
      })
  }, [administratieId, documentId])

  useEffect(() => {
    setDocumentVragen(null)
    laadVragen()
  }, [laadVragen, detail?.status])

  const openVraag = useMemo(() => documentVragen?.find((v) => v.status === 'open') ?? null, [documentVragen])
  const vragenChronologisch = useMemo(
    () => (documentVragen ? [...documentVragen].sort((a, b) => a.gesteld_op.localeCompare(b.gesteld_op)) : null),
    [documentVragen],
  )
  const toonOpmerkingen = () => {
    setTijdlijnTab('opmerkingen')
    opmerkingenRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  useEffect(() => {
    if (!administratieId || !documentId) return
    let objectUrl: string | null = null
    let actief = true

    void apiFetch(`/administraties/${administratieId}/documenten/${documentId}/bestand`).then(async (resp) => {
      if (!resp.ok || !actief) return
      const blob = await resp.blob()
      const contentType = resp.headers.get('content-type') ?? 'application/octet-stream'
      objectUrl = URL.createObjectURL(blob)
      const xmlTekst = contentType.includes('xml') ? formatteerXml(await blob.text()) : null
      if (actief) setBijlage({ url: objectUrl, contentType, xmlTekst })
    })

    return () => {
      actief = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [administratieId, documentId])

  if (fout) return <div className="fout">Kon document niet laden: {fout}</div>
  if (!administratieId || !documentId || !detail) return <p className="hint">Laden…</p>

  const extractieProbleem = laatsteExtractieProbleem(detail)
  const isHandmatigAfmaken = detail.status === 'handmatig_afmaken'
  const achtergrondBezig = extractieActief(detail.status)

  const opnieuwExtraheren = async () => {
    setOpnieuwBezig(true)
    setOpnieuwFout(null)
    try {
      await apiPostJson<DocumentActieResponseDto>(
        `/administraties/${administratieId}/documenten/${documentId}/extractie`,
        {},
      )
      setHerExtractieBevestigen(false)
      laadDetail()
    } catch (err) {
      setOpnieuwFout(err instanceof ApiError ? err.message : 'Opnieuw extraheren mislukt.')
    } finally {
      setOpnieuwBezig(false)
    }
  }

  // Alleen PDF's: UBL wordt deterministisch geparst, daar valt niets opnieuw te "lezen". De
  // backend bewaakt dit ook (alleen PDF, alleen vanaf te_controleren) — dit is de UI-kant.
  const isPdf = detail.bestandsnaam.toLowerCase().endsWith('.pdf')
  const magOpnieuwExtraheren = isPdf && detail.status === 'te_controleren' && !extractieProbleem

  const heropenen = async () => {
    setHeropenenBezig(true)
    setHeropenenFout(null)
    try {
      await apiPostJson<AfwijzingDto>(
        `/administraties/${administratieId}/documenten/${documentId}/heropenen`,
        {},
      )
      laadDetail()
    } catch (err) {
      setHeropenenFout(err instanceof ApiError ? err.message : 'Heropenen mislukt.')
    } finally {
      setHeropenenBezig(false)
    }
  }

  return (
    <div>
      <div className="topbar">
        <h1>
          <Link to={`/?administratie=${administratieId}`}>← Werkvoorraad</Link>{' '}
          <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span>{' '}
          {detail.bestandsnaam}
        </h1>
        <div className="adm-select">
          <StatusChip status={detail.status} />
        </div>
      </div>

      <div className="review" ref={splitter.containerRef} style={splitter.stijl}>
        <div className="docpane">
          <div className="panel">
            <div
              style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}
            >
              <h2 style={{ margin: 0 }}>Bijlage</h2>
              <ReviewVergrootKnop splitter={splitter} />
            </div>
            <div className="bijlage-inhoud">
              {!bijlage && <p className="hint">Bijlage laden…</p>}
              {bijlage?.contentType.includes('pdf') && (
                <object data={bijlage.url} type="application/pdf">
                  <p className="hint">
                    Geen inline PDF-weergave in deze browser —{' '}
                    <a href={bijlage.url} download={detail.bestandsnaam}>
                      open het bestand direct
                    </a>
                    .
                  </p>
                </object>
              )}
              {bijlage?.xmlTekst !== null && bijlage?.xmlTekst !== undefined && (
                <pre className="xml-bron">{bijlage.xmlTekst}</pre>
              )}
              {bijlage && !bijlage.contentType.includes('pdf') && bijlage.xmlTekst === null && (
                <p className="hint">Geen inline weergave voor dit bestandstype.</p>
              )}
            </div>
            {bijlage && (
              <p style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                <a className="btn secondary" href={bijlage.url} download={detail.bestandsnaam}>
                  Downloaden
                </a>
                {detail.bron_bestandsnaam && (
                  // Omgezette afbeelding (punt 2, 25-08 deel 3): het aangeleverde origineel blijft
                  // als brondocument bewaard en is hier op te halen.
                  <button
                    type="button"
                    className="btn ghost"
                    title="Deze PDF is gemaakt uit een aangeleverde afbeelding; het origineel blijft bewaard"
                    onClick={() => void downloadOrigineel()}
                  >
                    Origineel ({detail.bron_bestandsnaam})
                  </button>
                )}
              </p>
            )}
          </div>
        </div>

        <ReviewSplitter splitter={splitter} />

        <div className="formpane">
          {detail.status === 'wacht_op_iban_accordering' && (
            <IbanAccorderingSectie
              administratieId={administratieId}
              documentId={documentId}
              onGewijzigd={laadDetail}
            />
          )}

          <AccorderingSectie
            administratieId={administratieId}
            documentId={documentId}
            documentStatus={detail.status}
            onGewijzigd={laadDetail}
          />


          {/* Factuurmatch fase 3: volledige match-sectie (chip per uitkomst, per-week-
              uitsplitsing, periode-keuze/herberekenen, concept-mail bij afwijking) — een
              signaal bovenop de normale flow (besluit 3, geen status); de boeken-ondanks-
              afwijking-bevestiging blijft de pop-up in het boekvoorstel. */}
          {detail.factuurmatch && !['geboekt', 'verwijderd', 'gesplitst'].includes(detail.status) && (
            <MatchSectie
              administratieId={administratieId}
              documentId={documentId}
              match={detail.factuurmatch}
              onGewijzigd={laadDetail}
            />
          )}

          {detail.status === 'afgewezen' && (
            <div className="panel">
              <h2>
                Afgewezen — ter controle <span className="chip vraag">boeken geblokkeerd</span>
              </h2>
              {detail.afwijzing ? (
                <div className="q-item" style={{ marginBottom: 0, border: 'none', padding: 0 }}>
                  <div className="meta">
                    afgewezen door {naamVoor(detail.afwijzing.afgewezen_door)},{' '}
                    {formatDatum(detail.afwijzing.afgewezen_op)} · ter controle naar{' '}
                    <b>{naamVoor(detail.afwijzing.toegewezen_aan)}</b>
                  </div>
                  <div className="vraagtekst">reden: &ldquo;{detail.afwijzing.reden}&rdquo;</div>
                </div>
              ) : (
                <p className="hint" style={{ marginTop: 0 }}>
                  Dit document is afgewezen. Het blijft zichtbaar in de werkvoorraad; boeken kan pas na
                  heropenen.
                </p>
              )}
              {heropenenFout && <div className="fout">{heropenenFout}</div>}
              {detail.afwijzing && (
                <div className="actions">
                  <button
                    type="button"
                    className="btn"
                    disabled={heropenenBezig}
                    onClick={() => void heropenen()}
                  >
                    {heropenenBezig ? 'Bezig…' : '↺ Heropenen'}
                  </button>
                </div>
              )}
            </div>
          )}

          {detail.status === 'vraag_open' && (
            <div className="panel">
              <h2>
                Open vraag <span className="chip vraag">boeken geblokkeerd</span>
              </h2>
              {openVraag ? (
                <>
                  <div className="q-item" style={{ marginBottom: 0, border: 'none', padding: 0 }}>
                    <div className="meta">
                      gesteld door {naamVoor(openVraag.gesteld_door)}, {formatDatum(openVraag.gesteld_op)} · aan{' '}
                      <b>{naamVoor(openVraag.toegewezen_aan)}</b> · aan de beurt: <b>{naamVoor(openVraag.aan_de_beurt)}</b>
                      {openVraag.berichten.length > 0 && (
                        <> · {openVraag.berichten.length} {openVraag.berichten.length === 1 ? 'reactie' : 'reacties'}</>
                      )}
                    </div>
                    <div className="vraagtekst">&ldquo;{openVraag.vraag_tekst}&rdquo;</div>
                  </div>
                  <div className="actions">
                    <button type="button" className="btn" onClick={toonOpmerkingen}>
                      Reageren of afhandelen ↓
                    </button>
                    <Link
                      className="btn secondary"
                      to={`/?administratie=${administratieId}&sectie=vragen&document=${documentId}`}
                    >
                      Open in vragenlijst →
                    </Link>
                  </div>
                </>
              ) : (
                <p className="hint" style={{ marginTop: 0 }}>
                  Er staat een open vraag op dit document —{' '}
                  <Link to={`/?administratie=${administratieId}&sectie=vragen&document=${documentId}`}>
                    bekijk de vraag
                  </Link>
                  . Boeken kan pas nadat de vraagsteller de vraag als afgehandeld markeert (of na intrekking).
                </p>
              )}
            </div>
          )}

          {achtergrondBezig && (
            <div className="panel">
              <h2>
                Wordt op de achtergrond verwerkt{' '}
                <span className="chip ai">
                  {detail.status === 'extractie_wachtrij' ? 'in wachtrij' : 'extractie bezig'}
                </span>
              </h2>
              <p className="hint" style={{ marginTop: 0 }}>
                {detail.status === 'extractie_wachtrij'
                  ? 'Dit document staat in de wachtrij voor AI-extractie (groot document). Dit scherm ververst vanzelf zodra de verwerking start.'
                  : 'De AI-extractie draait op de achtergrond. Dit scherm ververst vanzelf zodra het voorstel klaar is.'}
              </p>
            </div>
          )}

          {extractieProbleem && (detail.status === 'te_controleren' || isHandmatigAfmaken) && (
            <div className="panel">
              <h2>
                {isHandmatigAfmaken ? 'Handmatig afmaken' : 'AI-extractie mislukt'}{' '}
                <span className={`chip ${isHandmatigAfmaken ? 'blokkerend' : 'afwijking'}`}>
                  {isHandmatigAfmaken ? 'regelset onvolledig — geen voorstel' : 'handmatig of opnieuw'}
                </span>
              </h2>
              <p className="hint" style={{ marginTop: 0 }}>
                {extractieProbleem}
              </p>
              {opnieuwFout && <div className="fout">{opnieuwFout}</div>}
              <div className="actions">
                <button
                  type="button"
                  className="btn secondary"
                  disabled={opnieuwBezig}
                  onClick={() => void opnieuwExtraheren()}
                >
                  {opnieuwBezig ? 'Bezig met extraheren…' : '↻ Opnieuw extraheren'}
                </button>
              </div>
            </div>
          )}

          {(() => {
            // Zolang de achtergrondextractie loopt is een (ouder) voorstel of het
            // boekvoorstel-formulier misleidend — de worker schrijft zo een nieuw voorstel.
            if (achtergrondBezig) return null
            const aiVoorstel = alsAiVoorstel(detail.veldvoorstel)
            if (aiVoorstel) {
              return (
                <AiVoorstelPanel
                  voorstel={aiVoorstel}
                  onOpnieuwExtraheren={
                    magOpnieuwExtraheren
                      ? () => {
                          setOpnieuwFout(null)
                          setHerExtractieBevestigen(true)
                        }
                      : undefined
                  }
                />
              )
            }
            if (!detail.veldvoorstel) return null
            return (
              <div className="panel">
                <h2>
                  Veldvoorstel (UBL) <span className="chip geheugen">deterministisch geparst</span>
                </h2>
                <table className="lines">
                  <tbody>
                    {Object.entries(detail.veldvoorstel).map(([sleutel, waarde]) => (
                      <tr key={sleutel}>
                        <td style={{ color: 'var(--muted)' }}>{veldnaam(sleutel)}</td>
                        <td>{waarde === null || waarde === undefined ? '—' : String(waarde)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          })()}

          {/* Uit de e-mail (feedbackronde 25-08 deel 3 punt 1b): context bij het voorstel. */}
          {detail.herkomst_mail && <UitDeEmail herkomst={detail.herkomst_mail} />}

          {/* Al-betaald-signaal (besluit Peter 25-08, deel 2 punt 1): alleen hier op het
              controlescherm, nooit blokkerend — de component gate zichzelf (soort/status). */}
          {!achtergrondBezig && (
            <AlBetaaldSignaal
              administratieId={administratieId}
              documentId={documentId}
              status={detail.status}
              soort={detail.soort}
              boekvoorstelVersie={boekvoorstelVersie}
            />
          )}

          {!achtergrondBezig && (
            <BoekvoorstelPanel
              administratieId={administratieId}
              documentId={documentId}
              status={detail.status}
              veldvoorstel={detail.veldvoorstel}
              onGeboekt={laadDetail}
              onHersteld={laadDetail}
              onVraagStellen={
                VRAAG_STELLEN_STATUSSEN.has(detail.status) ? () => setVraagModalOpen(true) : undefined
              }
              onAfwijzen={AFWIJZEN_STATUSSEN.has(detail.status) ? () => setAfwijsModalOpen(true) : undefined}
              onIbanAangeboden={VRAAG_STELLEN_STATUSSEN.has(detail.status) ? laadDetail : undefined}
              doorbelastingKlaargezet={doorbelastingKlaargezet}
              onVoorstelOpgeslagen={onVoorstelOpgeslagen}
            />
          )}

          {/* Doorbelasten ná boeken (besluit Peter 25-08, herziet 13-08): optioneel blok op een NOG
              NIET geboekt document — de sectie gate zichzelf (soort + status + toggle). */}
          <DoorbelastenNaBoeken
            administratieId={administratieId}
            documentId={documentId}
            status={detail.status}
            soort={detail.soort}
            boekvoorstelVersie={boekvoorstelVersie}
            onKlaargezet={setDoorbelastingKlaargezet}
          />

          {/* Tegenboek-pad (mockup 22-08): actie op een GEBOEKTE inkoopfactuur waarvan storno
              door de aangifte-poort geblokkeerd is — de sectie gate zichzelf. */}
          <TegenboekSectie
            administratieId={administratieId}
            documentId={documentId}
            status={detail.status}
            soort={detail.soort}
            onGewijzigd={laadDetail}
          />

          {/* Kempen-doorbelasting (blok 3): actie op een GEBOEKTE inkoopfactuur — de sectie
              gate zichzelf (status + soort + toggle per administratie, faalvriendelijk). */}
          <DoorbelastenSectie
            administratieId={administratieId}
            documentId={documentId}
            status={detail.status}
            soort={detail.soort}
          />

          {vraagModalOpen && (
            <VraagModal
              administratieId={administratieId}
              documentId={documentId}
              onGesteld={() => {
                setVraagModalOpen(false)
                laadDetail()
              }}
              onAnnuleren={() => setVraagModalOpen(false)}
            />
          )}

          {afwijsModalOpen && (
            <AfwijsModal
              administratieId={administratieId}
              documentId={documentId}
              onAfgewezen={() => {
                setAfwijsModalOpen(false)
                laadDetail()
              }}
              onAnnuleren={() => setAfwijsModalOpen(false)}
            />
          )}

          {herExtractieBevestigen && (
            <BevestigDialog
              titel="Opnieuw extraheren?"
              bericht={
                'De AI leest de PDF opnieuw en het nieuwe resultaat overschrijft het huidige ' +
                'veldvoorstel (nieuwste extractie wint, ook in de boekvoorstel-prefill). Een al ' +
                'opgeslagen boekvoorstel blijft bewaard.'
              }
              bezig={opnieuwBezig}
              fout={opnieuwFout}
              onBevestigen={() => void opnieuwExtraheren()}
              onAnnuleren={() => {
                if (!opnieuwBezig) setHerExtractieBevestigen(false)
              }}
            />
          )}

          <div className="panel" ref={opmerkingenRef}>
            {/* Twee tabs (besluit Peter 25-08, punt B3): Tijdlijn = statusgebeurtenissen,
                Opmerkingen = de vraag/antwoord-dialogen van dit document, nieuwste onderaan. */}
            <div className="segment" role="tablist" aria-label="Tijdlijn of opmerkingen" style={{ marginBottom: 10 }}>
              <button
                type="button"
                role="tab"
                aria-selected={tijdlijnTab === 'tijdlijn'}
                className={tijdlijnTab === 'tijdlijn' ? 'actief' : undefined}
                onClick={() => setTijdlijnTab('tijdlijn')}
              >
                Tijdlijn
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tijdlijnTab === 'opmerkingen'}
                className={tijdlijnTab === 'opmerkingen' ? 'actief' : undefined}
                onClick={() => setTijdlijnTab('opmerkingen')}
              >
                Opmerkingen{documentVragen && documentVragen.length > 0 ? ` (${documentVragen.length})` : ''}
                {openVraag && (
                  <span className="chip vraag" style={{ marginLeft: 6 }}>
                    open
                  </span>
                )}
              </button>
            </div>
            {tijdlijnTab === 'opmerkingen' && (
              <div role="tabpanel" aria-label="Opmerkingen">
                {vragenChronologisch === null && <p className="hint">Opmerkingen laden…</p>}
                {vragenChronologisch !== null && vragenChronologisch.length === 0 && (
                  <p className="hint" style={{ marginTop: 0 }}>
                    Nog geen vragen of opmerkingen bij dit document. Stel een vraag via &ldquo;Vraag stellen…&rdquo; in
                    het boekvoorstel — de dialoog verschijnt hier.
                  </p>
                )}
                {vragenChronologisch?.map((v) => (
                  <VraagThread
                    key={v.id}
                    vraag={v}
                    administratieId={administratieId ?? ''}
                    naamVoor={naamVoor}
                    metFactuurlink={false}
                    onGewijzigd={() => {
                      laadVragen()
                      laadDetail()
                    }}
                  />
                ))}
              </div>
            )}
            {tijdlijnTab === 'tijdlijn' && (
            <table className="lines" role="tabpanel" aria-label="Tijdlijn">
              <tbody>
                {detail.tijdlijn.map((g, i) => (
                  <tr key={i}>
                    <td style={{ whiteSpace: 'nowrap', color: 'var(--muted)' }}>{formatDatum(g.tijdstip)}</td>
                    <td>
                      {g.van_status ? (
                        <>
                          {g.van_status === g.naar_status ? (
                            // Tijdlijn-notitie zonder statusovergang (bv. IBAN-afwijzing of
                            // her-aanvraag op de wachtstatus): geen misleidende "X → X"-pijl.
                            <>
                              Status blijft <b>{statusLabel(g.naar_status)}</b>
                            </>
                          ) : (
                            <>
                              {statusLabel(g.van_status)} → <b>{statusLabel(g.naar_status)}</b>
                            </>
                          )}
                          {g.actor_is_systeem && (
                            <span className="chip geheugen" style={{ marginLeft: 6 }} title="Achtergrondverwerking — geen menselijke handeling">
                              ⚙ systeem
                            </span>
                          )}
                        </>
                      ) : (
                        <>
                          Document binnengekomen — status <b>{statusLabel(g.naar_status)}</b>
                          {detail.mogelijk_duplicaat_van && (
                            <div className="hint" style={{ marginTop: 2 }}>
                              Mogelijk duplicaat van{' '}
                              <Link to={`/documenten/${administratieId}/${detail.mogelijk_duplicaat_van.document_id}`}>
                                {detail.mogelijk_duplicaat_van.bestandsnaam} (
                                {formatDatumKort(detail.mogelijk_duplicaat_van.aangemaakt_op)})
                              </Link>
                              — beoordelen
                            </div>
                          )}
                        </>
                      )}
                      {g.detail && 'extractie_wachtrij' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Groot document ({typeof g.detail.paginas === 'number' ? `${g.detail.paginas} pagina's, ` : ''}
                          {typeof g.detail.bytes === 'number' ? `${(g.detail.bytes / (1024 * 1024)).toFixed(1)} MB` : ''}) —
                          extractie op de achtergrond
                        </div>
                      )}
                      {g.detail && 'herstel' in g.detail && g.detail.herstel === 'achtergebleven_na_herstart' && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Opnieuw ingepland na een herstart van de verwerking
                        </div>
                      )}
                      {g.detail && 'ubl_parse_fout' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          UBL-parsefout: {String(g.detail.ubl_parse_fout)}
                        </div>
                      )}
                      {g.detail && 'ai_extractie_fout' in g.detail && (
                        <div className="hint" style={{ marginTop: 2, color: 'var(--orange)' }}>
                          AI-extractie mislukt (handmatig invullen): {String(g.detail.ai_extractie_fout)}
                        </div>
                      )}
                      {g.detail && 'ai_extractie_overgeslagen' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          AI-extractie overgeslagen: {aiOvergeslagenLabel(String(g.detail.ai_extractie_overgeslagen))}
                        </div>
                      )}
                      {g.detail && 'ai_extractie_onvolledig' in g.detail && (
                        <div className="hint" style={{ marginTop: 2, color: 'var(--red)' }}>
                          {String(g.detail.ai_extractie_onvolledig)}
                        </div>
                      )}
                      {g.detail && 'vraag_id' in g.detail && g.naar_status === 'vraag_open' && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Vraag gesteld door {naamVoor(g.actor_id)} — toegewezen aan{' '}
                          {naamVoor(typeof g.detail.toegewezen_aan === 'string' ? g.detail.toegewezen_aan : null)}
                        </div>
                      )}
                      {g.detail && 'geboekt_ondanks_match_afwijking' in g.detail && (
                        <div className="hint" style={{ marginTop: 2, color: 'var(--orange)' }}>
                          Geboekt ondanks match-afwijking — expliciet bevestigd (besluit vastgelegd in het
                          auditlog)
                        </div>
                      )}
                      {g.detail && 'tegenboeking' in g.detail && (
                        <div className="hint" style={{ marginTop: 2, color: 'var(--orange)' }}>
                          {(() => {
                            const info = g.detail.tegenboeking as Record<string, unknown> | null
                            if (!info || typeof info !== 'object') return 'Tegengeboekt'
                            const soortTekst =
                              info.soort === 'vervang'
                                ? 'Tegengeboekt én klaargezet om opnieuw te boeken (herboeking gekoppeld — uitgezonderd van het duplicaatsignaal)'
                                : 'Volledig tegengeboekt — origineel gemarkeerd TEGENGEBOEKT'
                            const boekstuk = typeof info.rlz_boekstuknummer === 'string' ? info.rlz_boekstuknummer : null
                            const reden = typeof info.reden === 'string' ? info.reden : null
                            return `${soortTekst} door ${naamVoor(g.actor_id)}${boekstuk ? ` · tegenboeking ${boekstuk}` : ''}${reden ? ` — “${reden}”` : ''}`
                          })()}
                        </div>
                      )}
                      {g.detail && 'match_mail_verzonden' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Mail over de urenmatch verzonden door {naamVoor(g.actor_id)}
                          {(() => {
                            const info = g.detail.match_mail_verzonden
                            return info && typeof info === 'object' && 'aan' in info
                              ? ` aan ${String((info as { aan: unknown }).aan)}`
                              : ''
                          })()}
                        </div>
                      )}
                      {g.detail && 'vraag_beantwoord' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Vraag beantwoord door {naamVoor(g.actor_id)}
                        </div>
                      )}
                      {g.detail && 'vraag_afgehandeld' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Vraag afgehandeld door {naamVoor(g.actor_id)} — dialoog in het tabblad Opmerkingen
                        </div>
                      )}
                      {g.detail && 'vraag_ingetrokken' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Vraag ingetrokken door {naamVoor(g.actor_id)}
                          {typeof g.detail.reden === 'string' && g.detail.reden ? ` — “${g.detail.reden}”` : ''}
                        </div>
                      )}
                      {g.detail && 'afwijzing_id' in g.detail && g.naar_status === 'afgewezen' && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Afgewezen door {naamVoor(g.actor_id)}
                          {typeof g.detail.reden === 'string' && g.detail.reden ? ` — reden: “${g.detail.reden}”` : ''}
                          {' '}· ter controle naar{' '}
                          {naamVoor(typeof g.detail.toegewezen_aan === 'string' ? g.detail.toegewezen_aan : null)}
                        </div>
                      )}
                      {g.detail && 'afwijzing_heropend' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Heropend door {naamVoor(g.actor_id)} — terug naar de status van vóór de afwijzing
                        </div>
                      )}
                      {g.detail && 'iban_aangeboden' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Afwijkend IBAN ter accordering aangeboden door {naamVoor(g.actor_id)}
                          {typeof g.detail.soort === 'string' && (g.detail.soort === 'regulier' || g.detail.soort === 'g_rekening')
                            ? ` (${SOORT_LABELS[g.detail.soort]})`
                            : ''}{' '}
                          — vier-ogen-controle, boeken geblokkeerd
                        </div>
                      )}
                      {g.detail && 'iban_geaccordeerd' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          IBAN geaccordeerd door {naamVoor(g.actor_id)} — rekening toegevoegd aan de vertrouwde
                          set, boeken weer mogelijk
                        </div>
                      )}
                      {g.detail && 'iban_afgewezen' in g.detail && (
                        <div className="hint" style={{ marginTop: 2, color: 'var(--red)' }}>
                          IBAN-aanvraag afgewezen door {naamVoor(g.actor_id)}
                          {typeof g.detail.reden === 'string' && g.detail.reden ? ` — reden: “${g.detail.reden}”` : ''}{' '}
                          — document blijft geblokkeerd
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
