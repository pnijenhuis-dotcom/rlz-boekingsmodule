import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, apiFetch, apiJson } from '../api/client'
import type {
  CheckRapportDto,
  DocumentDetailDto,
  OmzetBoekenResponseDto,
  OmzetMargeStandDto,
  OmzetRegelDto,
  OmzetVoorstelDto,
  OmzetVoorstelInputDto,
} from '../api/types'
import { GeboektInRlzRegel } from '../document/GeboektInRlz'
import { bedragAlsGetal, normaliseerBedrag } from '../document/bedrag'
import { anderModus, brutoNaarNetto, rondCenten, useBedragModus } from '../document/bedragModus'
import { BedragModusInput } from '../document/BedragModusInput'
import { SearchableCombobox } from '../document/SearchableCombobox'
import { useAutoChecks } from '../document/useAutoChecks'
import { useGrootboekOpties, useTaxrateOpties } from '../document/useSyncOpties'
import { useTaxrateOptiesGefilterd } from '../document/useTaxrateOptiesGefilterd'
import { ChecksPopup } from '../ui/ChecksPopup'
import { DatePicker } from '../ui/DatePicker'
import { haalOmzetVoorstelOp, slaOmzetVoorstelOp, voerOmzetChecksUit, zetVerkoopCategorie } from './omzetApi'
import { BronBlok, bronNaam } from './BronBlok'
import { SkeletonPaneel } from '../ui/basis'
import { metViewerOpties } from '../document/pdfWeergaveUrl'

/** Bewerkbare regel-staat: bedragen als tekst (NL-invoer toegestaan), keuzes als id's. Kassabedragen zijn BRUTO
 * (incl. btw) — de bron-modus van de omzetkolom; netto/btw worden per regel deterministisch afgeleid. */
interface RegelStaat {
  categorie: string
  omzetBedrag: string
  kostprijsBedrag: string
  omzetLedgerId: string | null
  taxrateId: string | null
  kostprijsLedgerId: string | null
  herkomst: string
  btwHerkomst: string | null
  btwHerkomstDetail: string | null
}

function naarRegelStaat(regel: OmzetRegelDto): RegelStaat {
  return {
    categorie: regel.categorie,
    omzetBedrag: regel.omzet_bedrag ?? '',
    kostprijsBedrag: regel.kostprijs_bedrag ?? '',
    omzetLedgerId: regel.omzet_ledger_id,
    taxrateId: regel.taxrate_id,
    kostprijsLedgerId: regel.kostprijs_ledger_id,
    herkomst: regel.herkomst,
    btwHerkomst: regel.btw_herkomst ?? null,
    btwHerkomstDetail: regel.btw_herkomst_detail ?? null,
  }
}

