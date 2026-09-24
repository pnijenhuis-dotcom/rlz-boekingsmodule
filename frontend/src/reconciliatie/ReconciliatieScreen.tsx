// Inzicht › Reconciliatie — KANTOORBREED (opdracht 06-09 blok C; mockup inzicht-kantoorbreed.html
// ①②③⑨ = bouwnorm, zelfde patroon als Inzicht › Terugkerende facturen). De nachtelijke
// reconciliatie-alles-run legt onze eigen boekingen naast de werkelijke stand in Reeleezee; hier
// staat de uitkomst kantoorbreed (scope = de administraties van de gebruiker, RLS blijft de
// waarheid): server-side paginering 25, facetten administratie/soort (filter, nooit poort),
// zoekveld, tellers "N bevindingen over M administraties", urgentste bovenaan. Eén rij = één
// bevinding mét precies één handeling (②): afwijking → "Accepteren…" (Beheerder, verplichte reden),
// let-op → "Gezien…", gezien → "Toch tonen", plus de deep-link naar het document. "▶ Nu draaien" =
// één kantoorbrede achtergrondrun (③, 202 + status-poll). Teal = actie, groen = status.
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { GroepFilter } from '../ui/GroepFilter'
import { FoutMelding } from '../ui/FoutMelding'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  FormField,
  SkeletonRegels,
  useToastOptioneel,
} from '../ui/basis'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { BewustVerwijderdActie } from './BewustVerwijderdActie'
import { ExternGeboektActies } from './ExternGeboektActies'
import { isVerdwenenDocument, OpnieuwBoekenActie } from './OpnieuwBoekenActie'
import { HerboekenAlsOmzetActie, isOmzetInInkoopstroom } from './HerboekenAlsOmzetActie'
import { isKassarapportInWerkvoorraad, TypeWijzigenKassarapportActie } from './TypeWijzigenKassarapportActie'
import { BundelenActie, isUblPdfOngebundeld } from './BundelenActie'
import { FactuurPdfHerstellenActie, isDoorbelastingFactuurPdfOntbreekt } from './FactuurPdfHerstellenActie'
import { isBoekWachtrijGestrand, OpnieuwIndienenActie } from './OpnieuwIndienenActie'
import { isIntakePostvakVerschil, NuVerwerkenActie } from './NuVerwerkenActie'
import { isActivumAanmakenMislukt, OpnieuwAanmakenActie } from './OpnieuwAanmakenActie'
import { isRlzDubbel, RlzDubbelBoekstukken } from './RlzDubbelBoekstukken'
import {
  accepteerBevinding,
  BLOK_LABEL,
  gezienIntrekken,
  haalBevindingen,
  haalInstelling,
  haalLaatsteRun,
  haalRunStatus,
  herstelBewustVerwijderd,
  isBewustVerwijderdAcceptatie,
  mailStatusTekst,
  markeerGezien,
  SOORT_FACETTEN,
  SOORT_LABEL,
  startRun,
  trekAcceptatieIn,
  zetInstelling,
  type BevindingDto,
  type BevindingenLijstDto,
  type ReconciliatieRunDto,
  type SoortFacet, isIntussenExternGeboekt, externGeboektKernUitBevinding,
} from './reconciliatieApi'

const ALLE = '__alle'
/** Minimale lengte van een reden — spiegelt de server ("vereist een inhoudelijke reden"). */
const REDEN_MINIMUM = 5

function ddmm(iso: string): string {
  return new Date(iso).toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })
}

function tijd(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
}

/** Leesbare titel (07-09, blok A8) — met terugval op de CLI-regel voor een server zonder de leesbare laag. */
function titelVan(r: BevindingDto): string {
  return r.titel?.trim() ? r.titel : r.tekst
}

function isSoortFacet(w: string | null): w is SoortFacet {
  return w !== null && (SOORT_FACETTEN as string[]).includes(w)
}

/** Standregel onder de paneelkop: wat deed de laatste run, en ging de alert-mail weg? */
function runTekst(run: ReconciliatieRunDto): string {
  if (run.status === 'wachtend') return 'Reconciliatie staat klaar…'
  if (run.status === 'bezig') return 'Reconciliatie bezig…'
  if (run.status === 'fout') return `Laatste reconciliatie (${tijd(run.aangevraagd_op)}) is mislukt.`
  const mail = run.mail_status ? ` · mail: ${mailStatusTekst(run.mail_status)}` : ''
  return `Stand van ${tijd(run.afgerond_op ?? run.aangevraagd_op)} — exit ${run.exit_code ?? 0}${mail}`
}

