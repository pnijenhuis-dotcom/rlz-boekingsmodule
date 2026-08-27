import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  bulkTerAccorderingAanbieden,
  haalAccorderingInstellingen,
  haalVervallenMeldingen,
  type BulkAanbiedenResponseDto,
  type VervallenMeldingDto,
} from '../accordering/accorderingApi'
import { ApiError, apiJson, apiPostJson } from '../api/client'
import type { DocumentActieResponseDto, DocumentListItemDto, DocumentListResponseDto, VraagDto } from '../api/types'
import { haalRekeningen, type RekeningenDto } from '../bank/bankApi'
import { SNELTOETSEN_LIJST, useSneltoetsen } from '../document/sneltoetsen'
import { haalUrenStand, type UrenStandDto } from '../meerwerk/meerwerkApi'
import { AnkerPopup, Checkbox, useToastOptioneel } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { useMedewerkers } from '../vragen/useMedewerkers'
import { haalVragenOp } from '../vragen/vragenApi'
import { Breadcrumb } from './Breadcrumb'
import { useDichtheid } from './dichtheid'
import { SOORT_VOLGORDE, documentRoute, amountKlasse, formatBedrag, formatBinnenkomst, formatDatum, formatDatumKort, isOpenstaand, soortLabel } from './format'
import { KlantUpload } from './KlantStanden'
import {
  SOORT_ALLE,
  STATUSFILTER_ALLE,
  STATUSFILTER_AUTOMATISCH,
  STATUSFILTER_DUPLICAAT,
  STATUSFILTER_URENMATCH,
  filterDocumenten,
  isMogelijkDuplicaat,
  isUrenmatchAfwijking,
  kiesTabVoorStatus,
  lijstContextNaarParams,
  type LijstContext,
} from './lijstContext'
import { extractieActief, statusLabel } from './status'
import { StatusChip } from './StatusChip'
import { VerwijderDialog } from './VerwijderDialog'

/** Ververs-interval zolang er documenten in extractie_wachtrij/extractie_bezig staan. */
const EXTRACTIE_POLL_MS = 3000

/** Vaste tab-volgorde (mockup-norm 25-08) — leeft in ./format (gedeeld met de "volgende
 * document"-keuze); onbekende soorten volgen alfabetisch achteraan. Alleen soorten met teller > 0
 * krijgen een tab. */
export { SOORT_VOLGORDE }
/** Sentinels/constanten leven sinds 27/28-08 in ./lijstContext (gedeeld met het controlescherm). */
export { SOORT_ALLE, STATUSFILTER_DUPLICAAT }

/** Weggeklikte vervallen-meldingen (punt 2a, "eenmalig"): per batch per browser onthouden —
 * zelfde localStorage-voorkeurenpatroon als de dichtheid. */
const MELDING_WEGGEKLIKT_PREFIX = 'rlz.melding.accordering_vervallen.'
function meldingWeggeklikt(batchId: string): boolean {
  try {
    return window.localStorage.getItem(MELDING_WEGGEKLIKT_PREFIX + batchId) === '1'
  } catch {
    return false
  }
}
function markeerMeldingWeggeklikt(batchId: string): void {
  try {
    window.localStorage.setItem(MELDING_WEGGEKLIKT_PREFIX + batchId, '1')
  } catch {
    // geen opslag: de banner komt bij de volgende lading terug — beter dan stil verdwijnen
  }
}

/* Klantlanding = documentenlijst (besluit Peter 25-08, feedbackronde punt C — herziet het
 * IA-besluit 15-08 "klantpagina = standen-tussenlaag"): klik op een klant landt hier, met tabs
 * per soort (alleen soorten met teller > 0), een compacte klikbare chip-rij met de overige
 * standen (bank per rekening, vragen, bij klant, afgewezen, IBAN, meerwerk, standen-overzicht) en
 * de klant-upload. Daaronder het bestaande deelscherm: segment-filters op status (voorkiesbaar
 * via `?status=`), zoekveld, verwijderen/herstellen.
 *
 * Werkstroom- + UI-run 27/28-08: (1) de lijstcontext (tab + status-filter + zoekterm) staat in de
 * URL en reist mee naar het controlescherm (`documentRoute(…, context)`) — doorloop ná boeken en
 * ‹ ›-navigatie blijven binnen dit filter; (2a) eenmalige banner "accorderingen vervallen";
 * (2b) bulk "Ter accordering aanbieden" op de tab "Klaar om te boeken"; (3) leverancier-eerst-
 * rijen mét metaregel, dichtheid normaal/compact, groene geboekt-dot; (4) verwijderen via het
 * ⋯-rijmenu mét verplichte reden; (5) "/" = zoekveld. */
