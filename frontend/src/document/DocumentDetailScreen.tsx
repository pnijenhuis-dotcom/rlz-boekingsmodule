import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ApiError, apiFetch, apiJson, apiPostJson } from '../api/client'
import type {
  AfwijzingDto,
  DocumentActieResponseDto,
  DocumentDetailDto,
  DocumentListResponseDto,
  HerkomstMailDto,
  VraagDto,
} from '../api/types'
import { BevestigDialog } from '../instellingen/BevestigDialog'
import { StatusChip } from '../werkvoorraad/StatusChip'
import { GeboektInRlzChip } from './GeboektInRlz'
import { documentRoute, TERMINALE_STATUSSEN } from '../werkvoorraad/format'
import { kiesVolgendDocument } from '../werkvoorraad/volgendDocument'
import { lijstContextUitParams, lijstPositie, lijstRoute, type LijstContext } from '../werkvoorraad/lijstContext'
import { SNELTOETSEN_CONTROLESCHERM, useSneltoetsen } from './sneltoetsen'
import { SneltoetsOverzicht } from './SneltoetsOverzicht'
import { AnkerPopup, useToastOptioneel, SkeletonPaneel, SkeletonRegels, SkeletonBlok } from '../ui/basis'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { extractieActief, statusLabel } from '../werkvoorraad/status'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { haalVragenOp } from '../vragen/vragenApi'
import { VraagModal } from '../vragen/VraagModal'
import { VraagThread } from '../vragen/VraagThread'
import { DoorbelastenNaBoeken, type KlaargezetteDoorbelasting } from '../doorbelasting/DoorbelastenNaBoeken'
import { DoorbelastenSectie } from '../doorbelasting/DoorbelastenSectie'
import { TegenboekSectie } from './TegenboekSectie'
import { AfwijsModal } from './AfwijsModal'
import { VerplaatsModal } from './VerplaatsModal'
import { redenNietVerplaatsbaar } from './verplaatsen'
import { AlBetaaldSignaal } from './AlBetaaldSignaal'
import { AanbetalingSignaal, type VerrekenRegel } from './AanbetalingSignaal'
import { TerugkerendSignaal } from './TerugkerendSignaal'
import { alsAiVoorstel, isTemplateVoorstel, zekerheidPct, type AiVoorstel } from './aiVoorstel'
import { AccorderingSectie } from './AccorderingSectie'
import { BoekvoorstelPanel, type ChecksStand, type GeboektInfo, type ToeTeVoegenRegel } from './BoekvoorstelPanel'
import { MatchSectie } from './MatchSectie'
import { MateriaalMatchSectie } from './MateriaalMatchSectie'
import { IbanAccorderingSectie } from './IbanAccorderingSectie'
import { SOORT_LABELS } from './ibanAccorderingApi'
import { ReviewSplitter, ReviewVergrootKnop, useReviewSplitter } from '../ui/ReviewSplitter'

/** Statussen waaruit een vraag gesteld kan worden (spiegel van de backend-poort
 * _HERSTELBARE_HERKOMSTEN in app/documenten/vragen.py — de backend blijft de waarheid). */
const VRAAG_STELLEN_STATUSSEN = new Set(['te_controleren', 'handmatig_afmaken', 'klaar_om_te_boeken'])

/** Statussen waaruit afgewezen kan worden (spiegel van app/documenten/afwijzen.py —
 * zelfde herstelbare herkomsten als bij vragen; de backend blijft de waarheid). */
const AFWIJZEN_STATUSSEN = VRAAG_STELLEN_STATUSSEN

/** Uitkomst van een verwerkingsactie op dit scherm (boeken / ter accordering / afwijzen) — voedt
 * de toast en de doorloop naar het volgende document (besluit Peter 25-08, deel 4 punt 1). */
type VerwerkingsInfo =
  | GeboektInfo
  | { uitkomst: 'afgewezen'; referentie: string | null; boekstuknummer: null; waarschuwing?: undefined }