/** Eén reden-actie: welke bevinding, welke tekst in de dialoog, welke server-aanroep. */
interface RedenActie {
  bevinding: BevindingDto
  titel: string
  beschrijving: string
  bevestig: string
  uitvoeren: (administratieId: string, reden: string) => Promise<unknown>
  gelukt: string
}

export function ReconciliatieScreen({ pollMs = 1500 }: { pollMs?: number } = {}) {
  const { rol } = useAuth()
  const isBeheerder = rol === 'beheerder'
  const { administraties } = useAdministraties()
  const toast = useToastOptioneel()
  const [zoekParams, setZoekParams] = useSearchParams()
  const administratieId = zoekParams.get('administratie_id') ?? zoekParams.get('administratie') ?? ''
  // Blok 8 run 11-09: groepskenmerk als filter (deeplink `?groep_id=`), naast administratie en soort.
  const groepId = zoekParams.get('groep_id') ?? ''
  const soortParam = zoekParams.get('soort')
  const soort: SoortFacet = isSoortFacet(soortParam) ? soortParam : 'aandacht'
  const [zoek, setZoek] = useState('')
  const [pagina, setPagina] = useState(1)
  const [data, setData] = useState<BevindingenLijstDto | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [versie, setVersie] = useState(0)
  const [run, setRun] = useState<ReconciliatieRunDto | null>(null)
  const [runStartBezig, setRunStartBezig] = useState(false)
  const [redenActie, setRedenActie] = useState<RedenActie | null>(null)
  const [gezienDagen, setGezienDagen] = useState('')
  const [dagenBezig, setDagenBezig] = useState(false)

  const herlaad = useCallback(() => setVersie((v) => v + 1), [])

  useEffect(() => {
    let actueel = true
    setLaadFout(null)
    haalBevindingen({ pagina, q: zoek, administratieId: administratieId || null, soort, groepId: groepId || null })
      .then((d) => {
        if (actueel) setData(d)
      })
      .catch((err: unknown) => {
        if (actueel) setLaadFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actueel = false
    }
  }, [pagina, zoek, administratieId, soort, groepId, versie])

  // Stand van de laatste run bij binnenkomst (en een nog lopende run oppikken).
  useEffect(() => {
    let actueel = true
    haalLaatsteRun()
      .then((r) => {
        if (actueel && r) setRun(r)
      })
      .catch(() => undefined)
    return () => {
      actueel = false
    }
  }, [])

  // "Gezien"-vervaltermijn (⑨): alleen de Beheerder mag hem zetten, iedereen mag hem zien.
  useEffect(() => {
    if (!isBeheerder) return
    let actueel = true
    haalInstelling()
      .then((i) => {
        if (actueel) setGezienDagen(String(i.gezien_dagen))
      })
      .catch(() => undefined)
    return () => {
      actueel = false
    }
  }, [isBeheerder])

  // Pollen tot klaar/fout; klaar = toast + lijst verversen, fout = zichtbaar (FoutMelding hieronder).
  useEffect(() => {
    if (!run || (run.status !== 'wachtend' && run.status !== 'bezig')) return
    let actueel = true
    const t = window.setTimeout(() => {
      haalRunStatus(run.run_id)
        .then((r) => {
          if (!actueel) return
          setRun(r)
          if (r.status === 'klaar') {
            toast.meld(`Reconciliatie afgerond (exit ${r.exit_code ?? 0}).`)
            herlaad()
          }
        })
        .catch((err: unknown) => {
          if (actueel) setActieFout(err instanceof Error ? err.message : 'Status van de reconciliatie ophalen mislukt.')
        })
    }, pollMs)
    return () => {
      actueel = false
      window.clearTimeout(t)
    }
  }, [run, pollMs, herlaad, toast])

  const zetParam = (naam: string, waarde: string | null) => {
    const p = new URLSearchParams(zoekParams)
    if (waarde) p.set(naam, waarde)
    else p.delete(naam)
    p.delete('administratie') // legacy-param opruimen zodra er gekozen wordt
    setZoekParams(p, { replace: true })
    setPagina(1)
  }

  const nuDraaien = async () => {
    setRunStartBezig(true)
    setActieFout(null)
    try {
      setRun(await startRun())
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Reconciliatie starten mislukt.')
    } finally {
      setRunStartBezig(false)
    }
  }

  const dagenOpslaan = async () => {
    const n = Number(gezienDagen.trim())
    if (!Number.isInteger(n) || n < 1 || n > 3650) {
      setActieFout("'Gezien' vervalt na een heel aantal dagen (1 t/m 3650).")
      return
    }
    setDagenBezig(true)
    setActieFout(null)
    try {
      const i = await zetInstelling(n)
      setGezienDagen(String(i.gezien_dagen))
      toast.meld(`'Gezien' vervalt voortaan na ${i.gezien_dagen} dagen.`)
      herlaad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Instelling opslaan mislukt.')
    } finally {
      setDagenBezig(false)
    }
  }

  const comboboxOpties = useMemo(
    () => [{ id: ALLE, naam: 'Alle administraties' }, ...(administraties ?? [])],
    [administraties],
  )
  const rijen = data?.rijen ?? []
  const paginas = Math.max(1, Math.ceil((data?.totaal ?? 0) / (data?.per_pagina ?? 25)))
  const runLoopt = run !== null && (run.status === 'wachtend' || run.status === 'bezig')
  const laatsteRun = data?.laatste_run ?? null

  /** Actie-kolom: precies één handeling per rij, plus eventueel de deep-link naar het stuk zelf. */
  const actieVoor = (r: BevindingDto) => {
    const kanReden = r.administratie_id !== null
    // Automatiserings-LET-OP (07-09 blok C): de handeling is de instelling herstellen — de deeplink wijst
    // naar de instellingenpagina, ook zonder administratie (platformbrede voorwaarde).
    const isAutomatisering = r.blok === 'automatisering'
    // 21-09: een automatiserings-LET-OP mét document (boek_wachtrij_gestrand) linkt naar het document, niet naar een instelling.
    const naarDocument = !isAutomatisering || typeof r.detail?.document_id === 'string'
    const deeplink = r.doel_pad ? (
      <Link
        to={r.doel_pad}
        className="btn secondary"
        aria-label={
          naarDocument
            ? `Naar het document van ${r.administratie_naam ?? 'deze bevinding'}`
            : `Naar de instelling van ${titelVan(r)}`
        }
      >
        {!naarDocument ? 'Naar de instelling →' : r.soort === 'let_op' && !isAutomatisering ? 'Naar de doorbelasting →' : 'Naar het document →'}
      </Link>
    ) : null

    // 23-09 (Peter 22-09): berichten in het postvak zonder verwerking → "Nu verwerken" start de intake-job van het kanaal.
    if (r.soort === 'afwijking' && isIntakePostvakVerschil(r)) {
      return (
        <NuVerwerkenActie
          bevinding={r}
          onGelukt={(melding) => {
            toast.meld(melding)
            herlaad()
          }}
        />
      )
    }

    // 24-09 (BUG activa-kaart BLOw): activum niet aangemaakt ná een mens-klik → "Opnieuw aanmaken" op de rij (zelfde
    // kaart-route, voorgevulde afschrijvingsrekening); 422 = de rekening kiezen op het controlescherm (deeplink).
    if (r.soort === 'afwijking' && isActivumAanmakenMislukt(r)) {
      return (
        <>
          <OpnieuwAanmakenActie
            bevinding={r}
            onGelukt={(melding, soort) => {
              toast.meld(melding, soort)
              herlaad()
            }}
          />{' '}
          {deeplink}
        </>
      )
    }

    // 21-09 (BUG rlz-boek-wachtrij): boeking hangt op "Wordt geboekt…" → "Opnieuw indienen" is de primaire handeling.
    if (isBoekWachtrijGestrand(r)) {
      return (
        <>
          <OpnieuwIndienenActie
            bevinding={r}
            onGelukt={(melding, soort) => {
              toast.meld(melding, soort)
              herlaad()
            }}
          />{' '}
          {deeplink}
        </>
      )
    }

    // A11 (07-09): extern document verdwenen → "Opnieuw boeken…" (herboek-mechanisme zonder tegenboeking) is de
    // primaire handeling; accepteren (Beheerder) blijft als tweede knop beschikbaar.
    if (r.soort === 'afwijking' && isVerdwenenDocument(r)) {
      const accepteren = () =>
        setRedenActie({
          bevinding: r,
          titel: 'Afwijking accepteren',
          beschrijving:
            'De bevinding blijft bewaard, maar telt niet meer mee als afwijking. Leg vast waaróm dit verschil klopt — de reden komt in het audit log.',
          bevestig: 'Accepteren',
          uitvoeren: (aid, reden) => accepteerBevinding(r.id, aid, reden),
          gelukt: 'Afwijking geaccepteerd.',
        })
      return (
        <>
          <OpnieuwBoekenActie
            bevinding={r}
            onGelukt={(melding) => {
              toast.meld(melding)
              herlaad()
            }}
            onAccepteren={isBeheerder && kanReden ? accepteren : undefined}
            isBeheerder={isBeheerder}
          />{' '}
          {/* Blok D (16-09): de mens verwijderde het stuk zélf in RLZ (dubbel/test) → één klik: acceptatie mét vaste
              reden + document naar 'afgevoerd als duplicaat' (Beheerder). */}
          {isBeheerder && kanReden && (
            <>
              <BewustVerwijderdActie
                bevinding={r}
                onGelukt={(melding) => {
                  toast.meld(melding)
                  herlaad()
                }}
              />{' '}
            </>
          )}
          {deeplink}
        </>
      )
    }
    // Peter 22-09: intussen buiten de module geboekt (document wacht nog op klant/IBAN/kantoor) → twee handelingen op de
    // rij: afwijzen als al geboekt (accordering ingetrokken) of toch verschillend — doorgaan.
    if (r.soort === 'afwijking' && isIntussenExternGeboekt(r) && r.administratie_id !== null) {
      const d = r.detail ?? {}
      return (
        <>
          <ExternGeboektActies
            compact
            administratieId={r.administratie_id}
            documentId={String(d.document_id)}
            kern={externGeboektKernUitBevinding(r)}
            bevindingId={r.id}
            leverancier={typeof d.leverancier_naam === 'string' ? d.leverancier_naam : null}
            factuurnummer={typeof d.factuurnummer === 'string' ? d.factuurnummer : null}
            onGelukt={(melding) => {
              toast.meld(melding)
              herlaad()
            }}
          />{' '}
          {deeplink}
        </>
      )
    }
    // RLZ-vorm 24-09 stap 4: geboekte doorbelasting zonder factuur-PDF (art. 35a) → één klik "Factuur-PDF herstellen"
    // (RLZ rendert opnieuw, cent-exacte toets, bijlage op beide kanten; nooit een herboeking).
    if (r.soort === 'afwijking' && isDoorbelastingFactuurPdfOntbreekt(r)) {
      return (
        <>
          <FactuurPdfHerstellenActie
            bevinding={r}
            onGelukt={(melding) => {
              toast.meld(melding)
              herlaad()
            }}
          />{' '}
          {deeplink}
        </>
      )
    }
    // Blok 1 bundelrun 24-09 (Vastly-batch 23-09): losse PDF die de tweeling is van een UBL-verkoopfactuur → één klik
    // "Bundelen" (PDF wordt beeld van de verkoopfactuur, PDF-document → samengevoegd; geboekt = óók RLZ-bijlage).
    if (r.soort === 'afwijking' && isUblPdfOngebundeld(r)) {
      return (
        <>
          <BundelenActie
            bevinding={r}
            onGelukt={(melding) => {
              toast.meld(melding)
              herlaad()
            }}
          />{' '}
          {deeplink}
        </>
      )
    }
    // Blok C (16-09 avond): kassarapport dat als inkoopfactuur in de werkvoorraad staat → één klik "Type wijzigen".
    if (r.soort === 'afwijking' && isKassarapportInWerkvoorraad(r)) {
      return (
        <>
          <TypeWijzigenKassarapportActie
            bevinding={r}
            onGelukt={(melding) => {
              toast.meld(melding)
              herlaad()
            }}
          />{' '}
          {deeplink}
        </>
      )
    }
    // Peter 16-09 (Van Boxtel): omzet die als inkoopfactuur geboekt is → "Herboeken als omzet…" is de primaire handeling.
    if (r.soort === 'afwijking' && isOmzetInInkoopstroom(r)) {
      return (
        <>
          <HerboekenAlsOmzetActie
            bevinding={r}
            onGelukt={(melding) => {
              toast.meld(melding)
              herlaad()
            }}
            isBeheerder={isBeheerder}
          />{' '}
          {deeplink}
        </>
      )
    }
    if (r.soort === 'afwijking') {
      return (
        <>
          {/* Blok 6 (08-09): mogelijk dubbel in RLZ — geen document in de app, geen RLZ-deeplink bekend: de
              handeling is beide boekstuknummers in Reeleezee openen; accepteren (Beheerder) blijft de tweede knop. */}
          {isRlzDubbel(r) && <RlzDubbelBoekstukken bevinding={r} />}
          {isBeheerder && kanReden ? (
            <Button
              variant="secundair"
              maat="klein"
              aria-label={`Afwijking accepteren: ${titelVan(r)}`}
              onClick={() =>
                setRedenActie({
                  bevinding: r,
                  titel: 'Afwijking accepteren',
                  beschrijving:
                    'De bevinding blijft bewaard, maar telt niet meer mee als afwijking. Leg vast waaróm dit verschil klopt — de reden komt in het audit log.',
                  bevestig: 'Accepteren',
                  uitvoeren: (aid, reden) => accepteerBevinding(r.id, aid, reden),
                  gelukt: 'Afwijking geaccepteerd.',
                })
              }
            >
              Accepteren…
            </Button>
          ) : (
            <span className="hint">Beheerder accepteert</span>
          )}{' '}
          {deeplink}
        </>
      )
    }
    if (r.soort === 'geaccepteerd') {
      // Blok D (16-09): terugweg van "Bewust verwijderd in RLZ" — document terug naar geboekt + acceptatie ingetrokken
      // (Beheerder, verplichte reden). Het gewone "Intrekken…" zou het document op afgevoerd laten staan.
      if (isBeheerder && kanReden && isBewustVerwijderdAcceptatie(r)) {
        const documentId = String(r.detail?.document_id)
        return (
          <Button
            variant="secundair"
            maat="klein"
            aria-label={`Bewust verwijderd terugdraaien: ${titelVan(r)}`}
            onClick={() =>
              setRedenActie({
                bevinding: r,
                titel: 'Bewust verwijderd terugdraaien',
                beschrijving:
                  "Het document gaat in de module terug naar 'geboekt' en de acceptatie wordt ingetrokken — de bevinding telt bij de volgende run weer mee. Leg vast waarom.",
                bevestig: 'Terugdraaien',
                uitvoeren: (aid, reden) => herstelBewustVerwijderd(documentId, aid, reden),
                gelukt: 'Teruggedraaid: document staat weer op geboekt, acceptatie ingetrokken.',
              })
            }
          >
            Terugdraaien…
          </Button>
        )
      }
      return isBeheerder && kanReden ? (
        <Button
          variant="secundair"
          maat="klein"
          aria-label={`Acceptatie intrekken: ${titelVan(r)}`}
          onClick={() =>
            setRedenActie({
              bevinding: r,
              titel: 'Acceptatie intrekken',
              beschrijving: 'De bevinding telt daarna weer mee als afwijking. Leg vast waarom je de acceptatie intrekt.',
              bevestig: 'Intrekken',
              uitvoeren: (aid, reden) => trekAcceptatieIn(r.id, aid, reden),
              gelukt: 'Acceptatie ingetrokken.',
            })
          }
        >
          Intrekken…
        </Button>
      ) : (
        <span className="hint">Beheerder trekt in</span>
      )
    }
    if (r.soort === 'let_op') {
      return (
        <>
          {kanReden && (
            <Button
              variant="secundair"
              maat="klein"
              aria-label={`Gezien: ${titelVan(r)}`}
              onClick={() =>
                setRedenActie({
                  bevinding: r,
                  titel: 'Melding als gezien markeren',
                  beschrijving:
                    "De melding verdwijnt tijdelijk uit 'aandacht nodig' en komt vanzelf terug als hij blijft staan. Leg vast wat je ermee gedaan hebt.",
                  bevestig: 'Gezien',
                  uitvoeren: (aid, reden) => markeerGezien(r.id, aid, reden),
                  gelukt: 'Melding als gezien gemarkeerd.',
                })
              }
            >
              Gezien…
            </Button>
          )}{' '}
          {deeplink}
        </>
      )
    }
    if (r.soort === 'gezien') {
      return kanReden ? (
        <button
          type="button"
          className="linkbtn"
          aria-label={`Toch tonen: ${titelVan(r)}`}
          onClick={() =>
            setRedenActie({
              bevinding: r,
              titel: 'Toch weer tonen',
              beschrijving: "De melding komt terug in 'aandacht nodig'. Leg vast waarom.",
              bevestig: 'Toch tonen',
              uitvoeren: (aid, reden) => gezienIntrekken(r.id, aid, reden),
              gelukt: 'Melding staat weer bij aandacht nodig.',
            })
          }
        >
          Toch tonen
        </button>
      ) : null
    }
    if (r.soort === 'fout') {
      return (
        <>
          <span className="hint">controleren: credentials/RLZ-bereikbaarheid</span> {deeplink}
        </>
      )
    }
    return <span className="hint">telt niet mee (uitgesloten administratie)</span>
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 style={{ margin: 0 }}>Inzicht › Reconciliatie</h1>
          <div className="hint" style={{ marginTop: 2 }}>
            Dagelijkse controle van de eigen boekingen tegen de werkelijke stand in Reeleezee — bank, documenten, omzet en
            doorbelasting, over al je administraties. Signaleren en vastleggen; wij muteren nooit iets in Reeleezee.
          </div>
        </div>
      </div>

      <div className="panel" data-testid="reconciliatie-paneel" style={{ padding: 0, overflow: 'hidden' }}>
        <div
          className="p-kop"
          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}
        >
          <h2 style={{ margin: 0, fontSize: 14.5 }}>Reconciliatie</h2>
          {data && (
            <>
              <Badge variant={data.tellers.afwijkingen > 0 ? 'danger' : 'warn'} data-testid="chip-afwijkingen">
                {data.tellers.afwijkingen} afwijkingen
              </Badge>
              <Badge variant="stil" data-testid="chip-let-op">
                {data.tellers.let_op} let-op
              </Badge>
              {(data.tellers.meten ?? 0) > 0 && (
                <Badge
                  variant="stil"
                  data-testid="chip-meten"
                  title="Bevindingssoorten in meting: tellen wél, vragen geen handeling en staan niet in de actiemail (pas na promotie door een Beheerder)."
                >
                  {data.tellers.meten} in meting
                </Badge>
              )}
              <Badge variant={data.tellers.fouten > 0 ? 'danger' : 'stil'} data-testid="chip-fouten">
                {data.tellers.fouten} fouten
              </Badge>
            </>
          )}
          <span style={{ marginLeft: 'auto' }} />
          <GroepFilter waarde={groepId || null} onWijzig={(id) => zetParam('groep_id', id)} />
          <div style={{ minWidth: 220 }}>
            <AdministratieCombobox
              label="Administratie"
              toonLabel={false}
              administraties={comboboxOpties}
              waarde={administratieId || ALLE}
              onWijzig={(id) => zetParam('administratie_id', id === ALLE ? null : id)}
              placeholder="Administratie: alle"
            />
          </div>
          <select
            aria-label="Soort"
            value={soort}
            onChange={(e) => zetParam('soort', e.target.value === 'aandacht' ? null : e.target.value)}
            style={{ width: 'auto' }}
          >
            {SOORT_FACETTEN.map((s) => (
              <option key={s} value={s}>
                Soort: {SOORT_LABEL[s]}
                {data ? ` (${data.facetten.soort[s] ?? 0})` : ''}
              </option>
            ))}
          </select>
          <input
            type="search"
            aria-label="Zoek bevinding"
            placeholder="🔍 zoek bevinding…"
            value={zoek}
            onChange={(e) => {
              setZoek(e.target.value)
              setPagina(1)
            }}
            style={{ width: 200, maxWidth: '100%' }}
          />
          {isBeheerder && (
            <Button variant="secundair" maat="klein" disabled={runStartBezig || runLoopt} onClick={() => void nuDraaien()}>
              ▶ Nu draaien
            </Button>
          )}
        </div>

        {run && (
          <div
            className="hint"
            role="status"
            data-testid="reconciliatie-stand"
            style={{ margin: 0, padding: '8px 18px', borderBottom: '1px solid var(--border)' }}
          >
            {runTekst(run)}
          </div>
        )}
        {/* Blok 5 (08-09, feedback Peter): het tellersblok "Automatiseringen" staat niet meer op dit werkscherm maar op
            Instellingen › Boeken platformbreed; hier blijven alleen de bevindingen MÉT handeling (LET-OP-rijen blok
            Automatisering dragen "Naar de instelling →"). */}
        {run?.status === 'fout' && (
          <div style={{ padding: '0 18px' }}>
            <FoutMelding
              melding="De reconciliatie-run is mislukt."
              detail={run.fout_reden}
              onOpnieuw={isBeheerder ? () => void nuDraaien() : undefined}
            />
          </div>
        )}
        {actieFout && (
          <div className="fout" style={{ margin: '10px 18px' }}>
            {actieFout}
          </div>
        )}
        {laadFout && <FoutMelding melding="De bevindingen konden niet geladen worden." detail={laadFout} onOpnieuw={herlaad} />}
        {data === null && !laadFout && <SkeletonRegels />}
        {data !== null && rijen.length === 0 && (
          <div className="hint" style={{ padding: '14px 18px' }} data-testid="reconciliatie-leeg">
            {soort !== 'aandacht' ? (
              `Geen bevindingen met soort "${SOORT_LABEL[soort]}".`
            ) : laatsteRun ? (
              `Geen bevindingen die aandacht nodig hebben — de laatste run van ${tijd(laatsteRun.afgerond_op ?? laatsteRun.aangevraagd_op)} was schoon.`
            ) : (
              <>
                Nog geen run. De reconciliatie draait elke nacht mee; daarna staat de uitkomst hier.{' '}
                {isBeheerder && (
                  <button type="button" className="linkbtn" onClick={() => void nuDraaien()} disabled={runStartBezig || runLoopt}>
                    Nu een run starten
                  </button>
                )}
              </>
            )}
          </div>
        )}
        {rijen.length > 0 && (
          <div className="tabel-scroll">
            <table data-testid="reconciliatie-tabel">
              <thead>
                <tr>
                  <th style={{ width: '18%' }}>Administratie</th>
                  <th style={{ width: 120 }}>Blok</th>
                  <th>Bevinding</th>
                  <th style={{ width: 80 }}>Sinds</th>
                  <th style={{ width: 260 }} />
                </tr>
              </thead>
              <tbody>
                {rijen.map((r) => (
                  <tr key={r.id} data-testid="reconciliatie-rij">
                    <td>
                      {r.administratie_id ? (
                        <Link to={`/?administratie=${r.administratie_id}`} className="text-primary no-underline hover:underline">
                          {r.administratie_naam ?? 'Administratie'}
                        </Link>
                      ) : (
                        <span className="hint">—</span>
                      )}
                    </td>
                    <td>{BLOK_LABEL[r.blok] ?? r.blok}</td>
                    <td>
                      <div data-testid="bevinding-titel">
                        <strong>{titelVan(r)}</strong>{' '}
                        {r.nieuw && (
                          <Badge variant="warn" data-testid="chip-nieuw">
                            nieuw
                          </Badge>
                        )}
                      </div>
                      {r.wat && <div data-testid="bevinding-wat">{r.wat}</div>}
                      {r.doe && (
                        <div className="hint" style={{ margin: 0 }} data-testid="bevinding-doe">
                          → {r.doe}
                        </div>
                      )}
                      {(r.details?.length ?? 0) > 0 && (
                        <details style={{ marginTop: 4 }} data-testid="bevinding-details">
                          <summary className="hint" style={{ cursor: 'pointer', fontSize: 11.5, margin: 0 }}>
                            details
                          </summary>
                          <dl style={{ margin: '4px 0 0', fontSize: 11.5, display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: '2px 10px' }}>
                            {r.details.map((d, i) => (
                              <Fragment key={`${d.label}-${i}`}>
                                <dt className="hint" style={{ margin: 0 }}>
                                  {d.label}
                                </dt>
                                <dd style={{ margin: 0, wordBreak: 'break-all' }}>
                                  <code style={{ fontSize: 11 }}>{d.waarde}</code>
                                </dd>
                              </Fragment>
                            ))}
                          </dl>
                        </details>
                      )}
                      {r.acceptatie && (
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                          geaccepteerd: {r.acceptatie.reden}
                          {r.acceptatie.geaccepteerd_door_naam ? ` · ${r.acceptatie.geaccepteerd_door_naam}` : ''} ·{' '}
                          {ddmm(r.acceptatie.geaccepteerd_op)}
                        </div>
                      )}
                      {r.gezien && (
                        <div className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                          gezien: {r.gezien.reden}
                          {r.gezien.gezien_door_naam ? ` · ${r.gezien.gezien_door_naam}` : ''} · {ddmm(r.gezien.gezien_op)} · komt terug
                          op {ddmm(r.gezien.vervalt_op)}
                        </div>
                      )}
                    </td>
                    <td>{ddmm(r.sinds)}</td>
                    <td className="acties" style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
                      {actieVoor(r)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && (
          <div
            className="voet hint"
            data-testid="reconciliatie-voet"
            style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}
          >
            <Button variant="ghost" maat="klein" aria-label="Vorige pagina" disabled={pagina <= 1} onClick={() => setPagina((p) => p - 1)}>
              ‹
            </Button>
            <span>
              {pagina} van {paginas}
            </span>
            <Button variant="ghost" maat="klein" aria-label="Volgende pagina" disabled={pagina >= paginas} onClick={() => setPagina((p) => p + 1)}>
              ›
            </Button>
            <span>
              · {data.totaal} {data.totaal === 1 ? 'bevinding' : 'bevindingen'} over {data.administraties_in_selectie}{' '}
              {data.administraties_in_selectie === 1 ? 'administratie' : 'administraties'}
            </span>
            {isBeheerder && (
              <label style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center', margin: 0 }}>
                'Gezien' vervalt na (dagen)
                <input
                  aria-label="'Gezien' vervalt na (dagen)"
                  inputMode="numeric"
                  value={gezienDagen}
                  onChange={(e) => setGezienDagen(e.target.value)}
                  placeholder="14"
                  style={{ width: 64 }}
                />
                <Button variant="secundair" maat="klein" disabled={dagenBezig || gezienDagen.trim() === ''} onClick={() => void dagenOpslaan()}>
                  Opslaan
                </Button>
              </label>
            )}
          </div>
        )}
      </div>

      {redenActie && (
        <RedenDialoog
          actie={redenActie}
          onSluiten={() => setRedenActie(null)}
          onGelukt={(tekst) => {
            setRedenActie(null)
            toast.meld(tekst)
            herlaad()
          }}
        />
      )}
    </div>
  )
}

/** Eén dialoog voor álle reden-acties (accepteren / intrekken / gezien / toch tonen): de reden is
 * verplicht en inhoudelijk (≥ 5 tekens, spiegel van de server) en gaat mee het audit log in. */
function RedenDialoog({
  actie,
  onSluiten,
  onGelukt,
}: {
  actie: RedenActie
  onSluiten: () => void
  onGelukt: (tekst: string) => void
}) {
  const [reden, setReden] = useState('')
  const [fout, setFout] = useState<string | null>(null)
  const [bezig, setBezig] = useState(false)
  const geldig = reden.trim().length >= REDEN_MINIMUM

  const bevestig = async () => {
    if (!geldig || actie.bevinding.administratie_id === null) return
    setBezig(true)
    setFout(null)
    try {
      await actie.uitvoeren(actie.bevinding.administratie_id, reden.trim())
      onGelukt(actie.gelukt)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Actie mislukt.')
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="reden-dialoog">
        <DialogTitle>{actie.titel}</DialogTitle>
        <DialogDescription>{actie.beschrijving}</DialogDescription>
        <div className="hint" style={{ marginTop: 0 }} data-testid="reden-dialoog-bevinding">
          <strong>{titelVan(actie.bevinding)}</strong>
          {actie.bevinding.wat ? <div>{actie.bevinding.wat}</div> : null}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void bevestig()
          }}
        >
          <FormField label="Reden" htmlFor="reconciliatie-reden">
            <textarea
              id="reconciliatie-reden"
              required
              rows={4}
              value={reden}
              onChange={(e) => setReden(e.target.value)}
              placeholder="Bijvoorbeeld: verschil komt uit de handmatige correctie van 3 september in Reeleezee."
              style={{ width: '100%', fontFamily: 'inherit', fontSize: 12.5 }}
            />
          </FormField>
          {!geldig && reden.trim() !== '' && <div className="hint">Geef een inhoudelijke reden (minimaal {REDEN_MINIMUM} tekens).</div>}
          {fout && <div className="fout">{fout}</div>}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={onSluiten} disabled={bezig}>
              Annuleren
            </Button>
            <Button type="submit" disabled={bezig || !geldig}>
              {bezig ? 'Bezig…' : actie.bevestig}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