function formatBedrag(waarde: number): string {
  return waarde.toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** Eurocel zoals in de bouwnorm (mockup v2, correctie Peter 16-09): € links, getal rechts, vaste breedte — de
 * totaalregel lijnt zo exact uit op de cellen erboven. */
function Eur({ waarde, vet }: { waarde: number | null; vet?: boolean }) {
  return (
    <span className="omzet-eur" style={{ fontWeight: vet ? 700 : undefined }}>
      <i>€</i>
      <span>{waarde === null ? '—' : formatBedrag(waarde)}</span>
    </span>
  )
}

/** Statussen waaruit de backend een boekpoging accepteert (documenten.boeken-poort). */
const BOEKBARE_STATUSSEN = new Set(['te_controleren', 'klaar_om_te_boeken', 'boeken_mislukt', 'handmatig_afmaken'])

const PROFX_BRONNEN = new Set(['profx_journaal', 'profx_margerapport'])

function margeChip(marge: OmzetMargeStandDto | null | undefined): { tekst: string; klasse: string; titel: string } | null {
  if (!marge) return null
  const week = marge.week != null ? `weekrapport ${marge.week}` : 'margerapport'
  switch (marge.stand) {
    case 'gebundeld':
      return {
        tekst: 'Margerapport gekoppeld · zelfde dag',
        klasse: 'ok',
        titel: 'Het margerapport van deze kassadag is in dit document gebundeld — de inkoopwaarde per groep is voorgevuld',
      }
    case 'gekoppeld_periode':
      return {
        tekst: `kostprijs: ${week} gekoppeld`,
        klasse: 'ok',
        titel: `Het margerapport (${marge.periode_van ?? '?'} t/m ${marge.periode_tot ?? '?'}) is een eigen document: één kostprijsmemoriaal per rapportperiode dekt deze kassadag`,
      }
    case 'geboekt':
      return { tekst: `kostprijs: ${week} geboekt`, klasse: 'ok', titel: 'Het kostprijsmemoriaal van deze periode is al geboekt' }
    default:
      return {
        tekst: `Margerapport ontbreekt · kostprijs later (${week} verwacht)`,
        klasse: 'vraag',
        titel: 'Boeken maakt nu alleen de verkoopboeking; de kostprijs volgt automatisch zodra het margerapport binnenkomt',
      }
  }
}

export function OmzetReviewScreen() {
  const { administratieId, documentId } = useParams<{ administratieId: string; documentId: string }>()

  const [detail, setDetail] = useState<DocumentDetailDto | null>(null)
  const [voorstel, setVoorstel] = useState<OmzetVoorstelDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [bijlageUrl, setBijlageUrl] = useState<string | null>(null)

  const [periodeStart, setPeriodeStart] = useState('')
  const [periodeEind, setPeriodeEind] = useState('')
  const [totaalOmzet, setTotaalOmzet] = useState('')
  const [totaalKostprijs, setTotaalKostprijs] = useState('')
  const [regels, setRegels] = useState<RegelStaat[]>([])
  const [voorraadLedgerId, setVoorraadLedgerId] = useState<string | null>(null)

  const [opslaanBezig, setOpslaanBezig] = useState(false)
  const [opslaanFout, setOpslaanFout] = useState<string | null>(null)
  const [checkRapport, setCheckRapport] = useState<CheckRapportDto | null>(null)
  const [boekenBezig, setBoekenBezig] = useState(false)
  const [boekenFout, setBoekenFout] = useState<string | null>(null)
  const [boekResultaat, setBoekResultaat] = useState<OmzetBoekenResponseDto | null>(null)
  // Elke wijziging maakt een eerder checkresultaat verouderd — het rapport blijft zichtbaar
  // maar telt niet meer als groen licht; de checks draaien daarna automatisch opnieuw
  // (blok B 2026-08-10: geen "Controleren"-knop meer).
  const [checksActueel, setChecksActueel] = useState(false)
  const [wijzigingsVersie, setWijzigingsVersie] = useState(0)
  const wijzigingsVersieRef = useRef(0)
  const [popupChecks, setPopupChecks] = useState<{ melding: string | null; checks: CheckRapportDto } | null>(null)
  // Blok E (Peter 16-09): kopje "Omzet netto/bruto" klikbaar — voorkeur per gebruiker, geen tegenwaarde onder de cel.
  const [bedragModus, wisselBedragModus] = useBedragModus()

  const markeerGewijzigd = useCallback(() => {
    setChecksActueel(false)
    wijzigingsVersieRef.current += 1
    setWijzigingsVersie(wijzigingsVersieRef.current)
  }, [])

  const grootboek = useGrootboekOpties(administratieId ?? '')
  const btwCodes = useTaxrateOpties(administratieId ?? '')
  // 18-09 DEEL B: gedeelde keuzelijst-sortering (gebruik 12 mnd bovenaan); omzet kent geen leverancier-land.
  const btwGefilterd = useTaxrateOptiesGefilterd(btwCodes.opties, null)
  const percentageMap = useMemo(() => {
    const map: Record<string, number> = {}
    for (const optie of btwCodes.opties) if (optie.percentage !== undefined) map[optie.id] = optie.percentage
    return map
  }, [btwCodes.opties])
  const rekeningLabel = useMemo(() => {
    const map: Record<string, string> = {}
    for (const o of grootboek.opties) map[o.id] = o.code ? `${o.code} ${o.label}` : o.label
    return map
  }, [grootboek.opties])
  const btwLabel = useMemo(() => {
    const map: Record<string, string> = {}
    for (const o of btwCodes.opties) map[o.id] = o.label
    return map
  }, [btwCodes.opties])

  const neemVoorstelOver = useCallback((data: OmzetVoorstelDto) => {
    setVoorstel(data)
    setPeriodeStart(data.periode_start ?? '')
    setPeriodeEind(data.periode_eind ?? '')
    setTotaalOmzet(data.rapport_totaal_omzet ?? '')
    setTotaalKostprijs(data.rapport_totaal_kostprijs ?? '')
    setRegels(data.regels.map(naarRegelStaat))
    setVoorraadLedgerId(data.voorraad_ledger_id)
  }, [])

  useEffect(() => {
    if (!administratieId || !documentId) return
    let actief = true
    Promise.all([
      apiJson<DocumentDetailDto>(`/administraties/${administratieId}/documenten/${documentId}`),
      haalOmzetVoorstelOp(administratieId, documentId),
    ])
      .then(([documentDetail, voorstelData]) => {
        if (!actief) return
        setDetail(documentDetail)
        neemVoorstelOver(voorstelData)
      })
      .catch((err: unknown) => {
        if (actief) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [administratieId, documentId, neemVoorstelOver])

  useEffect(() => {
    if (!administratieId || !documentId) return
    let objectUrl: string | null = null
    let actief = true
    void apiFetch(`/administraties/${administratieId}/documenten/${documentId}/bestand`).then(async (resp) => {
      if (!resp.ok || !actief) return
      objectUrl = URL.createObjectURL(await resp.blob())
      if (actief) setBijlageUrl(objectUrl)
    })
    return () => {
      actief = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [administratieId, documentId])

  /** Per regel de afgeleide cijfers: bruto (bron), netto en btw op het percentage van de btw-code (cent-exact,
   * restcent in de btw), inkoopwaarde en marge (netto − inkoop) / netto. Geen btw-code = netto onbekend (—). */
  const afgeleid = useMemo(
    () =>
      regels.map((regel) => {
        const bruto = bedragAlsGetal(regel.omzetBedrag)
        const pct = regel.taxrateId ? percentageMap[regel.taxrateId] : undefined
        const netto = bruto !== null && pct !== undefined ? brutoNaarNetto(bruto, pct) : null
        const btw = bruto !== null && netto !== null ? rondCenten(bruto - netto) : null
        const inkoop = bedragAlsGetal(regel.kostprijsBedrag)
        const basis = netto ?? bruto
        const marge = basis !== null && basis !== 0 && inkoop !== null ? ((basis - inkoop) / basis) * 100 : null
        return { bruto, netto, btw, inkoop, marge, pct }
      }),
    [regels, percentageMap],
  )
  const kostprijsTotaalRegels = useMemo(
    () => regels.reduce((som, regel) => som + (bedragAlsGetal(regel.kostprijsBedrag) ?? 0), 0),
    [regels],
  )
  const omzetTotaalRegels = useMemo(
    () => regels.reduce((som, regel) => som + (bedragAlsGetal(regel.omzetBedrag) ?? 0), 0),
    [regels],
  )
  const nettoTotaal = afgeleid.reduce((som, a) => som + (a.netto ?? a.bruto ?? 0), 0)
  const btwTotaal = afgeleid.reduce((som, a) => som + (a.btw ?? 0), 0)
  const heeftKostprijs = kostprijsTotaalRegels !== 0
  const margeTotaal = heeftKostprijs && nettoTotaal !== 0 ? ((nettoTotaal - kostprijsTotaalRegels) / nettoTotaal) * 100 : null
  const rapportTotaal = bedragAlsGetal(totaalOmzet)
  const sluitOpRapport = rapportTotaal !== null && Math.abs(rapportTotaal - omzetTotaalRegels) < 0.005

  const wijzigRegel = (index: number, wijziging: Partial<RegelStaat>) => {
    setRegels((huidig) => huidig.map((regel, i) => (i === index ? { ...regel, ...wijziging } : regel)))
    markeerGewijzigd()
  }

  const bouwInvoer = (): OmzetVoorstelInputDto => ({
    periode_start: periodeStart || null,
    periode_eind: periodeEind || null,
    rapport_totaal_omzet: totaalOmzet ? normaliseerBedrag(totaalOmzet) : null,
    rapport_totaal_kostprijs: totaalKostprijs ? normaliseerBedrag(totaalKostprijs) : null,
    regels: regels.map((regel) => ({
      categorie: regel.categorie,
      omzet_bedrag: regel.omzetBedrag ? normaliseerBedrag(regel.omzetBedrag) : null,
      kostprijs_bedrag: regel.kostprijsBedrag ? normaliseerBedrag(regel.kostprijsBedrag) : null,
      omzet_ledger_id: regel.omzetLedgerId,
      taxrate_id: regel.taxrateId,
      kostprijs_ledger_id: regel.kostprijsLedgerId,
    })),
    voorraad_ledger_id: voorraadLedgerId,
    mapping_onthouden: true,
  })

  const opslaan = async (): Promise<boolean> => {
    if (!administratieId || !documentId) return false
    setOpslaanBezig(true)
    setOpslaanFout(null)
    // Versie vóór het versturen vastleggen: typt de gebruiker dóór terwijl de save loopt, dan
    // mag de response de verse invoer niet overschrijven (de volgende debounce-run pakt 'm op).
    const versieBijVersturen = wijzigingsVersieRef.current
    try {
      const data = await slaOmzetVoorstelOp(administratieId, documentId, bouwInvoer())
      if (wijzigingsVersieRef.current === versieBijVersturen) neemVoorstelOver(data)
      return true
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Opslaan mislukt.')
      return false
    } finally {
      setOpslaanBezig(false)
    }
  }

  /** Checks bij openen: read-only over het opgeslagen voorstel óf de prefill — zonder opslaan
   * (blok B 2026-08-10: checks draaien automatisch, geen knop). */
  const checksBijOpenen = useCallback(async () => {
    if (!administratieId || !documentId) return
    const versieBijStart = wijzigingsVersieRef.current
    const resultaat = await voerOmzetChecksUit(administratieId, documentId)
    if (wijzigingsVersieRef.current === versieBijStart) {
      setCheckRapport(resultaat.checks)
      setChecksActueel(true)
    }
  }, [administratieId, documentId])

  /** Checks na een wijziging (gedebounced): opslaan + checks — exact wat de vroegere
   * "Controleren"-knop deed, zonder menselijke handeling. */
  const checksBijWijziging = async () => {
    if (!administratieId || !documentId) return
    const versieBijStart = wijzigingsVersieRef.current
    if (!(await opslaan())) return
    try {
      const resultaat = await voerOmzetChecksUit(administratieId, documentId)
      if (wijzigingsVersieRef.current === versieBijStart) {
        setCheckRapport(resultaat.checks)
        setChecksActueel(true)
      }
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Checks uitvoeren mislukt.')
    }
  }

  const boeken = async () => {
    if (!administratieId || !documentId) return
    setBoekenBezig(true)
    setBoekenFout(null)
    try {
      if (!(await opslaan())) return
      // Rauwe apiFetch (zelfde patroon als het controlescherm): BoekenGeblokkeerdDoorChecks (409)
      // stuurt het verse CheckRapport mee in detail.checks — een object dat de generieke
      // apiJson/ApiError-afhandeling niet kan uitpakken.
      const resp = await apiFetch(`/administraties/${administratieId}/omzet/documenten/${documentId}/boeken`, {
        method: 'POST',
      })
      const body: unknown = await resp.json().catch(() => null)
      if (resp.ok) {
        const resultaat = body as OmzetBoekenResponseDto
        setBoekResultaat(resultaat)
        setDetail((huidig) => (huidig ? { ...huidig, status: resultaat.status } : huidig))
        return
      }
      const detailBody = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : null
      if (resp.status === 409 && detailBody && typeof detailBody === 'object' && 'checks' in detailBody) {
        const { melding, checks } = detailBody as { melding?: string; checks: CheckRapportDto }
        setCheckRapport(checks)
        setChecksActueel(true)
        // Blok B: de server-side herdraaide checks blokkeren → pop-up met de concrete
        // gefaalde check(s); de inline lijst blijft daarnaast staan.
        setPopupChecks({ melding: melding ?? null, checks })
      } else {
        setBoekenFout(typeof detailBody === 'string' ? detailBody : resp.statusText || `Fout (${resp.status})`)
      }
    } catch (err) {
      setBoekenFout(err instanceof ApiError ? err.message : 'Boeken mislukt.')
    } finally {
      setBoekenBezig(false)
    }
  }

  // Blok B 2026-08-10: checks draaien automatisch — bij openen (read-only) en gedebounced na
  // elke wijziging (opslaan + checks). Geen "Controleren"-knop meer.
  const { checksBezig } = useAutoChecks({
    actief:
      detail !== null && voorstel !== null && detail.status !== 'geboekt' && detail.status !== 'verwijderd',
    wijzigingsVersie,
    bijOpenen: checksBijOpenen,
    bijWijziging: checksBijWijziging,
  })

  if (laadFout) return <div className="fout">Kon omzetboeking niet laden: {laadFout}</div>
  if (!detail || !voorstel || !administratieId || !documentId) return <SkeletonPaneel />

  const isGeboekt = detail.status === 'geboekt'
  const isVraagOpen = detail.status === 'vraag_open'
  const isBoekbaar = BOEKBARE_STATUSSEN.has(detail.status)
  const nieuweCategorieen = regels.filter((r) => r.herkomst === 'nieuw')
  const checksGroen = checksActueel && checkRapport !== null && !checkRapport.geblokkeerd
  const bronDetail = voorstel.bron_detail ?? null
  const isProfx = Boolean(voorstel.bron && PROFX_BRONNEN.has(voorstel.bron))
  const isSpreadsheetBron = Boolean(voorstel.bron) && !isProfx
  const marge = isProfx ? margeChip(bronDetail?.marge) : null
  // Blok C: "eerste keer bevestigen" (Edible-default) komt als niet-blokkerende bron-controle "‹groep›: categorie uit
  // default … bevestigen" — de regel van die groep krijgt de oranje chip.
  const bevestigControles = (bronDetail?.controles ?? []).filter((c) => !c.ok && !c.blokkerend && /bevestig/i.test(c.detail))
  const betaalwijzen = Object.entries(bronDetail?.betaalwijzen ?? {})
  const tegenzijdeRegels = bronDetail?.tegenzijde?.regels ?? []
  const kostprijsRegels = regels.map((r, i) => ({ r, i })).filter(({ r }) => bedragAlsGetal(r.kostprijsBedrag))
  const boekLabel = heeftKostprijs ? 'Boeken in RLZ (2 documenten) ✓' : 'Boeken in RLZ (alleen omzet) ✓'
  // Peter 16-09 (Van Boxtel): hoe de boeking in Reeleezee gelezen wordt — binder · categorie mét herkomst; klikbaar
  // (keuzelijst gegroepeerd op binder, Uitgaven mét waarschuwing). Mens wint en wordt de default van de administratie.
  const cat = voorstel.verkoop_categorie ?? null
  const keuzes = voorstel.verkoop_categorieen ?? []
  const keuzesPerBinder = keuzes.reduce<Record<string, typeof keuzes>>((acc, k) => {
    const sleutel = k.binder ?? 'Onbekend'
    ;(acc[sleutel] ??= []).push(k)
    return acc
  }, {})
  const kiesCategorie = async (id: string) => {
    if (!administratieId || !documentId || !id) return
    try {
      const nieuw = await zetVerkoopCategorie(administratieId, id, documentId)
      setVoorstel((huidig) => (huidig ? { ...huidig, verkoop_categorie: nieuw } : huidig))
      markeerGewijzigd()
    } catch (err) {
      setOpslaanFout(err instanceof ApiError ? err.message : 'Categorie kiezen mislukt.')
    }
  }

  return (
    <div>
      <div className="topbar">
        <h1>
          <Link to={`/?administratie=${administratieId}`}>← Werkvoorraad</Link>{' '}
          <span style={{ color: 'var(--muted)', fontWeight: 400 }}>/</span> {detail.bestandsnaam}
        </h1>
        <div className="adm-select">
          <span className="chip klaar">omzetboeking · kassarapport</span>
          {voorstel.bron && (
            <span className="chip geheugen" title="Profiel Winkel / kassa: afgeleid uit een herkend kassarapport">
              Winkel / kassa
            </span>
          )}
        </div>
      </div>

      {isSpreadsheetBron && voorstel.bron && (
        <BronBlok bron={voorstel.bron} detail={voorstel.bron_detail} rekeningen={grootboek.opties} />
      )}
      <div className="membanner">
        <div className="icon">🧠</div>
        <div>
          <b>Rapport herkend:</b>{' '}
          {voorstel.rapport_titel ?? (voorstel.bron ? bronNaam(voorstel.bron) : 'kassarapport')}
          {voorstel.entiteit_naam ? ` ${voorstel.entiteit_naam}` : ''}, periode{' '}
          {voorstel.periode_start && voorstel.periode_eind
            ? `${voorstel.periode_start} t/m ${voorstel.periode_eind} (uit het rapport zelf gelezen)`
            : 'niet herkend — vul de periode hieronder in'}
          .{' '}
          {isProfx && bronDetail?.kassas && bronDetail.kassas.length > 0 && (
            <>
              {bronDetail.kassas.join(' + ')}
              {bronDetail.klanten != null ? ` · ${bronDetail.klanten} klanten` : ''} · periode 05:00 → 05:00 = één
              kassadag, boekdatum = startdag.{' '}
            </>
          )}
          {voorstel.marge_pct !== null && (
            <>
              Marge <b>{voorstel.marge_pct}%</b> (in code berekend uit de rapport-totalen).{' '}
            </>
          )}
          Duplicaat- en plausibiliteitscontrole draaien mee in de harde checks hieronder.
        </div>
      </div>
      {nieuweCategorieen.length > 0 && (
        <div className="alertbanner">
          <div className="icon">⚠️</div>
          <div>
            <b>Nieuwe categorie{nieuweCategorieen.length === 1 ? '' : 'ën'} zonder mapping:</b>{' '}
            {nieuweCategorieen.map((r) => `‘${r.categorie}’`).join(', ')} — stel per categorie de omzet-GB,
            btw-code en kostprijs-GB in. De mapping wordt per administratie onthouden voor volgende rapporten;
            boeken is geblokkeerd tot elke categorie compleet is.
          </div>
        </div>
      )}
      {isVraagOpen && (
        <div className="alertbanner">
          <div className="icon">❓</div>
          <div>
            Er staat een open vraag op dit rapport — boeken is geblokkeerd tot de vraag beantwoord of
            ingetrokken is (zie <Link to={`/?administratie=${administratieId}&sectie=vragen&document=${documentId}`}>Vragen</Link>).
          </div>
        </div>
      )}

      <div className="review">
        <div className="docpane">
          <div className="panel">
            <div className="bijlage-inhoud">
              {!bijlageUrl && <p className="hint">Bijlage laden…</p>}
              {bijlageUrl && isSpreadsheetBron && (
                <p className="hint">
                  Spreadsheet-bron — de cijfers hiernaast zijn er in code uit gelezen.{' '}
                  <a href={bijlageUrl} download={detail.bestandsnaam}>
                    Download het bestand
                  </a>
                  .
                </p>
              )}
              {bijlageUrl && !isSpreadsheetBron && (
                <object data={metViewerOpties(bijlageUrl)} type="application/pdf">
                  <p className="hint">
                    PDF-weergave niet beschikbaar —{' '}
                    <a href={bijlageUrl} download={detail.bestandsnaam}>
                      download het rapport
                    </a>
                    .
                  </p>
                </object>
              )}
            </div>
          </div>
        </div>

        <div className="formpane">
          <div className="panel">
            <h2>
              Rapportperiode &amp; totalen{' '}
              <span className="chip geheugen">mapping onthouden per administratie</span>
            </h2>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10 }}>
              <div>
                <label htmlFor="periode-start">{isProfx ? 'Kassadag · boekdatum' : 'Periode van'}</label>
                <DatePicker
                  id="periode-start"
                  value={periodeStart || null}
                  onChange={(v) => {
                    setPeriodeStart(v ?? '')
                    markeerGewijzigd()
                  }}
                  disabled={isGeboekt}
                />
              </div>
              <div>
                <label htmlFor="periode-eind">t/m</label>
                <DatePicker
                  id="periode-eind"
                  value={periodeEind || null}
                  onChange={(v) => {
                    setPeriodeEind(v ?? '')
                    markeerGewijzigd()
                  }}
                  disabled={isGeboekt}
                />
              </div>
              <div>
                <label htmlFor="totaal-omzet">Rapport-totaal omzet</label>
                <input
                  id="totaal-omzet"
                  title="Bruto omzet volgens het rapport (incl. btw)"
                  value={totaalOmzet}
                  onChange={(e) => {
                    setTotaalOmzet(e.target.value)
                    markeerGewijzigd()
                  }}
                  disabled={isGeboekt}
                />
              </div>
              <div>
                <label htmlFor="totaal-kostprijs">Rapport-totaal kostprijs</label>
                <input
                  id="totaal-kostprijs"
                  title="Inkoopwaarde volgens het margerapport"
                  value={totaalKostprijs}
                  onChange={(e) => {
                    setTotaalKostprijs(e.target.value)
                    markeerGewijzigd()
                  }}
                  disabled={isGeboekt}
                />
              </div>
            </div>
            <div className="omzet-categorie" data-testid="omzet-categorie">
              <span>Boekt in Reeleezee als:</span>{' '}
              {cat && cat.id ? (
                <>
                  <b>{cat.binder ?? '?'}</b> · {cat.naam ?? '?'}{' '}
                  <span
                    className={`chip ${cat.bron === 'mens' ? 'geheugen' : cat.is_inkomsten ? 'ok' : 'blokkerend'}`}
                    title={
                      cat.bron === 'mens'
                        ? 'Gekozen door een medewerker — geldt als default voor deze administratie'
                        : 'Automatisch gekozen op de binder Inkomsten (DocumentType 10)'
                    }
                  >
                    {cat.bron === 'mens' ? 'gekozen' : 'automatisch'}
                  </span>
                  {!cat.is_inkomsten && (
                    <span className="chip blokkerend" title="Deze categorie staat in Reeleezee onder een andere map dan Inkomsten">
                      verschijnt in RLZ onder {cat.binder ?? 'onbekend'}
                    </span>
                  )}
                </>
              ) : (
                <span className="chip vraag" title="De harde check 'Omzetcategorie (Inkomsten)' bepaalt de categorie bij het openen">
                  nog niet bepaald
                </span>
              )}
              {keuzes.length > 0 && !isGeboekt && (
                <select
                  aria-label="Omzetcategorie in Reeleezee"
                  value={cat?.id ?? ''}
                  onChange={(e) => void kiesCategorie(e.target.value)}
                  style={{ width: 'auto', marginLeft: 6 }}
                >
                  <option value="">wijzig…</option>
                  {Object.entries(keuzesPerBinder).map(([binder, lijst]) => (
                    <optgroup key={binder} label={binder === 'Inkomsten' ? 'Inkomsten' : `${binder} — verschijnt in RLZ onder ${binder}`}>
                      {lijst.map((k) => (
                        <option key={k.id} value={k.id}>
                          {k.naam}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              )}
            </div>
            {(voorstel.bron || marge) && (
              <div className="omzet-bronchips" data-testid="omzet-bronchips">
                {voorstel.bron && (
                  <span className="chip ok" title="Deterministisch herkend op inhoud — geen AI">
                    {bronNaam(voorstel.bron)} herkend
                  </span>
                )}
                {marge && (
                  <span className={`chip ${marge.klasse}`} title={marge.titel} data-testid="marge-stand">
                    {marge.tekst}
                  </span>
                )}
                {isProfx && bronDetail?.controles && bronDetail.controles.some((c) => !c.ok && c.blokkerend) && (
                  <span className="chip blokkerend">sluitcontrole rood — zie checks</span>
                )}
              </div>
            )}
          </div>

          <div className="panel">
            <h2>
              Omzet én kostprijs per artikelgroep{' '}
              <span className="hint" style={{ display: 'inline', fontWeight: 400 }}>
                — één rij per groep, twee RLZ-documenten
              </span>
            </h2>
            <table className="lines omzet-groepen">
              <thead>
                <tr>
                  <th>Artikelgroep</th>
                  <th>Categorie → rekening · btw</th>
                  <th className="amount">
                    <button
                      type="button"
                      className="linkbtn omzet-kopknop"
                      onClick={wisselBedragModus}
                      aria-pressed={bedragModus === 'bruto'}
                      title={`Klik om bedragen ${anderModus(bedragModus)} in te vullen — de andere waarde volgt uit de btw-code van de regel`}
                    >
                      {bedragModus === 'netto' ? 'Omzet netto' : 'Omzet bruto'}
                      <small>klik voor {anderModus(bedragModus)}</small>
                    </button>
                  </th>
                  <th className="amount">Btw</th>
                  <th className="amount">Inkoopwaarde</th>
                  <th className="amount">Marge</th>
                </tr>
              </thead>
              <tbody>
                {regels.map((regel, index) => {
                  const a = afgeleid[index]
                  const bevestig = bevestigControles.some(
                    (c) => c.detail.startsWith(`${regel.categorie}:`) || c.naam.startsWith(`${regel.categorie}:`),
                  )
                  return (
                    <tr key={regel.categorie + index}>
                      <td>
                        <b>{regel.categorie}</b>
                        {regel.herkomst === 'nieuw' && (
                          <div>
                            <span className="chip vraag">nieuw — mapping instellen</span>
                          </div>
                        )}
                        {regel.herkomst === 'mapping' && (
                          <div>
                            <span className="chip geheugen">uit mapping</span>
                          </div>
                        )}
                        {regel.herkomst === 'default' && (
                          <div>
                            <span className="chip" title="Categorie uit de standaard voor deze artikelgroep">default</span>
                          </div>
                        )}
                      </td>
                      <td>
                        <div className="omzet-cat">
                          <SearchableCombobox
                            label={`Omzet-GB ${regel.categorie}`}
                            toonLabel={false}
                            opties={grootboek.opties}
                            laden={grootboek.laden}
                            laadFout={grootboek.fout}
                            waarde={regel.omzetLedgerId}
                            onWijzig={(id) => wijzigRegel(index, { omzetLedgerId: id })}
                            placeholder="Kies omzetrekening…"
                          />
                          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <SearchableCombobox
                                label={`Btw-code ${regel.categorie}`}
                                toonLabel={false}
                                opties={btwGefilterd.opties}
                                laden={btwCodes.laden}
                                laadFout={btwCodes.fout}
                                waarde={regel.taxrateId}
                                onWijzig={(id) => wijzigRegel(index, { taxrateId: id })}
                                placeholder="Kies btw-code…"
                              />
                            </div>
                            {bevestig ? (
                              <span className="chip vraag" title="Categorie uit default — eerste keer bevestigen">
                                bevestig
                              </span>
                            ) : regel.btwHerkomst && regel.btwHerkomst.startsWith('default') ? (
                              <span className="chip" title={regel.btwHerkomstDetail ?? 'btw-default voor deze groep'}>
                                default
                              </span>
                            ) : regel.btwHerkomst === 'mapping' ? (
                              <span className="chip geheugen" title="btw uit de onthouden mapping">
                                geheugen
                              </span>
                            ) : null}
                          </div>
                        </div>
                      </td>
                      <td className="amount">
                        <BedragModusInput
                          ariaLabel={`omzetbedrag ${regel.categorie}`}
                          bron="bruto"
                          modus={bedragModus}
                          percentage={a.pct}
                          waarde={regel.omzetBedrag}
                          onWijzig={(w) => wijzigRegel(index, { omzetBedrag: w })}
                          disabled={isGeboekt}
                          className="omzet-cel"
                        />
                      </td>
                      <td className="amount" title={a.pct === undefined ? 'Geen btw-code — btw niet af te leiden' : undefined}>
                        <Eur waarde={a.btw} />
                      </td>
                      <td className="amount">
                        {heeftKostprijs || isProfx ? (
                          <input
                            aria-label={`Kostprijsbedrag ${regel.categorie}`}
                            className={`omzet-cel${a.inkoop === null ? ' grijs' : ''}`}
                            inputMode="decimal"
                            placeholder="—"
                            title={a.inkoop === null ? 'Geen inkoopwaarde — margerapport ontbreekt of deze groep staat er niet in' : 'Inkoopwaarde uit het margerapport; mens wint'}
                            style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                            value={regel.kostprijsBedrag}
                            onChange={(e) => wijzigRegel(index, { kostprijsBedrag: e.target.value })}
                            disabled={isGeboekt}
                          />
                        ) : (
                          <input
                            aria-label={`Kostprijsbedrag ${regel.categorie}`}
                            className="omzet-cel grijs"
                            inputMode="decimal"
                            placeholder="—"
                            style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                            value={regel.kostprijsBedrag}
                            onChange={(e) => wijzigRegel(index, { kostprijsBedrag: e.target.value })}
                            disabled={isGeboekt}
                          />
                        )}
                      </td>
                      <td className={`amount omzet-marge ${a.marge === null ? 'stil' : a.marge < 35 || a.marge > 70 ? 'warn' : 'ok'}`}>
                        {a.marge === null ? '—' : `${a.marge.toFixed(1)} %`}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={2}>
                    <b>Totaal</b>{' '}
                    <span className="hint" style={{ display: 'inline' }}>
                      {rapportTotaal === null
                        ? '— rapporttotaal ontbreekt'
                        : sluitOpRapport
                          ? `· sluit op rapport € ${formatBedrag(rapportTotaal)}`
                          : `· sluit NIET op rapport € ${formatBedrag(rapportTotaal)} (Σ regels € ${formatBedrag(omzetTotaalRegels)})`}
                    </span>{' '}
                    {rapportTotaal !== null && <span className={`chip ${sluitOpRapport ? 'ok' : 'blokkerend'}`}>{sluitOpRapport ? '✓' : '≠'}</span>}
                  </td>
                  <td className="amount">
                    <Eur waarde={bedragModus === 'netto' ? nettoTotaal : omzetTotaalRegels} vet />
                  </td>
                  <td className="amount">
                    <Eur waarde={btwTotaal} vet />
                  </td>
                  <td className="amount">
                    <Eur waarde={heeftKostprijs ? kostprijsTotaalRegels : null} vet />
                  </td>
                  <td className={`amount omzet-marge ${margeTotaal === null ? 'stil' : margeTotaal < 35 || margeTotaal > 70 ? 'warn' : 'ok'}`}>
                    {margeTotaal === null ? '—' : `${margeTotaal.toFixed(1)} %`}
                  </td>
                </tr>
              </tfoot>
            </table>
            <div className="hint">
              Kassabedragen zijn bruto (incl. btw); netto en btw per regel volgen deterministisch uit het percentage van
              de gekozen btw-code (vrijgesteld/0 % = geen splitsing) — de boekmotor rekent identiek.
            </div>

            {(betaalwijzen.length > 0 || tegenzijdeRegels.length > 0) && isProfx && (
              <div className="omzet-strook" data-testid="omzet-strook">
                <span>
                  Ontvangen (betaalwijzen):{' '}
                  {betaalwijzen.length === 0 ? (
                    <span className="chip vraag" title="Blad 3 (betaalwijzen) ontbreekt — alles op kas mét signaal">
                      niet in het rapport — alles kas
                    </span>
                  ) : (
                    betaalwijzen.map(([naam, bedrag]) => (
                      <b key={naam} style={{ marginRight: 10 }}>
                        {naam} € {formatBedrag(bedragAlsGetal(bedrag) ?? 0)}
                      </b>
                    ))
                  )}
                </span>
                {tegenzijdeRegels.length > 0 && (
                  <span>
                    → tegenzijde:{' '}
                    {tegenzijdeRegels
                      .map((t) => `${t.betaalwijze} ${t.ledger_id ? rekeningLabel[t.ledger_id] ?? t.ledger_id : '(geen rekening)'}`)
                      .join(' · ')}{' '}
                    <Link className="linkbtn" to={`/instellingen/administraties/${administratieId}?tab=boeken-ai#omzetbronnen`}>
                      wijzig…
                    </Link>
                  </span>
                )}
              </div>
            )}

            <div className="omzet-kaarten">
              <div className="omzet-kaart" data-testid="kaart-verkoop">
                <div className="t">
                  Verkoop → Reeleezee{' '}
                  <span className="chip">
                    {regels.length} regels · € {formatBedrag(omzetTotaalRegels)} incl.
                  </span>
                </div>
                <div className="d">
                  Kasomzet-bon (Receipt, geen debiteur), boekdatum {periodeStart || '—'}, btw per regel
                  {tegenzijdeRegels.length > 0 ? '; tegenzijde per betaalwijze' : ''}
                  {cat && cat.id ? `; in Reeleezee onder ${cat.binder ?? '?'} · ${cat.naam ?? '?'}` : ''}.
                </div>
                <details>
                  <summary>regels tonen</summary>
                  <table>
                    <tbody>
                      {regels.map((regel, index) => (
                        <tr key={regel.categorie + index}>
                          <td>{regel.omzetLedgerId ? rekeningLabel[regel.omzetLedgerId] ?? regel.omzetLedgerId : '(geen rekening)'} · {regel.categorie}</td>
                          <td className="r">netto € {formatBedrag(afgeleid[index].netto ?? afgeleid[index].bruto ?? 0)}</td>
                          <td className="r">btw € {formatBedrag(afgeleid[index].btw ?? 0)}{regel.taxrateId ? ` (${btwLabel[regel.taxrateId] ?? ''})` : ''}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              </div>
              <div className="omzet-kaart" data-testid="kaart-kostprijs" style={{ opacity: heeftKostprijs ? 1 : 0.6 }}>
                <div className="t">
                  Kostprijs → memoriaal{' '}
                  <span className={`chip ${heeftKostprijs ? '' : 'vraag'}`}>
                    {heeftKostprijs ? `${kostprijsRegels.length} regels · € ${formatBedrag(kostprijsTotaalRegels)}` : 'wacht op margerapport'}
                  </span>
                </div>
                <div className="d">
                  {heeftKostprijs
                    ? 'Per groep: kostprijs verkopen (D) ↔ voorraad / inkoop (C). Bron: margerapport, mens wint. Beide documenten als één transactie: faalt document 2, dan wordt document 1 teruggedraaid — nooit stil een halve boeking.'
                    : 'Boeken maakt nu alleen de verkoopboeking; de kostprijs volgt zodra het margerapport van deze periode binnenkomt (geen blokkade).'}
                </div>
                {heeftKostprijs && (
                  <details>
                    <summary>regels tonen</summary>
                    <table>
                      <tbody>
                        {kostprijsRegels.map(({ r, i }) => (
                          <tr key={r.categorie + i}>
                            <td>{r.categorie}</td>
                            <td>
                              <SearchableCombobox
                                label={`Kostprijs-GB ${r.categorie}`}
                                toonLabel={false}
                                opties={grootboek.opties}
                                laden={grootboek.laden}
                                laadFout={grootboek.fout}
                                waarde={r.kostprijsLedgerId}
                                onWijzig={(id) => wijzigRegel(i, { kostprijsLedgerId: id })}
                                placeholder="Kies kostenrekening…"
                              />
                            </td>
                            <td className="r">D € {formatBedrag(bedragAlsGetal(r.kostprijsBedrag) ?? 0)}</td>
                          </tr>
                        ))}
                        <tr>
                          <td>
                            <b>aan Voorraad (tegenrekening)</b>
                          </td>
                          <td>
                            <SearchableCombobox
                              label="Voorraad-tegenrekening"
                              toonLabel={false}
                              opties={grootboek.opties}
                              laden={grootboek.laden}
                              laadFout={grootboek.fout}
                              waarde={voorraadLedgerId}
                              onWijzig={(id) => {
                                setVoorraadLedgerId(id)
                                markeerGewijzigd()
                              }}
                              placeholder="Kies voorraadrekening…"
                            />
                          </td>
                          <td className="r">
                            <b>C € {formatBedrag(kostprijsTotaalRegels)}</b>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </details>
                )}
              </div>
            </div>
          </div>

          <div className="panel">
            <h2>
              Harde checks{' '}
              {checksBezig ? (
                <span className="chip vraag">checks worden uitgevoerd…</span>
              ) : checkRapport !== null && checksActueel ? (
                <span className={`chip ${checkRapport.geblokkeerd ? 'blokkerend' : 'ok'}`}>
                  {checkRapport.geblokkeerd ? 'blokkerend' : 'alle checks groen'}
                </span>
              ) : (
                <span className="chip">automatisch</span>
              )}
            </h2>
            {checkRapport === null && !checksBezig && (
              <p className="hint">
                De harde checks draaien automatisch — bij het openen en na elke wijziging.
              </p>
            )}
            {checkRapport && (
              <>
                {!checksActueel && !checksBezig && (
                  <div className="hint" style={{ color: 'var(--orange)' }}>
                    Wijzigingen sinds de laatste controle — de checks draaien zo automatisch opnieuw.
                  </div>
                )}
                <table className="lines">
                  <tbody>
                    {checkRapport.resultaten.map((r) => (
                      <tr key={r.naam} style={!checksActueel ? { opacity: 0.55 } : undefined}>
                        <td>
                          <span className={`chip ${r.ok ? 'ok' : 'blokkerend'}`}>{r.ok ? 'OK' : 'Blokkerend'}</span>
                        </td>
                        <td>
                          <b>{r.naam}</b>
                        </td>
                        <td>{r.melding}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
            {isProfx && bronDetail?.controles && bronDetail.controles.length > 0 && (
              <table className="lines" data-testid="bron-controles" style={{ marginTop: 8 }}>
                <tbody>
                  {bronDetail.controles.map((c) => (
                    <tr key={c.naam}>
                      <td>
                        <span className={`chip ${c.ok ? 'ok' : c.blokkerend ? 'blokkerend' : 'vraag'}`}>
                          {c.ok ? 'OK' : c.blokkerend ? 'Blokkerend' : 'let op'}
                        </span>
                      </td>
                      <td>
                        <b>{c.naam}</b>
                      </td>
                      <td>{c.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel">
            {opslaanFout && <div className="fout">{opslaanFout}</div>}
            {boekenFout && <div className="fout">{boekenFout}</div>}
            {boekResultaat && (
              <div className="hint" style={{ color: 'var(--green)' }}>
                Geboekt in RLZ — verkoopfactuur <b>{boekResultaat.verkoop_boekstuknummer ?? '—'}</b>
                {boekResultaat.memoriaal_boekstuknummer && (
                  <>
                    {' '}
                    + kostprijsmemoriaal <b>{boekResultaat.memoriaal_boekstuknummer}</b>
                  </>
                )}{' '}
                — de periode is geregistreerd en kan niet dubbel geboekt worden.
              </div>
            )}
            {isGeboekt && !boekResultaat && detail.geboekt_in_rlz && <GeboektInRlzRegel stand={detail.geboekt_in_rlz} />}
            {isGeboekt && !boekResultaat && (
              <p className="hint" style={{ marginTop: 0 }}>
                {detail.geboekt_in_rlz ? 'Wijzigen' : 'Deze omzetboeking is geboekt in RLZ. Wijzigen'} kan alleen via
                stornering in Reeleezee (actie 19) — de omzet-reconciliatie signaleert dat dan.
              </p>
            )}
            {!isGeboekt && (
              <div className="actions">
                <span className="hint" style={{ marginRight: 'auto', display: 'inline' }}>
                  {heeftKostprijs
                    ? 'Boeken maakt 2 documenten in Reeleezee: verkoop + kostprijsmemoriaal. Mislukt de tweede, dan wordt de eerste gestorneerd.'
                    : 'Boeken maakt nu alleen de verkoopboeking; de kostprijs volgt zodra het margerapport binnenkomt.'}
                </span>
                <button
                  type="button"
                  className="btn secondary"
                  disabled={opslaanBezig || boekenBezig}
                  onClick={() => void opslaan()}
                >
                  {opslaanBezig ? 'Bezig…' : 'Opslaan'}
                </button>
                <button
                  type="button"
                  className="btn"
                  disabled={!isBoekbaar || !checksGroen || boekenBezig}
                  title={
                    !isBoekbaar
                      ? `Boeken kan niet vanuit status ${detail.status}`
                      : !checksGroen
                        ? 'De harde checks draaien automatisch — boeken kan zodra alle checks groen zijn'
                        : heeftKostprijs
                          ? 'Verkoopboeking + kostprijsmemoriaal worden als één logische transactie geboekt'
                          : 'Alleen de verkoopboeking — de kostprijs volgt met het margerapport'
                  }
                  onClick={() => void boeken()}
                >
                  {boekenBezig ? 'Bezig…' : boekLabel}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
      {popupChecks && (
        <ChecksPopup
          melding={popupChecks.melding}
          checks={popupChecks.checks}
          onSluiten={() => setPopupChecks(null)}
        />
      )}
    </div>
  )
}