function toastTekst(info: VerwerkingsInfo, referentie: string): string {
  switch (info.uitkomst) {
    case 'geboekt':
      return `Geboekt — ${referentie}${info.boekstuknummer ? ` · boekstuk ${info.boekstuknummer}` : ''}`
    case 'staande_goedkeuring':
      return `Geboekt via staande goedkeuring — ${referentie}`
    case 'ter_accordering':
      return `Ter accordering aangeboden — ${referentie}`
    case 'afgewezen':
      return `Afgewezen — ${referentie}`
  }
}

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
  // Deterministische terugval (best-practice-besluit 2, 31-08): zelfde paneel, eigen herkomst-chip —
  // geen zekerheidsscores (het template leest letterlijk of verwerpt volledig), wél "uit template" per veld.
  const template = isTemplateVoorstel(voorstel)
  return (
    <div className="panel">
      <h2>
        {template ? 'Veldvoorstel (template)' : 'Veldvoorstel (AI)'}{' '}
        {template ? (
          <span
            className="chip ok"
            title="Deterministisch geëxtraheerd via het geleerde template van deze leverancier — lokale code, geen AI-aanroep. Het template reproduceert de laatste bevestigde facturen van deze leverancier exact; één afwijking = volledig verworpen en AI-pad."
          >
            uit template — mens boekt
          </span>
        ) : (
          <span className="chip ai">AI-voorstel — mens boekt</span>
        )}
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
                  {waarde !== null && template && <span className="chip ok">uit template</span>}
                  {waarde !== null && !template && score !== undefined && (
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
                  {controle.regelsom_wijkt_af
                    ? `som € ${controle.regelsom} (${controle.regelsom_basis === 'excl' ? 'excl.' : 'incl.'}) wijkt af`
                    : 'regelsom sluit aan'}
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
        {template
          ? 'Gelezen via het geleerde template van deze leverancier (deterministisch, geen AI-aanroep, geen data naar buiten); ' +
            'bedragen en datums zijn cent-/dag-exact getoetst. Grootboek en btw-code komen uitsluitend uit de sync-cache — ' +
            'boeken blijft een menselijke actie. Corrigeert u een waarde en boekt u, dan vervalt het template en leert het systeem opnieuw.'
          : 'De AI leest alleen voor; bedragen, datums en suggesties zijn door de controlelaag geparst en getoetst. ' +
            'Grootboek en btw-code komen uitsluitend uit de sync-cache — boeken blijft een menselijke actie.'}
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

/** Reden waarom de laatste extractie is OVERGESLAGEN (feedbackronde 26-08 punt 4: een via de
 * module geüploade PDF zonder AI-voorstel moet zichtbaar zeggen waarom — gate uit, geen key,
 * AI-limiet) — null als er wél geëxtraheerd is of het geen PDF-extractie betrof. */
function laatsteExtractieOvergeslagen(detail: DocumentDetailDto): string | null {
  for (let i = detail.tijdlijn.length - 1; i >= 0; i--) {
    const g = detail.tijdlijn[i]
    if (g.naar_status === 'te_controleren' || g.naar_status === 'handmatig_afmaken') {
      return g.detail && 'ai_extractie_overgeslagen' in g.detail ? String(g.detail.ai_extractie_overgeslagen) : null
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

/** Tijdlijn-detail van een verhuizing (app/documenten/verplaatsen.py) — alleen renderen als de
 * namen er echt staan (oudere/afwijkende details vallen stil terug op de kale statusregel). */
function isVerplaatstDetail(
  waarde: unknown,
): waarde is { van_administratie_naam: string; naar_administratie_naam: string } {
  return (
    typeof waarde === 'object' &&
    waarde !== null &&
    typeof (waarde as { van_administratie_naam?: unknown }).van_administratie_naam === 'string' &&
    typeof (waarde as { naar_administratie_naam?: unknown }).naar_administratie_naam === 'string'
  )
}

export function DocumentDetailScreen() {
  const { administratieId, documentId } = useParams<{ administratieId: string; documentId: string }>()
  const navigate = useNavigate()
  const { meld } = useToastOptioneel()
  // Vóór de lijstpositie gedeclareerd: de sortering op "Toegewezen" (punt 21) rekent met de namen.
  const { naamVoor, isKlantAccordeur } = useMedewerkers(administratieId ?? null)
  // Lijstcontext (werkstroom-run 27/28-08, punt 1): tab + status-filter + zoekterm van de lijst
  // waaruit dit document geopend is — uit de URL-query, stuurt doorloop, ‹ › en de terugweg.
  const [searchParams] = useSearchParams()
  const context: LijstContext | null = useMemo(() => lijstContextUitParams(searchParams), [searchParams])
  // De gefilterde lijst voor ‹ › + "3 van 12" (punt 1c): één keer per document geladen; een
  // fout hier kost alleen de positie-indicator, nooit het scherm.
  const [lijst, setLijst] = useState<DocumentListResponseDto['documenten'] | null>(null)
  const positie = useMemo(
    () => (lijst && context && documentId ? lijstPositie(lijst, context, documentId, { naamVoor }) : null),
    [lijst, context, documentId, naamVoor],
  )
  // Onopgeslagen wijzigingen in het boekvoorstel (debounce nog niet klaar) → bevestiging vóór
  // ‹ ›/Esc/pijltjes; het doel wacht in `verlaatDoel`.
  const [onopgeslagen, setOnopgeslagen] = useState(false)
  const onOnopgeslagenWijzigingen = useCallback((heeft: boolean) => setOnopgeslagen(heeft), [])
  const [verlaatDoel, setVerlaatDoel] = useState<string | null>(null)
  // Actieve besluitknop van het boekvoorstel-paneel (sneltoets B, punt 5).
  const actiesRef = useRef<{ boeken: () => void; kanBoeken: boolean; boekLabel: string } | null>(null)
  const onActies = useCallback((acties: { boeken: () => void; kanBoeken: boolean; boekLabel: string }) => {
    actiesRef.current = acties
  }, [])
  const [overzichtOpen, setOverzichtOpen] = useState(false)
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
  // Gebundeld UBL+PDF-document (bundeling/samenvoegen 02-09): het opgeslagen bestand is de UBL
  // (data), de PDF is het beeld — /bestand serveert dan de PDF en de UBL blijft via ?vorm=data
  // downloadbaar. Anders (omgezette foto) is het origineel de bron zelf.
  // Sinds blok A2 02-09 serveert /bestand óók de in de UBL INGESLOTEN factuur-PDF (RLZ-export-UBL's
  // zonder bron-kolommen): dan is het geserveerde beeld een PDF terwijl bron_bestandsnaam leeg is.
  const ublMetBeeld = Boolean(
    detail?.bestandsnaam.toLowerCase().endsWith('.xml') &&
      (detail.bron_bestandsnaam?.toLowerCase().endsWith('.pdf') || bijlage?.contentType.includes('pdf')),
  )
  const downloadOrigineel = async () => {
    if (!detail || (!detail.bron_bestandsnaam && !ublMetBeeld)) return
    const pad = ublMetBeeld
      ? `/administraties/${administratieId}/documenten/${documentId}/bestand?vorm=data`
      : `/administraties/${administratieId}/documenten/${documentId}/bronbestand`
    const resp = await apiFetch(pad)
    if (!resp.ok) return
    const url = URL.createObjectURL(await resp.blob())
    const a = document.createElement('a')
    a.href = url
    a.download = ublMetBeeld ? detail.bestandsnaam : (detail.bron_bestandsnaam ?? detail.bestandsnaam)
    a.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
  const opmerkingenRef = useRef<HTMLDetailsElement | null>(null)
  // Doorbelasten in de boekflow (besluit Peter 25-08): het blok meldt of er een klaargezette run
  // is en of die groen staat — de boekknop wordt dan "Boeken + doorbelasten" (poort in het paneel).
  const [doorbelastingKlaargezet, setDoorbelastingKlaargezet] = useState<KlaargezetteDoorbelasting | null>(null)
  // Actiebalk-positie (feedback Peter 27-08): het paneel rendert zijn besluitknoppen via een
  // portal in dit anker, dat ónder het blok "Doorbelasten na boeken" staat — alleen volgorde.
  const [actiebalkDoel, setActiebalkDoel] = useState<HTMLElement | null>(null)
  // Controlescherm v2 (02-09): inklapregel "Controles" rendert het paneel via een portal onderaan
  // de werk-kolom; de stand voedt de topbar-chip "alle controles groen ✓".
  const [inklapDoel, setInklapDoel] = useState<HTMLElement | null>(null)
  const [checksStand, setChecksStand] = useState<ChecksStand | null>(null)
  const onChecksStand = useCallback((stand: ChecksStand | null) => setChecksStand(stand), [])
  const [opmerkingenOpen, setOpmerkingenOpen] = useState(false)
  const [boekvoorstelVersie, setBoekvoorstelVersie] = useState(0)
  const onVoorstelOpgeslagen = useCallback(() => setBoekvoorstelVersie((v) => v + 1), [])
  const [afwijsModalOpen, setAfwijsModalOpen] = useState(false)
  // ⋯-actiemenu in de topbar (addendum 27-08 punt 5): "Verplaats naar andere administratie…".
  const [actieMenuOpen, setActieMenuOpen] = useState(false)
  const actieMenuKnop = useRef<HTMLButtonElement | null>(null)
  const navKnopVorige = useRef<HTMLButtonElement | null>(null)
  const navKnopVolgende = useRef<HTMLButtonElement | null>(null)
  const [navTip, setNavTip] = useState<'vorige' | 'volgende' | null>(null)
  const [verplaatsModalOpen, setVerplaatsModalOpen] = useState(false)
  const { administraties } = useAdministraties()
  // Aanbetaling-verrekenregel (deel 4 punt 3): brug van het signaal naar het boekvoorstel — elke
  // klik levert een nieuw volgnummer, het paneel voegt de regel dan één keer toe.
  const [toeTeVoegenRegel, setToeTeVoegenRegel] = useState<ToeTeVoegenRegel | null>(null)
  const verrekenTeller = useRef(0)
  const voegVerrekenregelToe = useCallback((regel: VerrekenRegel) => {
    verrekenTeller.current += 1
    setToeTeVoegenRegel({ volgnummer: verrekenTeller.current, ...regel })
  }, [])
  const [heropenenBezig, setHeropenenBezig] = useState(false)
  const [heropenenFout, setHeropenenFout] = useState<string | null>(null)
  const splitter = useReviewSplitter()

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

  useEffect(() => {
    if (!administratieId || !context) {
      setLijst(null)
      return
    }
    let actueel = true
    apiJson<DocumentListResponseDto>(`/administraties/${administratieId}/documenten`)
      .then((data) => {
        if (actueel) setLijst(data.documenten)
      })
      .catch(() => {
        if (actueel) setLijst(null)
      })
    return () => {
      actueel = false
    }
  }, [administratieId, context, documentId])

  /** Navigeren mét onopgeslagen-bevestiging (punt 1c): opslaan loopt automatisch, maar een
   * wijziging van < 1 s geleden staat nog in de debounce — dan eerst vragen. */
  const verlaatNaar = useCallback(
    (doel: string) => {
      if (onopgeslagen) setVerlaatDoel(doel)
      else void navigate(doel)
    },
    [navigate, onopgeslagen],
  )
  const terugNaarLijst = useCallback(() => {
    if (!administratieId) return
    verlaatNaar(lijstRoute(administratieId, context))
  }, [administratieId, context, verlaatNaar])
  const naarBuur = useCallback(
    (richting: 'vorige' | 'volgende') => {
      if (!administratieId || !positie) return
      const buur = richting === 'vorige' ? positie.vorige : positie.volgende
      if (!buur) return
      verlaatNaar(documentRoute(administratieId, buur, context))
    },
    [administratieId, positie, context, verlaatNaar],
  )

  // Sneltoetsen (punt 5): alleen buiten invoervelden en zonder open dialoog (useSneltoetsen).
  useSneltoetsen(SNELTOETSEN_CONTROLESCHERM, {
    boeken: () => {
      const acties = actiesRef.current
      if (!acties || !acties.kanBoeken) return false
      acties.boeken()
    },
    afwijzen: () => {
      if (!detail || !AFWIJZEN_STATUSSEN.has(detail.status)) return false
      setAfwijsModalOpen(true)
    },
    vorige: () => {
      if (!positie?.vorige) return false
      naarBuur('vorige')
    },
    volgende: () => {
      if (!positie?.volgende) return false
      naarBuur('volgende')
    },
    terug: () => terugNaarLijst(),
    overzicht: () => setOverzichtOpen(true),
  })

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
    setOpmerkingenOpen(true)
    opmerkingenRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  useEffect(() => {
    if (!administratieId || !documentId) return
    let objectUrl: string | null = null
    let actief = true
    // Bugfix 02-09 (B5a): bij ‹ ›-navigatie werd het <object> hergebruikt mét de al gerevokede
    // blob-URL van het vorige document — Chrome herlaadt een <object> niet bij een data-wissel.
    // Daarom: bijlage expliciet leegmaken (skeleton) én het <object> keyen op de nieuwe URL.
    setBijlage(null)

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
  if (!administratieId || !documentId || !detail) return <SkeletonPaneel />

  const extractieProbleem = laatsteExtractieProbleem(detail)
  const extractieOvergeslagen = laatsteExtractieOvergeslagen(detail)
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

  /** Referentie voor de toast: het ingevulde factuurnummer, anders het geëxtraheerde, anders de
   * bestandsnaam — een toast zonder herkenbare aanduiding zegt niets. */
  const veldvoorstelReferentie =
    detail.veldvoorstel && typeof detail.veldvoorstel.factuurnummer === 'string' && detail.veldvoorstel.factuurnummer.trim()
      ? detail.veldvoorstel.factuurnummer
      : null
  const referentieVoorMelding = (ref: string | null) => ref?.trim() || veldvoorstelReferentie || detail.bestandsnaam

  /** Ná boeken / ter accordering / afwijzen (besluit Peter 25-08, deel 4 punt 1): toast en dan
   * automatisch door naar het volgende te verwerken document van deze klant (zelfde soort eerst);
   * stapel leeg — of lijst niet leesbaar — dan terug naar de documentenlijst. Eén uitzondering:
   * ter accordering mét boek_fout (staande goedkeuring die niet kon boeken) blijft op het
   * scherm — de fout hoort zichtbaar te blijven waar hij thuishoort, niet alleen in een toast. */
  const naVerwerking = async (info: VerwerkingsInfo) => {
    const tekst = toastTekst(info, referentieVoorMelding(info.referentie))
    if (info.uitkomst === 'ter_accordering' && info.waarschuwing) {
      meld(`${tekst} — ${info.waarschuwing}`, 'warn')
      laadDetail()
      return
    }
    meld(info.waarschuwing ? `${tekst} — ${info.waarschuwing}` : tekst, info.waarschuwing ? 'warn' : 'ok')
    // Punt 1b: mét lijstcontext blijft de doorloop BINNEN het actieve filter (vanuit "Klaar om te
    // boeken" → het volgende klaar-om-te-boeken-document); filter leeg → terug naar de lijst mét
    // dat filter. Zonder context: het bestaande gedrag (zelfde klant, zelfde soort eerst).
    let doel = lijstRoute(administratieId, context)
    try {
      const lijst = await apiJson<DocumentListResponseDto>(`/administraties/${administratieId}/documenten`)
      const volgende = kiesVolgendDocument(lijst.documenten, documentId, detail.soort, context, { naamVoor })
      if (volgende) doel = documentRoute(administratieId, volgende, context)
    } catch {
      // Lijst niet leesbaar: de documentenlijst zelf toont die fout — daar landen we dan.
    }
    void navigate(doel)
  }

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
          <Link
            to={lijstRoute(administratieId, context)}
            title="Terug naar de documentenlijst (zelfde tab en filter) — sneltoets Esc"
            onClick={(e) => {
              if (onopgeslagen) {
                e.preventDefault()
                terugNaarLijst()
              }
            }}
          >
            ← Werkvoorraad
          </Link>{' '}
          <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span>{' '}
          {detail.bestandsnaam}
        </h1>
        <div className="adm-select">
          {/* Punt 1c: ‹ › binnen dezelfde gefilterde lijst mét positie — alleen met lijstcontext
              én als dit document (nog) in die lijst staat. */}
          {positie && positie.index >= 0 && (
            <span className="lijst-navigatie" data-testid="lijst-navigatie">
              {/* B5b (02-09): de uitleg als anker-popup bij de knop zelf (AnkerPopup-patroon) i.p.v.
                  een tooltip die linksboven over de zijbalk rendert. */}
              <button
                ref={navKnopVorige}
                type="button"
                className="icon-btn"
                aria-label="Vorige document in de lijst"
                disabled={!positie.vorige}
                onClick={() => naarBuur('vorige')}
                onMouseEnter={() => setNavTip('vorige')}
                onMouseLeave={() => setNavTip(null)}
                onFocus={() => setNavTip('vorige')}
                onBlur={() => setNavTip(null)}
              >
                ‹
              </button>
              <span className="positie" aria-live="polite">
                {positie.index + 1} van {positie.totaal}
              </span>
              <button
                ref={navKnopVolgende}
                type="button"
                className="icon-btn"
                aria-label="Volgende document in de lijst"
                disabled={!positie.volgende}
                onClick={() => naarBuur('volgende')}
                onMouseEnter={() => setNavTip('volgende')}
                onMouseLeave={() => setNavTip(null)}
                onFocus={() => setNavTip('volgende')}
                onBlur={() => setNavTip(null)}
              >
                ›
              </button>
              <AnkerPopup
                open={navTip !== null}
                anker={navTip === 'vorige' ? navKnopVorige : navKnopVolgende}
                kant="onder"
                uitlijning="start"
                afstand={6}
                className="tip"
                role="tooltip"
              >
                {navTip === 'vorige' ? 'Vorige in de gefilterde lijst — sneltoets ←' : 'Volgende in de gefilterde lijst — sneltoets →'}
              </AnkerPopup>
            </span>
          )}
          {/* v2 ①: alles groen = één chip; afwijkingen staan als banner boven de actiebalk. */}
          {checksStand && (
            <span
              className={`chip ${
                checksStand.bezig || !checksStand.actueel || !checksStand.rapport
                  ? 'neutraal'
                  : checksStand.rapport.geblokkeerd
                    ? 'blokkerend'
                    : checksStand.rapport.resultaten.some((r) => r.signaal)
                      ? 'afwijking'
                      : 'ok'
              }`}
              data-testid="controles-chip"
              title="Alle controles staan onderaan in de inklapregel “Controles”"
            >
              {checksStand.bezig || !checksStand.actueel || !checksStand.rapport
                ? 'controles lopen…'
                : checksStand.rapport.geblokkeerd
                  ? `${checksStand.rapport.resultaten.filter((r) => !r.ok).length} controle(s) rood`
                  : checksStand.rapport.resultaten.some((r) => r.signaal)
                    ? `${checksStand.rapport.resultaten.filter((r) => r.signaal).length} signaal/signalen`
                    : 'alle controles groen ✓'}
            </span>
          )}
          <StatusChip status={detail.status} />
          {detail.geboekt_in_rlz && <GeboektInRlzChip stand={detail.geboekt_in_rlz} />}
          <button
            ref={actieMenuKnop}
            type="button"
            className="icon-btn"
            aria-label="Meer acties"
            aria-haspopup="menu"
            aria-expanded={actieMenuOpen}
            onClick={() => setActieMenuOpen((o) => !o)}
          >
            ⋯
          </button>
          <AnkerPopup
            open={actieMenuOpen}
            anker={actieMenuKnop}
            kant="onder"
            uitlijning="eind"
            className="rijmenu"
            role="menu"
            aria-label="Meer acties"
            onAnkerUitBeeld={() => setActieMenuOpen(false)}
          >
            {(() => {
              // Herstel foute toewijzing (besluit Peter 27-08): alleen vanuit de kantoorbak-statussen;
              // geboekt (storno/tegenboeken) en ter_accordering (eerst intrekken) leggen uit waarom niet.
              const reden = redenNietVerplaatsbaar(detail.status, detail.soort)
              return (
                <>
                  <button
                    type="button"
                    className="linkbtn"
                    role="menuitem"
                    disabled={reden !== null}
                    aria-disabled={reden !== null}
                    onClick={() => {
                      if (reden !== null) return
                      setActieMenuOpen(false)
                      setVerplaatsModalOpen(true)
                    }}
                  >
                    Verplaats naar andere administratie…
                  </button>
                  {reden !== null && (
                    <div className="hint" style={{ padding: '2px 8px 6px', maxWidth: 280 }}>
                      {reden}
                    </div>
                  )}
                  <button
                    type="button"
                    className="linkbtn"
                    role="menuitem"
                    onClick={() => {
                      setActieMenuOpen(false)
                      setOverzichtOpen(true)
                    }}
                  >
                    Sneltoetsen… <kbd className="kbd" aria-hidden>?</kbd>
                  </button>
                </>
              )
            })()}
          </AnkerPopup>
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
              {!bijlage && <SkeletonBlok />}
              {bijlage?.contentType.includes('pdf') && (
                <object key={bijlage.url} data={bijlage.url} type="application/pdf" data-testid="bijlage-pdf">
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
                <a className="btn secondary" href={bijlage.url} download={ublMetBeeld ? detail.bron_bestandsnaam ?? detail.bestandsnaam.replace(/\.xml$/i, '.pdf') : detail.bestandsnaam}>
                  Downloaden
                </a>
                {(detail.bron_bestandsnaam || ublMetBeeld) && (
                  // Omgezette afbeelding (punt 2, 25-08 deel 3): het aangeleverde origineel blijft
                  // als brondocument bewaard en is hier op te halen. Gebundeld UBL+PDF (02-09): de
                  // UBL-data naast het PDF-beeld.
                  <button
                    type="button"
                    className="btn ghost"
                    title={
                      ublMetBeeld
                        ? 'Gebundeld document: de gegevens komen uit de UBL, de PDF is het beeld'
                        : 'Deze PDF is gemaakt uit een aangeleverde afbeelding; het origineel blijft bewaard'
                    }
                    onClick={() => void downloadOrigineel()}
                  >
                    {ublMetBeeld ? `UBL-data (${detail.bestandsnaam})` : `Origineel (${detail.bron_bestandsnaam})`}
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
          {detail.factuurmatch && !TERMINALE_STATUSSEN.includes(detail.status) && (
            <MatchSectie
              administratieId={administratieId}
              documentId={documentId}
              match={detail.factuurmatch}
              onGewijzigd={laadDetail}
            />
          )}
          {/* Materiaalcontrole (steigerbouw-run D6): inkoopfacturen van gekoppelde verhuur-
              crediteuren vs geregistreerde leveringen — zelfde vlag-patroon als de urenmatch. */}
          {detail.materiaalmatch && !TERMINALE_STATUSSEN.includes(detail.status) && (
            <MateriaalMatchSectie
              administratieId={administratieId}
              documentId={documentId}
              match={detail.materiaalmatch}
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

          {extractieOvergeslagen && detail.status === 'te_controleren' && (
            <div className="panel" role="status">
              <h2>
                Geen AI-voorstel <span className="chip afwijking">extractie overgeslagen</span>
              </h2>
              <p className="hint" style={{ marginTop: 0 }}>
                AI-extractie overgeslagen: {aiOvergeslagenLabel(extractieOvergeslagen)}. Het boekingsvoorstel is daarom
                niet vooringevuld — handmatig invullen werkt gewoon.
                {extractieOvergeslagen === 'ai_extractie_uitgeschakeld' && (
                  <>
                    {' '}
                    De Beheerder kan de AI-extractie per administratie aanzetten op{' '}
                    <Link to="/instellingen/administraties">Instellingen › Administraties</Link>; daarna &ldquo;Opnieuw
                    extraheren&rdquo;.
                  </>
                )}
                {extractieOvergeslagen === 'ai_limiet_bereikt' && (
                  <>
                    {' '}
                    Verbruik en limiet: <Link to="/instellingen/intake-ai">Instellingen › Intake-AI &amp; kosten</Link>.
                  </>
                )}
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

          {/* Prijsstijging-chip terugkerende factuur (blok B 30-08): signaal, geen blokkade. */}
          {!achtergrondBezig && (
            <TerugkerendSignaal
              administratieId={administratieId}
              documentId={documentId}
              status={detail.status}
              soort={detail.soort}
              boekvoorstelVersie={boekvoorstelVersie}
            />
          )}
          {/* Aanbetaling-open-signaal (deel 4 punt 3): zelfde gates; de verrekenknop alleen
              zolang het boekvoorstel bewerkbaar is. */}
          {!achtergrondBezig && (
            <AanbetalingSignaal
              administratieId={administratieId}
              documentId={documentId}
              status={detail.status}
              soort={detail.soort}
              boekvoorstelVersie={boekvoorstelVersie}
              onVerrekenregel={
                VRAAG_STELLEN_STATUSSEN.has(detail.status) || detail.status === 'boeken_mislukt'
                  ? voegVerrekenregelToe
                  : undefined
              }
            />
          )}

          {!achtergrondBezig && (
            <BoekvoorstelPanel
              administratieId={administratieId}
              documentId={documentId}
              status={detail.status}
              veldvoorstel={detail.veldvoorstel}
              onGeboekt={(info) => void naVerwerking(info)}
              onHersteld={laadDetail}
              onVraagStellen={
                VRAAG_STELLEN_STATUSSEN.has(detail.status) ? () => setVraagModalOpen(true) : undefined
              }
              onAfwijzen={AFWIJZEN_STATUSSEN.has(detail.status) ? () => setAfwijsModalOpen(true) : undefined}
              onIbanAangeboden={VRAAG_STELLEN_STATUSSEN.has(detail.status) ? laadDetail : undefined}
              doorbelastingKlaargezet={doorbelastingKlaargezet}
              onVoorstelOpgeslagen={onVoorstelOpgeslagen}
              toeTeVoegenRegel={toeTeVoegenRegel}
              actiebalkDoel={actiebalkDoel}
              inklapDoel={inklapDoel}
              onChecksStand={onChecksStand}
              onActies={onActies}
              onOnopgeslagenWijzigingen={onOnopgeslagenWijzigingen}
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

          {/* v2 ①–③: alles passiefs/groens onderaan als inklapregel — Controles (portal uit het
              paneel), Extractie-details, Uit de e-mail, Opmerkingen, Tijdlijn. */}
          <div className="inklap-rijen" data-testid="inklap-rijen">
            {!achtergrondBezig && <div ref={setInklapDoel} data-testid="inklap-doel" style={{ display: 'contents' }} />}
            {(() => {
              // v2 ②: het AI-veldvoorstel-blok is een inklapregel — de herkomst-chips staan al op
              // de velden; hier de volledige extractie-details + "opnieuw extraheren".
              if (achtergrondBezig) return null
              const aiVoorstel = alsAiVoorstel(detail.veldvoorstel)
              if (aiVoorstel) {
                const scores = Object.values(aiVoorstel.zekerheid).filter((s): s is number => typeof s === 'number')
                const gemiddeld = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null
                const label = isTemplateVoorstel(aiVoorstel)
                  ? 'Extractie-details (template)'
                  : `Extractie-details${gemiddeld !== null ? ` (AI ${zekerheidPct(gemiddeld)})` : ' (AI)'}`
                return (
                  <details data-testid="extractie-inklap">
                    <summary>{label}</summary>
                    <div className="inklap-inhoud">
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
                    </div>
                  </details>
                )
              }
              if (!detail.veldvoorstel) return null
              return (
                <details data-testid="extractie-inklap">
                  <summary>Extractie-details (UBL)</summary>
                  <div className="inklap-inhoud">
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
                  </div>
                </details>
              )
            })()}

            {/* Uit de e-mail (feedbackronde 25-08 deel 3 punt 1b): context bij het voorstel. */}
            {detail.herkomst_mail && <UitDeEmail herkomst={detail.herkomst_mail} />}
          {/* v2 ③: tijdlijn en opmerkingen als inklapregels (waren tabs — besluit 25-08 B3;
              inhoud ongewijzigd: Tijdlijn = statusgebeurtenissen, Opmerkingen = de dialogen). */}
          <details ref={opmerkingenRef} open={opmerkingenOpen || Boolean(openVraag)} onToggle={(e) => setOpmerkingenOpen((e.target as HTMLDetailsElement).open)} data-testid="opmerkingen-inklap">
            <summary>
              Opmerkingen{documentVragen && documentVragen.length > 0 ? ` (${documentVragen.length})` : ' (0)'}
              {openVraag && (
                <span className="chip vraag" style={{ marginLeft: 6 }}>
                  open
                </span>
              )}
            </summary>
            <div className="inklap-inhoud">
              <div aria-label="Opmerkingen">
                {vragenChronologisch === null && <SkeletonRegels />}
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
                    isKlantAccordeur={isKlantAccordeur}
                    metFactuurlink={false}
                    onGewijzigd={() => {
                      laadVragen()
                      laadDetail()
                    }}
                  />
                ))}
              </div>
            </div>
          </details>
          <details data-testid="tijdlijn-inklap">
            <summary>Tijdlijn</summary>
            <div className="inklap-inhoud">
            <table className="lines" aria-label="Tijdlijn">
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
                      {g.detail && 'verplaatst' in g.detail && isVerplaatstDetail(g.detail.verplaatst) && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Verplaatst van {g.detail.verplaatst.van_administratie_naam} naar{' '}
                          {g.detail.verplaatst.naar_administratie_naam}
                          {Array.isArray(g.detail.leerregels_gecorrigeerd) && g.detail.leerregels_gecorrigeerd.length > 0
                            ? ` · toewijzings-geheugen gecorrigeerd (${(g.detail.leerregels_gecorrigeerd as string[]).join(', ')})`
                            : ' · geen leer-regel te corrigeren'}
                          {Array.isArray(g.detail.vragen_verhuisd) && g.detail.vragen_verhuisd.length > 0
                            ? ` · ${g.detail.vragen_verhuisd.length} open ${g.detail.vragen_verhuisd.length === 1 ? 'vraag' : 'vragen'} verhuisd`
                            : ''}
                          {'afwijzing_gesloten_door_verplaatsing' in g.detail ? ' · open afwijzing gesloten' : ''}
                          {' · veldvoorstel vervallen, extractie opnieuw'}
                        </div>
                      )}
                      {g.detail && 'accordering_vervallen' in g.detail && (
                        <div className="hint" style={{ marginTop: 2, color: 'var(--orange)' }}>
                          Accordering vervallen —{' '}
                          {typeof g.detail.reden === 'string' && g.detail.reden
                            ? g.detail.reden
                            : 'accorderingsconfiguratie gewijzigd — opnieuw aanbieden vereist'}
                          {' '}(door {naamVoor(g.actor_id)})
                        </div>
                      )}
                      {g.detail && 'accordering_ingetrokken' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Accordering {'na_boekfout' in g.detail ? 'ná boekfout teruggehaald' : 'ingetrokken'} door{' '}
                          {naamVoor(g.actor_id)}
                        </div>
                      )}
                      {g.detail && 'alle_lagen_akkoord' in g.detail && !('accordering_boek_fout' in g.detail) && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Alle lagen akkoord — boeken gestart (mét alle harde checks)
                        </div>
                      )}
                      {g.detail && 'accordering_boek_fout' in g.detail && (
                        <div className="hint" style={{ marginTop: 2, color: 'var(--red)' }}>
                          Boeken ná het laatste klant-akkoord mislukt — {String(g.detail.accordering_boek_fout)}
                        </div>
                      )}
                      {/* Bugfix-run 28-08 (kernprincipe "niets verdwijnt stil"): élke ⚙-systeemovergang
                          draagt een reden — generiek getoond, tenzij een specifieke regel hierboven 'm al
                          leesbaar maakt. */}
                      {g.actor_is_systeem &&
                        g.detail &&
                        typeof g.detail.reden === 'string' &&
                        g.detail.reden &&
                        !('accordering_vervallen' in g.detail) &&
                        !('accordering_boek_fout' in g.detail) &&
                        !('alle_lagen_akkoord' in g.detail) && (
                          <div className="hint" style={{ marginTop: 2 }}>
                            Reden: {g.detail.reden}
                          </div>
                        )}
                      {g.detail && 'tenaamstelling_geleerd' in g.detail && typeof g.detail.tenaamstelling_geleerd === 'string' && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Onthouden: tenaamstelling &ldquo;{g.detail.tenaamstelling_geleerd}&rdquo; hoort bij deze administratie
                        </div>
                      )}
                      {g.detail && 'vraag_hersteld_na_extractie' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Open vraag blokkeert boeken weer ná de nieuwe extractie
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
                      {g.detail && 'template_terugval' in g.detail && (
                        <div className="hint" style={{ marginTop: 2 }}>
                          Template-terugval: {String(g.detail.template_terugval)}
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
                      {/* Odoo-adapter blok E (03-09, notitie ④): een GEBOEKT-gebeurtenis in Odoo benoemt backend +
                          company — een mens moet een company-mismatch kunnen zíén. RLZ-gebeurtenissen ongewijzigd. */}
                      {g.detail && g.detail.backend === 'odoo' && g.naar_status === 'geboekt' && (
                        <div className="hint" style={{ marginTop: 2 }} data-testid="tijdlijn-geboekt-odoo">
                          Geboekt in Odoo
                          {typeof g.detail.odoo_naam === 'string' && g.detail.odoo_naam ? ` · ${g.detail.odoo_naam}` : ''}
                          {g.detail.odoo_company_id != null ? ` (company ${String(g.detail.odoo_company_id)})` : ''}
                        </div>
                      )}
                      {g.detail && Array.isArray(g.detail.btw_override) && g.detail.btw_override.length > 0 && (
                        <div className="hint" style={{ marginTop: 2, color: 'var(--orange)' }} data-testid="tijdlijn-btw-override">
                          <span className="chip afwijking">btw-cent-override</span> Btw-cent-override toegepast (± € 0,02 per tarief) — zie boeking
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
                            // Odoo (blok E): het boekstuk is een reversal (RBILL-nummer) — benoem de backend + de kruisverwijzing.
                            const inOdoo = info.backend === 'odoo' || g.detail.backend === 'odoo'
                            const kruis = typeof info.kruisverwijzing === 'string' && info.kruisverwijzing ? ` · ${info.kruisverwijzing}` : ''
                            return `${soortTekst} door ${naamVoor(g.actor_id)}${boekstuk ? ` · tegenboeking ${boekstuk}${inOdoo ? ' in Odoo' : ''}` : ''}${kruis}${reden ? ` — “${reden}”` : ''}`
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
            </div>
          </details>
          </div>

          {/* Anker voor de actiebalk (Afwijzen / Vraag stellen / Ter accordering / Boeken, al dan
              niet "+ doorbelasten"): ÓNDER het doorbelast-blok en de inklapregels — sticky onderaan
              (v2 ⑤), zodat de acties altijd in beeld zijn. Geen logica; het paneel blijft eigenaar. */}
          {!achtergrondBezig && (
            <div className="actiebalk-sticky">
              <div ref={setActiebalkDoel} data-testid="actiebalk-doel" />
            </div>
          )}

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
              referentie={veldvoorstelReferentie}
              onAfgewezen={(_afwijzing, info) => {
                setAfwijsModalOpen(false)
                void naVerwerking({ uitkomst: 'afgewezen', referentie: info.referentie, boekstuknummer: null })
              }}
              onAnnuleren={() => setAfwijsModalOpen(false)}
            />
          )}

          {verplaatsModalOpen && (
            <VerplaatsModal
              administratieId={administratieId}
              administratieNaam={administraties?.find((a) => a.id === administratieId)?.naam ?? null}
              documentId={documentId}
              bestandsnaam={detail.bestandsnaam}
              openVragen={documentVragen?.filter((v) => v.status === 'open').length ?? 0}
              tenaamstelling={detail.tenaamstelling ?? null}
              onVerplaatst={(resultaat) => {
                setVerplaatsModalOpen(false)
                meld(`Verplaatst naar ${resultaat.naar_administratie_naam} — extractie draait opnieuw`)
                // Het document is in de bron-scope niet meer zichtbaar: door naar het doel.
                void navigate(`/documenten/${resultaat.naar_administratie_id}/${documentId}`)
              }}
              onAnnuleren={() => setVerplaatsModalOpen(false)}
            />
          )}

          {overzichtOpen && <SneltoetsOverzicht onSluiten={() => setOverzichtOpen(false)} />}

          {verlaatDoel !== null && (
            <BevestigDialog
              titel="Wijzigingen worden nog opgeslagen"
              bericht={
                'Je laatste wijziging in het boekvoorstel is nog niet opgeslagen (opslaan loopt automatisch, ' +
                'maar is nog niet klaar). Wacht een moment, of verlaat het document — dan gaat die laatste ' +
                'wijziging verloren.'
              }
              bezig={false}
              fout={null}
              onBevestigen={() => {
                const doel = verlaatDoel
                setVerlaatDoel(null)
                void navigate(doel)
              }}
              onAnnuleren={() => setVerlaatDoel(null)}
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

        </div>
      </div>
    </div>
  )
}