export function DocumentenDeelscherm({
  administratieId,
  administratieNaam,
}: {
  administratieId: string
  administratieNaam: string
}) {
  const navigate = useNavigate()
  const { meld } = useToastOptioneel()
  const [searchParams, setSearchParams] = useSearchParams()
  const soortParam = searchParams.get('soort')
  const statusParam = searchParams.get('status')
  const zoekParam = searchParams.get('q') ?? ''
  const { naamVoor } = useMedewerkers(administratieId)
  const [dichtheid, setDichtheid] = useDichtheid()

  const [documenten, setDocumenten] = useState<DocumentListItemDto[] | null>(null)
  const [lijstFout, setLijstFout] = useState<string | null>(null)
  const [toonVerwijderd, setToonVerwijderd] = useState(false)
  const [zoekterm, setZoekterm] = useState(zoekParam)
  const [statusFilter, setStatusFilter] = useState(statusParam ?? STATUSFILTER_ALLE)
  const zoekveldRef = useRef<HTMLInputElement | null>(null)
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
  // ⋯-rijmenu (punt 4): archief-patroon — één open menu, anker per rij.
  const [menuOpen, setMenuOpen] = useState<string | null>(null)
  const menuKnoppen = useRef<Record<string, HTMLButtonElement | null>>({})
  // Accordering (punt 2): toggle-stand voor de bulk-actie + vervallen-meldingen voor de banner.
  const [accorderingAan, setAccorderingAan] = useState(false)
  const [vervallenMeldingen, setVervallenMeldingen] = useState<VervallenMeldingDto[]>([])
  const [meldingVersie, setMeldingVersie] = useState(0)
  const [selectie, setSelectie] = useState<Set<string>>(() => new Set())
  const [bulkBezig, setBulkBezig] = useState(false)
  const [bulkFout, setBulkFout] = useState<string | null>(null)
  const [bulkResultaat, setBulkResultaat] = useState<BulkAanbiedenResponseDto | null>(null)

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

  // `?status=` uit een chip/kolom-teller (Bij klant / Afgewezen / IBAN / klantoverzicht) kiest het
  // segment-filter voor; `?q=` de zoekterm (terugweg vanaf het controlescherm, punt 1).
  useEffect(() => {
    setStatusFilter(statusParam ?? STATUSFILTER_ALLE)
  }, [statusParam])
  useEffect(() => {
    setZoekterm(zoekParam)
  }, [zoekParam])

  useEffect(() => {
    let actueel = true
    setRekeningen(null)
    setVragen(null)
    setUrenStand(null)
    setAccorderingAan(false)
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
    // Klant-accordering aan? Dan is de bulk-actie zinvol (punt 2b). Fout = geen bulk, lijst gewoon.
    haalAccorderingInstellingen(administratieId)
      .then((data) => {
        if (actueel) setAccorderingAan(data.ingeschakeld)
      })
      .catch(() => undefined)
    return () => {
      actueel = false
    }
  }, [administratieId])

  // Vervallen-meldingen (punt 2a): apart effect zodat een bulk-aanbieding 'm kan verversen.
  useEffect(() => {
    let actueel = true
    haalVervallenMeldingen(administratieId)
      .then((data) => {
        if (actueel) setVervallenMeldingen(data)
      })
      .catch(() => undefined)
    return () => {
      actueel = false
    }
  }, [administratieId, meldingVersie])

  // Live extractiestatus (async extractie): zolang er documenten in de wachtrij of bij de
  // worker staan, ververst de lijst vanzelf.
  useEffect(() => {
    if (!documenten?.some((d) => extractieActief(d.status))) return
    const timer = setInterval(laadDocumenten, EXTRACTIE_POLL_MS)
    return () => clearInterval(timer)
  }, [documenten, laadDocumenten])

  // Punt 5: "/" zet de cursor in het zoekveld (alleen buiten invoervelden/dialogen).
  useSneltoetsen(SNELTOETSEN_LIJST, {
    zoeken: () => {
      zoekveldRef.current?.focus()
      zoekveldRef.current?.select()
    },
  })

  const verwijderen = async (reden: string) => {
    if (!verwijderenVoor) return
    setVerwijderenBezig(true)
    setVerwijderenFout(null)
    try {
      await apiPostJson<DocumentActieResponseDto>(
        `/administraties/${administratieId}/documenten/${verwijderenVoor.id}/verwijderen`,
        { reden },
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
  // Zonder soort-param: de eerste tab met open werk — of, bij een voorgefilterde status (punt 1a),
  // de eerste tab waarin dat filter iets oplevert; niets open → alle documenten.
  const soort: string | null =
    soortParam === SOORT_ALLE
      ? null
      : (soortParam ?? (documenten === null ? null : kiesTabVoorStatus(documenten, tabs, statusFilter)))
  const toontAlle = documenten !== null && soort === null

  /** De actuele lijstcontext (punt 1) — reist mee in élke rij-link en in de URL van dit scherm. */
  const context: LijstContext = useMemo(
    () => ({ soort, status: statusFilter, zoekterm }),
    [soort, statusFilter, zoekterm],
  )

  // Context in de URL houden (replace — geen history-vervuiling), zodat terug/vernieuwen en de
  // terugweg vanaf het controlescherm exact dezelfde lijst tonen.
  useEffect(() => {
    if (documenten === null) return
    const huidig = new URLSearchParams(searchParams)
    const gewenst = new URLSearchParams(searchParams)
    for (const sleutel of ['soort', 'status', 'q']) gewenst.delete(sleutel)
    // Soort alleen expliciet als de gebruiker (of een link) 'm zette — de automatische tab-keuze
    // blijft impliciet (zodat een nieuwe tab-met-werk gewoon de landing wordt).
    if (soortParam !== null) gewenst.set('soort', soortParam)
    const ctx = new URLSearchParams(lijstContextNaarParams({ ...context, soort: null }))
    ctx.delete('soort')
    for (const [k, v] of ctx) gewenst.set(k, v)
    if (huidig.toString() !== gewenst.toString()) setSearchParams(gewenst, { replace: true })
  }, [context, documenten, searchParams, setSearchParams, soortParam])

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

  // Eén bron voor het filteren (lijstContext.filterDocumenten) — het controlescherm rekent met
  // exact dezelfde functie voor "3 van 12" en de doorloop.
  const gefilterd = useMemo(
    () => (documenten === null ? null : filterDocumenten(documenten, context)),
    [documenten, context],
  )

  const aanwezigeStatussen = useMemo(
    () => Array.from(new Set((inScope ?? []).map((d) => d.status))).sort(),
    [inScope],
  )
  const heeftAutomatischGeboekt = useMemo(() => (inScope ?? []).some((d) => d.automatisch_geboekt), [inScope])
  const aantalMogelijkDuplicaat = useMemo(() => (inScope ?? []).filter(isMogelijkDuplicaat).length, [inScope])
  const aantalUrenmatch = useMemo(() => (inScope ?? []).filter(isUrenmatchAfwijking).length, [inScope])
  const aantalMetStatus = useCallback(
    (status: string) => (inScope ?? []).filter((d) => d.status === status).length,
    [inScope],
  )

  // --- Bulk "Ter accordering aanbieden" (punt 2b) ------------------------------------------------
  // Alleen op de tab "Klaar om te boeken" én als accordering voor deze klant aan staat; de poorten
  // per document blijven server-side onverkort (overgeslagen mét reden in het resultaatpaneel).
  const bulkMogelijk = accorderingAan && statusFilter === 'klaar_om_te_boeken'
  const selecteerbaar = useMemo(
    () => (bulkMogelijk ? (gefilterd ?? []).filter((d) => d.status === 'klaar_om_te_boeken') : []),
    [bulkMogelijk, gefilterd],
  )
  useEffect(() => {
    // Selectie opschonen zodra rijen uit de lijst verdwijnen (herladen/filterwissel).
    setSelectie((s) => {
      const ids = new Set(selecteerbaar.map((d) => d.id))
      const nieuw = new Set([...s].filter((id) => ids.has(id)))
      return nieuw.size === s.size ? s : nieuw
    })
  }, [selecteerbaar])
  const allesGeselecteerd = selecteerbaar.length > 0 && selecteerbaar.every((d) => selectie.has(d.id))
  const wisselSelectie = (id: string) =>
    setSelectie((s) => {
      const n = new Set(s)
      if (n.has(id)) n.delete(id)
      else n.add(id)
      return n
    })
  const bulkAanbieden = async () => {
    if (selectie.size === 0) return
    setBulkBezig(true)
    setBulkFout(null)
    setBulkResultaat(null)
    try {
      const resultaat = await bulkTerAccorderingAanbieden(administratieId, [...selectie])
      setBulkResultaat(resultaat)
      const gelukt = resultaat.aangeboden + resultaat.geboekt
      meld(
        `${gelukt} ${gelukt === 1 ? 'document' : 'documenten'} ter accordering aangeboden` +
          (resultaat.geboekt > 0 ? ` (${resultaat.geboekt} direct geboekt via staande goedkeuring)` : '') +
          (resultaat.overgeslagen > 0 ? ` — ${resultaat.overgeslagen} overgeslagen, zie de redenen` : ''),
        resultaat.overgeslagen > 0 ? 'warn' : 'ok',
      )
      setSelectie(new Set())
      laadDocumenten()
      setMeldingVersie((v) => v + 1)
    } catch (err) {
      setBulkFout(err instanceof ApiError ? err.message : 'Bulk aanbieden mislukt.')
    } finally {
      setBulkBezig(false)
    }
  }

  // --- Vervallen-melding (punt 2a): nieuwste batch met nog niet opnieuw aangeboden documenten ----
  const [weggeklikteBatches, setWeggeklikteBatches] = useState<Set<string>>(() => new Set())
  const actieveMelding =
    vervallenMeldingen.find(
      (m) => m.nog_niet_opnieuw_aangeboden > 0 && !weggeklikteBatches.has(m.batch_id) && !meldingWeggeklikt(m.batch_id),
    ) ?? null

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

      {/* Punt 2a: eenmalige melding — lopende accorderingen vervallen door een configuratiewijziging. */}
      {actieveMelding && (
        <div className="melding-banner" role="status" data-testid="vervallen-melding">
          <div className="melding-tekst">
            <b>
              {actieveMelding.aantal} {actieveMelding.aantal === 1 ? 'accordering is' : 'accorderingen zijn'} vervallen
            </b>{' '}
            op {formatDatum(actieveMelding.tijdstip)}
            {actieveMelding.door_naam ? ` (configuratie gewijzigd door ${actieveMelding.door_naam})` : ''} —{' '}
            {actieveMelding.reden}.{' '}
            {actieveMelding.nog_niet_opnieuw_aangeboden} {actieveMelding.nog_niet_opnieuw_aangeboden === 1 ? 'staat' : 'staan'}{' '}
            nog op &ldquo;Klaar om te boeken&rdquo; en {actieveMelding.nog_niet_opnieuw_aangeboden === 1 ? 'is' : 'zijn'} nog
            niet opnieuw aangeboden.
          </div>
          <div className="melding-acties">
            <button
              type="button"
              className="btn secondary"
              onClick={() => navigate(`/?administratie=${administratieId}&status=klaar_om_te_boeken`)}
            >
              Toon &ldquo;Klaar om te boeken&rdquo;
            </button>
            <button
              type="button"
              className="linkbtn"
              onClick={() => {
                markeerMeldingWeggeklikt(actieveMelding.batch_id)
                setWeggeklikteBatches((s) => new Set([...s, actieveMelding.batch_id]))
              }}
              aria-label="Melding sluiten"
            >
              Sluiten
            </button>
          </div>
        </div>
      )}

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
        {/* Segment-filters (mockup #scherm-docs) + zoekveld + dichtheid (punt 3b). */}
        <div className="lijst-werkbalk">
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
            {aantalUrenmatch > 0 && (
              <button
                type="button"
                className={statusFilter === STATUSFILTER_URENMATCH ? 'actief' : undefined}
                onClick={() => setStatusFilter(STATUSFILTER_URENMATCH)}
                title="Veldwerker-facturen waarvan de urenmatch afwijkt van de goedgekeurde weekstaten"
              >
                Urenmatch wijkt af ({aantalUrenmatch})
              </button>
            )}
          </div>
          <input
            ref={zoekveldRef}
            placeholder="Zoek op leverancier, bedrag, bestandsnaam…  ( / )"
            aria-label="Zoek in documenten"
            style={{ maxWidth: 300 }}
            value={zoekterm}
            onChange={(e) => setZoekterm(e.target.value)}
          />
          <div className="spacer" />
          <div className="segment" role="group" aria-label="Dichtheid van de lijst" title="Rijhoogte van de lijst (per gebruiker onthouden)">
            <button
              type="button"
              className={dichtheid === 'normaal' ? 'actief' : undefined}
              aria-pressed={dichtheid === 'normaal'}
              onClick={() => setDichtheid('normaal')}
            >
              Normaal
            </button>
            <button
              type="button"
              className={dichtheid === 'compact' ? 'actief' : undefined}
              aria-pressed={dichtheid === 'compact'}
              onClick={() => setDichtheid('compact')}
            >
              Compact
            </button>
          </div>
        </div>

        {/* Bulk-balk (punt 2b): alleen op "Klaar om te boeken" mét accordering aan. */}
        {bulkMogelijk && selecteerbaar.length > 0 && (
          <div className="bulk-balk" data-testid="bulk-balk">
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, margin: 0 }}>
              <Checkbox
                checked={allesGeselecteerd}
                aria-label="Alle documenten in deze lijst selecteren"
                onChange={(e) =>
                  setSelectie(e.target.checked ? new Set(selecteerbaar.map((d) => d.id)) : new Set())
                }
              />
              {selectie.size === 0
                ? `Selecteer documenten om ze in één keer ter accordering aan te bieden (${selecteerbaar.length} klaar om te boeken)`
                : `${selectie.size} van ${selecteerbaar.length} geselecteerd`}
            </label>
            <div className="spacer" />
            <button
              type="button"
              className="btn"
              disabled={selectie.size === 0 || bulkBezig}
              onClick={() => void bulkAanbieden()}
              title="Zelfde poorten als de losse knop: harde checks, doorbelasting-checks en match-bevestigingen per document — wat niet mag, wordt overgeslagen mét reden"
            >
              {bulkBezig ? 'Aanbieden…' : `Ter accordering aanbieden${selectie.size > 0 ? ` (${selectie.size})` : ''} →`}
            </button>
          </div>
        )}
        {bulkFout && <FoutMelding melding={bulkFout} />}
        {bulkResultaat && (
          <div className="hint bulk-resultaat" role="status" style={{ marginBottom: 12 }}>
            <b>
              {bulkResultaat.aangeboden} aangeboden
              {bulkResultaat.geboekt > 0 ? `, ${bulkResultaat.geboekt} direct geboekt (staande goedkeuring)` : ''}
              {bulkResultaat.overgeslagen > 0 ? `, ${bulkResultaat.overgeslagen} overgeslagen` : ''}.
            </b>
            {bulkResultaat.overgeslagen > 0 && (
              <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
                {bulkResultaat.resultaten
                  .filter((r) => r.uitkomst === 'overgeslagen')
                  .map((r) => (
                    <li key={r.document_id}>
                      <b>{r.bestandsnaam ?? r.document_id}</b>: {r.reden ?? 'geweigerd'}
                    </li>
                  ))}
              </ul>
            )}
            {bulkResultaat.resultaten.some((r) => r.boek_fout) && (
              <ul style={{ margin: '4px 0 0', paddingLeft: 18, color: 'var(--danger)' }}>
                {bulkResultaat.resultaten
                  .filter((r) => r.boek_fout)
                  .map((r) => (
                    <li key={r.document_id}>
                      <b>{r.bestandsnaam ?? r.document_id}</b>: boeken ná staande goedkeuring mislukt — {r.boek_fout}
                    </li>
                  ))}
              </ul>
            )}{' '}
            <button type="button" className="linkbtn" onClick={() => setBulkResultaat(null)}>
              Sluiten
            </button>
          </div>
        )}

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
            <table className={`documenten-tabel${dichtheid === 'compact' ? ' dichtheid-compact' : ''}`} data-dichtheid={dichtheid}>
              <tbody>
                <tr>
                  {bulkMogelijk && <th className="selectie" aria-label="Selectie" />}
                  <th>Leverancier</th>
                  <th>Factuurdatum</th>
                  <th className="amount">Bedrag (incl. btw)</th>
                  <th>Status</th>
                  <th>Toegewezen</th>
                  <th />
                </tr>
                {gefilterd.map((d) => {
                  const isVerwijderd = d.status === 'verwijderd'
                  // Backend blokkeert dit hard (bewaarplicht/lopende accordering) — het menu-item legt
                  // uit waarom i.p.v. stil te verdwijnen.
                  const redenNietVerwijderbaar =
                    d.status === 'geboekt'
                      ? 'Geboekt in RLZ — bewaarplicht; terugdraaien kan alleen via storno of tegenboeken.'
                      : d.status === 'ter_accordering'
                        ? 'Ligt bij de klant ter accordering — trek de accordering eerst in.'
                        : null
                  const isKassarapport = d.soort === 'kassarapport'
                  const isVerkoopfactuur = d.soort === 'verkoopfactuur'
                  const isWaarborg = d.soort === 'waarborg'
                  const route = documentRoute(administratieId, d, context)
                  const geselecteerd = selectie.has(d.id)
                  return (
                    <tr
                      key={d.id}
                      className={`clickable${geselecteerd ? ' geselecteerd' : ''}`}
                      onClick={() => navigate(route)}
                    >
                      {bulkMogelijk && (
                        <td className="selectie" onClick={(e) => e.stopPropagation()}>
                          {d.status === 'klaar_om_te_boeken' && (
                            <Checkbox
                              checked={geselecteerd}
                              aria-label={`Selecteer ${d.leverancier ?? d.bestandsnaam}`}
                              onChange={() => wisselSelectie(d.id)}
                            />
                          )}
                        </td>
                      )}
                      <td>
                        {/* Punt 3a: leverancier eerst (vet), bestandsnaam + binnenkomst als metaregel. */}
                        <div className="lijst-hoofd">{d.leverancier ?? d.bestandsnaam}</div>
                        <div className="lijst-meta">
                          {d.leverancier ? `${d.bestandsnaam} · ` : ''}
                          {d.bron} · {formatBinnenkomst(d.aangemaakt_op)}
                        </div>
                      </td>
                      <td>{d.factuurdatum ? formatDatumKort(d.factuurdatum) : '—'}</td>
                      <td className={amountKlasse(d.totaalbedrag)}>{formatBedrag(d.totaalbedrag)}</td>
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
                      <td>
                        {d.status === 'ter_accordering' && d.accordeur_aan_de_beurt ? (
                          <span title="Klant-accordeur die nu aan de beurt is">
                            {d.accordeur_aan_de_beurt.naam}
                            <span style={{ color: 'var(--muted)' }}> · laag {d.accordeur_aan_de_beurt.laag}</span>
                          </span>
                        ) : d.toegewezen_aan ? (
                          naamVoor(d.toegewezen_aan)
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="acties">
                        {/* Punt 4: ⋯-rijmenu (archief-patroon) — verwijderen zit achter een menu-item mét
                            bevestigingsdialoog en verplichte reden, nooit meer één onbeschermde klik. */}
                        <button
                          ref={(el) => {
                            menuKnoppen.current[d.id] = el
                          }}
                          type="button"
                          className="icon-btn"
                          aria-label={`Acties voor ${d.leverancier ?? d.bestandsnaam}`}
                          aria-haspopup="menu"
                          aria-expanded={menuOpen === d.id}
                          onClick={(e) => {
                            e.stopPropagation()
                            setMenuOpen((h) => (h === d.id ? null : d.id))
                          }}
                        >
                          ⋯
                        </button>
                        <AnkerPopup
                          open={menuOpen === d.id}
                          anker={menuKnoppen.current[d.id] ?? null}
                          kant="onder"
                          uitlijning="eind"
                          className="rijmenu"
                          role="menu"
                          aria-label={`Acties voor ${d.leverancier ?? d.bestandsnaam}`}
                          onAnkerUitBeeld={() => setMenuOpen(null)}
                          onClick={(e) => e.stopPropagation()}
                        >
                          <button
                            type="button"
                            className="linkbtn"
                            role="menuitem"
                            onClick={() => {
                              setMenuOpen(null)
                              navigate(route)
                            }}
                          >
                            Openen
                          </button>
                          {isVerwijderd ? (
                            <button
                              type="button"
                              className="linkbtn"
                              role="menuitem"
                              disabled={herstellenBezig === d.id}
                              onClick={() => {
                                setMenuOpen(null)
                                void herstellen(d.id)
                              }}
                            >
                              {herstellenBezig === d.id ? 'Bezig…' : '↺ Herstellen'}
                            </button>
                          ) : (
                            <>
                              <button
                                type="button"
                                className="linkbtn"
                                role="menuitem"
                                disabled={redenNietVerwijderbaar !== null}
                                aria-disabled={redenNietVerwijderbaar !== null}
                                onClick={() => {
                                  if (redenNietVerwijderbaar !== null) return
                                  setMenuOpen(null)
                                  setVerwijderenFout(null)
                                  setVerwijderenVoor(d)
                                }}
                              >
                                🗑 Verwijderen…
                              </button>
                              {redenNietVerwijderbaar !== null && (
                                <div className="hint" style={{ padding: '2px 8px 6px', maxWidth: 260 }}>
                                  {redenNietVerwijderbaar}
                                </div>
                              )}
                            </>
                          )}
                        </AnkerPopup>
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
