import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { ApiError } from '../api/client'
import { Breadcrumb } from '../werkvoorraad/Breadcrumb'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import { useMijnToegang } from '../auth/useMijnToegang'
import { Badge, Button, Dialog, DialogContent, DialogFooter, DialogTitle, FormField, Select } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { NieuwProjectModal } from '../projecten/NieuwProjectModal'
import { archiveerGebruiker, haalOpenWerkOp, nodigUit } from '../gebruikers/gebruikersApi'
import { TransportTab } from './TransportTab'
import { ConflictenPaneel } from './ConflictenPaneel'
import { DagEerstGrid, type KaartDropPayload } from './DagEerstGrid'
import { PerProjectWeergave } from './PerProjectWeergave'
import { PloegPaneel } from './PloegPaneel'
import { ProjectBalk } from './ProjectBalk'
import { afwezigTot, bouwDagKolommen, conflictWeekLabel, conflictenUniek, conflictenVanaf, conflictenVoorPaneel, conflictenVoorWeek, dagKort, parseKaartParam, poolStand, projectTegels, type Conflict, type DagKaart, type VulhandvatVoorbeeld } from './dagEerst'
import { isOngedaanToets, maakOngedaanStand, type OngedaanStand } from './planBulkOngedaan'
import { maakSleepPayload } from './useDagDrop'
import {
  bevestigConflict,
  haalPlanning,
  haalWerkopdrachten,
  isoWeekVan,
  maakReservering,
  maakWerkopdracht,
  parseWeekParam,
  planBulk,
  planToewijzing,
  schuifWeek,
  verplaatsToewijzing,
  verwijderReservering,
  verwijderToewijzing,
  weekDagen,
  weekNaarParam,
  wijzigWerkopdracht,
  zetDagdeel,
  zetWerkopdrachtDagOverride,
  type PlanningBulkItemDto,
  type PlanningProjectRijDto,
  type PlanningWeekDto,
  type WerkopdrachtDto,
  parseUrenFilter,
  type UrenFilter,
} from './planningApi'

/* Planning personeel V3 "DAG-EERST" (Peter 18-09, mockup planning-v3-dag-eerst.html = bouwnorm; vervangt het
 * project-rij-grid van 22/23-08 als BEWERKweergave): dagkolommen mét projectkaarten, projectbalk (alle actieve projecten,
 * slepen → reservering), conflictenbalk, vulhandvat (kaart + ploeg over de week), ploeg-paneel rechts, toggle "Per project"
 * als leesweergave. De pool, de week-URL, de werkopdrachten, de meldingen en de Transport-tab zijn ongewijzigd. De oude
 * beschrijving hieronder blijft als historie van de datalaag (één request levert álle actieve projecten).
 *
 * Planning-agenda steigerbouw (mockup planning-steigerbouw.html v3, besluit Peter 23-08 —
 * vervángt het 22-08-grid-filter "alleen projecten mét planning + zoekrij", dat gaf een leeg
 * grid waarin je niet kon beginnen): het grid toont ÁLLE actieve projecten in twee blokken —
 * mét planning deze week bovenaan (volle rijen, tellers), daaronder compact de overige
 * actieve projecten (lage rijen, direct beplanbaar via klik én drag & drop; zodra er iemand
 * gepland wordt schuift het project bij de verversing naar boven). Het filterveld boven het
 * grid versmalt beide blokken live (nummer/plaats/opdrachtgever); één request levert alles.
 * Vrij vooruit plannen (weeknavigatie + weekkiezer, onbegrensd — het hele jaar wordt vooruit
 * gevuld, besluit: géén week-kopieerknop); de URL draagt de week (?week=2026-W41) zodat een
 * stand deelbaar/herlaadbaar is. Slepen uit de pool = plannen (maakt de projectkoppeling
 * automatisch aan, besluit A); slepen tussen cellen = atomair verplaatsen; klik-alternatief:
 * cel aanklikken → persoon kiezen uit de pool (DnD is nooit de enige weg — touch/trackpad).
 * FAILSAFE: dezelfde persoon nooit 2× op dezelfde dag op hetzélfde project — de cel weigert
 * (rood), de backend-PK is het vangnet. Plannen ná de project-einddatum mag: zacht oranje
 * signaal op kaartje én rijkop, ook in het compacte blok (natuurlijke grens, geen blokkade).
 * De zijbalk toont de pool (geplande dagen; > 5 = zacht signaal, besluit C), de controle-
 * meldingen en de dubbele-dag-teller — uitsluitend kantoor. Toegang: module-recht
 * 'Meerwerk & urenstaten'. */

/** 21-09: de weekchip zegt eerlijk of de getoonde week verstreken/lopend is (deeplinks landen bewust op een oude week). */
function weekStand(vrijdag: string, maandag: string, vandaag: string): 'verstreken' | 'lopend' | 'komend' {
  if (vrijdag < vandaag) return 'verstreken'
  if (maandag <= vandaag) return 'lopend'
  return 'komend'
}

function dagLabel(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString('nl-NL', { day: 'numeric', month: 'numeric' })
}

function lokaleIsoDatum(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function tijdLabel(iso: string): string {
  return new Date(iso).toLocaleString('nl-NL', { day: 'numeric', month: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/* Werkopdracht-popup (mockup planning-werkopdracht-transport.html, akkoord 31-08): periode +
 * vrije tekst per project; meerdere/overlappende opdrachten per project; wijzigen = nieuwe
 * append-only versie — de historie (wie/wanneer) blijft zichtbaar onderin. */
function WerkopdrachtDialog({
  administratieId,
  projectId,
  projectNaam,
  onSluiten,
  onGewijzigd,
}: {
  administratieId: string
  projectId: string
  projectNaam: string
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const [lijst, setLijst] = useState<WerkopdrachtDto[] | null>(null)
  const [bewerk, setBewerk] = useState<WerkopdrachtDto | 'nieuw' | null>(null)
  const [van, setVan] = useState('')
  const [totEnMet, setTotEnMet] = useState('')
  const [tekst, setTekst] = useState('')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  function laadLijst() {
    haalWerkopdrachten(administratieId, projectId)
      .then((data) => {
        setLijst(data)
        // Geen opdracht = direct het nieuw-formulier; één opdracht = die open (mockup-flow).
        if (data.length === 0) begin('nieuw')
        else if (data.length === 1) begin(data[0])
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Laden mislukt'))
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(laadLijst, [administratieId, projectId])

  function begin(w: WerkopdrachtDto | 'nieuw') {
    setBewerk(w)
    setFout(null)
    if (w === 'nieuw') {
      setVan(lokaleIsoDatum(new Date()))
      setTotEnMet('')
      setTekst('')
    } else {
      setVan(w.van)
      setTotEnMet(w.tot_en_met)
      setTekst(w.tekst)
    }
  }

  async function opslaan() {
    if (!bewerk) return
    setBezig(true)
    setFout(null)
    try {
      if (bewerk === 'nieuw') {
        await maakWerkopdracht({ administratie_id: administratieId, project_id: projectId, van, tot_en_met: totEnMet, tekst })
      } else {
        await wijzigWerkopdracht(bewerk.groep_id, { administratie_id: administratieId, van, tot_en_met: totEnMet, tekst })
      }
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const historie = bewerk !== null && bewerk !== 'nieuw' ? bewerk.historie : []
  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>📋 Werkopdracht — {projectNaam}</DialogTitle>
        <p className="hint" style={{ marginTop: 0 }}>
          Zichtbaar voor iedereen die in de periode op dit project is ingepland (veld-app, alleen-lezen).
        </p>
        {lijst !== null && lijst.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
            {lijst.map((w) => (
              <button
                key={w.groep_id}
                className="linkbtn"
                style={{
                  border: `1px solid ${bewerk !== 'nieuw' && bewerk?.groep_id === w.groep_id ? 'var(--purple)' : 'var(--border)'}`,
                  borderRadius: 99,
                  padding: '2px 10px',
                  fontSize: 11.5,
                }}
                onClick={() => begin(w)}
              >
                📋 {w.tekst.slice(0, 32)}
                {w.tekst.length > 32 ? '…' : ''} · {dagLabel(w.van)}–{dagLabel(w.tot_en_met)}
              </button>
            ))}
            <button className="linkbtn" style={{ fontSize: 11.5 }} onClick={() => begin('nieuw')}>
              + nieuwe werkopdracht
            </button>
          </div>
        )}
        {bewerk !== null && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <FormField label="Van">
                <input type="date" value={van} onChange={(e) => setVan(e.target.value)} />
              </FormField>
              <FormField label="Tot en met">
                <input type="date" value={totEnMet} onChange={(e) => setTotEnMet(e.target.value)} />
              </FormField>
            </div>
            <FormField label="Opdracht (vrije tekst)">
              <textarea
                rows={5}
                value={tekst}
                onChange={(e) => setTekst(e.target.value)}
                placeholder="Bv. Montage fase 1 — zuidgevel eerst, daarna oost. Aanspreekpunt: …"
                style={{ resize: 'vertical', width: '100%' }}
              />
            </FormField>
            <p className="hint" style={{ fontSize: 11.5 }}>
              Meerdere werkopdrachten per project mogen (ook overlappend, bv. montage + demontage). Eén dag afwijken?
              Klik in het grid op de dagcel → &quot;afwijkende opdracht voor deze dag&quot;.
            </p>
            {historie.length > 0 && (
              <div style={{ borderTop: '1px dashed var(--border)', paddingTop: 8, fontSize: 11, color: 'var(--faint)', lineHeight: 1.6 }}>
                <b>Historie (append-only):</b>{' '}
                {historie.map((h) => `${tijdLabel(h.tijdstip)} ${h.omschrijving} door ${h.door_naam}`).join(' · ')} —
                alles terug te zien, niets overschreven.
              </div>
            )}
          </>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" maat="klein" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button maat="klein" onClick={() => void opslaan()} disabled={bezig || bewerk === null || !van || !totEnMet || !tekst.trim()}>
            Opslaan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* Dag-override (sparse — alleen die dag wint): afwijkende tekst op één (werkopdracht, datum). */
function DagOverrideDialog({
  administratieId,
  datum,
  rij,
  onSluiten,
  onGewijzigd,
}: {
  administratieId: string
  datum: string
  rij: PlanningProjectRijDto
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  // Binnen de periode van de dag zelf; meerdere overlappende opdrachten = keuze.
  const opties = rij.werkopdrachten.filter((w) => w.van <= datum && datum <= w.tot_en_met)
  const [groepId, setGroepId] = useState(opties[0]?.groep_id ?? '')
  const bestaand = (rij.werkopdracht_overrides[datum] ?? []).find((o) => o.groep_id === groepId)
  const [tekst, setTekst] = useState(bestaand?.tekst ?? '')
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      await zetWerkopdrachtDagOverride(groepId, { administratie_id: administratieId, datum, tekst })
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>📋 Afwijkende opdracht — {rij.project_naam ?? ''} · {dagLabel(datum)}</DialogTitle>
        <p className="hint" style={{ marginTop: 0 }}>
          Alleen deze dag wijkt af; de periode-tekst blijft de basis voor de overige dagen.
        </p>
        {opties.length > 1 && (
          <FormField label="Bij welke werkopdracht">
            <Select
              value={groepId}
              onChange={(e) => {
                setGroepId(e.target.value)
                const o = (rij.werkopdracht_overrides[datum] ?? []).find((x) => x.groep_id === e.target.value)
                setTekst(o?.tekst ?? '')
              }}
            >
              {opties.map((w) => (
                <option key={w.groep_id} value={w.groep_id}>
                  {w.tekst.slice(0, 60)}
                </option>
              ))}
            </Select>
          </FormField>
        )}
        <FormField label={`Afwijkende tekst voor ${dagLabel(datum)}`}>
          <textarea
            rows={4}
            value={tekst}
            onChange={(e) => setTekst(e.target.value)}
            placeholder="Bv. extra werk — traptoren bijplaatsen (meerwerk gemeld)"
            style={{ resize: 'vertical', width: '100%' }}
          />
        </FormField>
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" maat="klein" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button maat="klein" onClick={() => void opslaan()} disabled={bezig || !groepId || !tekst.trim()}>
            Opslaan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* "+ ZZP'er" in de planning-zijbalk (31-08): veldwerker aanmaken via het fijnmazige
 * veldwerkerbeheer-recht (of Beheerder) — uitsluitend veldrollen, scope = deze administratie. */
function NieuweVeldwerkerDialog({
  administratieId,
  onSluiten,
  onKlaar,
}: {
  administratieId: string
  onSluiten: () => void
  onKlaar: () => void
}) {
  const [naam, setNaam] = useState('')
  const [eMail, setEMail] = useState('')
  const [rol, setRol] = useState('zzper')
  const [uitnodigingLater, setUitnodigingLater] = useState(true)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  // D3 (01-09): ná aanmaken de BESTAANDE uitnodigingslink als QR tonen — scannen op de bouwplaats,
  // werkt samen met de pincode-activatieflow (universal link); zelfde link/geldigheid, audit ongewijzigd.
  const [qrLink, setQrLink] = useState<string | null>(null)

  async function aanmaken() {
    setBezig(true)
    setFout(null)
    try {
      const resultaat = await nodigUit({
        naam: naam.trim(),
        e_mail: eMail.trim(),
        rol,
        administratie_ids: [administratieId],
        uitnodiging_later: uitnodigingLater,
        bron: 'planning',
      })
      onKlaar()
      setQrLink(`${window.location.origin}/activeren?token=${encodeURIComponent(resultaat.token)}`)
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Aanmaken mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>👷 Veldwerker toevoegen</DialogTitle>
        {qrLink ? (
          <div data-testid="veldwerker-qr">
            <p className="hint" style={{ marginTop: 0 }}>
              {naam.trim()} is aangemaakt. Laat de veldwerker deze code scannen met de telefoon — dezelfde eenmalige
              activatielink als in de mail (72 uur geldig){uitnodigingLater ? '; de mail is nog niet verstuurd (later via Gebruikers & toegang)' : ''}.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
              <div style={{ background: '#fff', padding: 12, borderRadius: 10 }}>
                <QRCodeSVG value={qrLink} size={220} />
              </div>
              <code style={{ fontSize: 11, wordBreak: 'break-all', color: 'var(--muted)' }}>{qrLink}</code>
            </div>
            <DialogFooter>
              <Button maat="klein" onClick={onSluiten}>
                Klaar
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <>
        <p className="hint" style={{ marginTop: 0 }}>
          Alleen veldwerker-rollen, gekoppeld aan deze administratie (veldwerkerbeheer-recht, geaudit).
        </p>
        <FormField label="Naam">
          <input value={naam} onChange={(e) => setNaam(e.target.value)} placeholder="Bv. Milan Kovács" />
        </FormField>
        <FormField label="E-mailadres">
          <input type="email" value={eMail} onChange={(e) => setEMail(e.target.value)} placeholder="naam@voorbeeld.nl" />
        </FormField>
        <FormField label="Rol">
          <Select value={rol} onChange={(e) => setRol(e.target.value)}>
            <option value="zzper">ZZP&apos;er</option>
            <option value="uitvoerder">Uitvoerder</option>
            <option value="detacheerder">Detacheerder</option>
          </Select>
        </FormField>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12.5 }}>
          <input type="checkbox" checked={uitnodigingLater} onChange={(e) => setUitnodigingLater(e.target.checked)} />
          Uitnodiging later mailen (account bestaat alvast; mailen kan via Gebruikers &amp; toegang)
        </label>
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" maat="klein" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button maat="klein" onClick={() => void aanmaken()} disabled={bezig || !naam.trim() || !eMail.includes('@')}>
            Toevoegen
          </Button>
        </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

const WEERGAVE_SLEUTEL = 'planning-weergave'
const POOL_ZICHTBAAR = 100

function leesWeergave(): 'dag' | 'project' {
  try {
    return window.localStorage.getItem(WEERGAVE_SLEUTEL) === 'project' ? 'project' : 'dag'
  } catch {
    return 'dag'
  }
}

export function PlanningScreen() {
  const [searchParams, setSearchParams] = useSearchParams()
  const administratieId = searchParams.get('administratie')
  const { administraties } = useAdministraties()

  // De URL draagt de week (?week=2026-W41) — deelbaar/herlaadbaar; ongeldig → huidige week.
  const week = useMemo(
    () => parseWeekParam(searchParams.get('week')) ?? isoWeekVan(new Date()),
    [searchParams],
  )
  const [data, setData] = useState<PlanningWeekDto | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [geenRecht, setGeenRecht] = useState(false)
  const [moduleUit, setModuleUit] = useState(false)
  const [bezig, setBezig] = useState(false)
  // Projectbalk: zoekterm + klik-selectie (klik-alternatief voor slepen: project kiezen, dan dag aanklikken).
  const [filterTerm, setFilterTerm] = useState('')
  const [projectSelectie, setProjectSelectie] = useState<string | null>(null)
  // Dag-eerst: geselecteerde kaart (ploeg-paneel + handvat), opgelichte kaart (deeplink/conflictenbalk), weergave-toggle.
  const [geselecteerd, setGeselecteerd] = useState<string | null>(null)
  const [oplichten, setOplichten] = useState<string | null>(null)
  const [weergave, setWeergaveState] = useState<'dag' | 'project'>(leesWeergave)
  const [alleenVrij, setAlleenVrij] = useState(false)
  const [poolAlles, setPoolAlles] = useState(false)
  // Toast + ongedaan maken ná een bulk-actie (10 s; Cmd/Ctrl-Z).
  const [ongedaan, setOngedaan] = useState<OngedaanStand | null>(null)
  const ongedaanRef = useRef<OngedaanStand | null>(null)
  ongedaanRef.current = ongedaan
  // Werkopdrachten (31-08): popup per project + dag-override per (project, datum).
  const [woDialoog, setWoDialoog] = useState<{ projectId: string; projectNaam: string } | null>(null)
  const [overrideDialoog, setOverrideDialoog] = useState<{ rij: PlanningProjectRijDto; datum: string } | null>(null)
  // Blok C (31-08): "+ Project aanmaken" (B+P) en "+ ZZP'er"/archiveren (veldwerkerbeheer).
  const [nieuwProjectOpen, setNieuwProjectOpen] = useState(false)
  const [nieuweVeldwerkerOpen, setNieuweVeldwerkerOpen] = useState(false)
  const toegang = useMijnToegang()
  const magVeldwerkerbeheer = toegang?.is_beheerder === true || toegang?.heeft_veldwerkerbeheer_recht === true
  // Steigerbouw-run D1: tweede tab Transport naast Personeel (URL: ?tab=transport).
  const tab: 'personeel' | 'transport' = searchParams.get('tab') === 'transport' ? 'transport' : 'personeel'
  // 15-09 (Peter/Haci): urenstatus-filter bovenaan (chips, URL-param `uren`) — in v3 een KAARTfilter.
  const urenFilter: UrenFilter = parseUrenFilter(searchParams.get('uren'))
  function zetUrenFilter(f: UrenFilter) {
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        if (f === 'alle') p.delete('uren')
        else p.set('uren', f)
        return p
      },
      { replace: true },
    )
  }
  function zetTab(t: 'personeel' | 'transport') {
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        if (t === 'transport') p.set('tab', 'transport')
        else p.delete('tab')
        return p
      },
      { replace: true },
    )
  }
  function zetWeergave(w: 'dag' | 'project') {
    setWeergaveState(w)
    try {
      window.localStorage.setItem(WEERGAVE_SLEUTEL, w)
    } catch {
      /* opslag geblokkeerd — de stand leeft dan alleen in deze sessie */
    }
  }

  const administratieNaam = useMemo(
    () => (administraties ?? []).find((a) => a.id === administratieId)?.naam ?? 'Administratie',
    [administraties, administratieId],
  )

  function zetWeek(w: { jaar: number; weeknummer: number }) {
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        p.set('week', weekNaarParam(w))
        return p
      },
      { replace: true },
    )
  }

  function laad() {
    if (!administratieId) return
    setFout(null)
    haalPlanning(administratieId, week.jaar, week.weeknummer)
      .then(setData)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) setGeenRecht(true)
        else if (err instanceof ApiError && err.status === 409) setModuleUit(true)
        else setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
  }

  useEffect(() => {
    setData(null)
    setGeselecteerd(null)
    setProjectSelectie(null)
    laad()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administratieId, week.jaar, week.weeknummer])

  // Deeplink `?kaart=<project>|<datum>` (signalen, conflictenbalk-links): kaart selecteren + oplichten zodra de data er is.
  const kaartParam = parseKaartParam(searchParams.get('kaart'))
  useEffect(() => {
    if (!kaartParam || data === null) return
    setWeergaveState('dag')
    setGeselecteerd(kaartParam)
    setOplichten(kaartParam)
    const t = window.setTimeout(() => setOplichten(null), 2500)
    return () => window.clearTimeout(t)
  }, [kaartParam, data])

  // Toast verloopt ná 10 s; Cmd/Ctrl-Z = ongedaan maken zolang de toast staat.
  useEffect(() => {
    if (!ongedaan) return
    const t = window.setTimeout(() => setOngedaan(null), Math.max(0, ongedaan.verloopt_op - Date.now()))
    const toets = (e: KeyboardEvent) => {
      if (isOngedaanToets(e) && ongedaanRef.current) {
        e.preventDefault()
        void maakOngedaan()
      }
    }
    window.addEventListener('keydown', toets)
    return () => {
      window.clearTimeout(t)
      window.removeEventListener('keydown', toets)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ongedaan])

  if (!administratieId) {
    return <p className="hint">Geen administratie gekozen — open de planning vanaf de klantpagina.</p>
  }
  if (geenRecht) {
    return (
      <p className="hint">
        De planning hoort bij het module-recht &quot;Meerwerk &amp; urenstaten&quot; — een Beheerder kent dit toe
        onder Gebruikers &amp; toegang.
      </p>
    )
  }
  if (moduleUit) {
    return <p className="hint">Uren &amp; meerwerk (en daarmee de planning) is niet ingeschakeld voor deze administratie.</p>
  }

  // Ma–vr als kolommen; za/zo alleen als er iets op staat (inklapbaar in het grid).
  const alleDagen = weekDagen(week.jaar, week.weeknummer)
  const dagen = alleDagen.slice(0, 5)
  const werkdagen = dagen.map((d) => d.datum)
  const vandaagIso = lokaleIsoDatum(new Date())

  // V3: één request levert álle actieve projecten; de transformatie naar dagkolommen is puur (dagEerst.ts).
  const conflicten = data ? conflictenVoorWeek(data) : []
  // 21-09: het paneel toont alleen conflicten vanaf vandaag (verstreken dag = historie, wél in "Per project"); kaart-chips en
  // "Per project" houden álle conflicten. Label "deze week" alleen als de getoonde week de huidige is.
  const conflictGroepen = conflictenVoorPaneel(conflicten, vandaagIso)
  const verstrekenConflicten = conflictenUniek(conflicten).length - conflictenUniek(conflictenVanaf(conflicten, vandaagIso)).length
  const kolommen = data ? bouwDagKolommen(data, alleDagen, { urenFilter, conflicten }) : []
  const tegels = data ? projectTegels(data, dagen, filterTerm) : []
  const alleRijen = data?.projecten ?? []
  const aantalActief = alleRijen.filter((rij) => rij.is_actief).length
  const metPlanning = alleRijen.filter((rij) => Object.keys(rij.per_datum).length > 0).length
  const totaalMan = kolommen.filter((k) => werkdagen.includes(k.datum)).reduce((s, k) => s + k.aantal_man, 0)
  const geselecteerdeKaart: DagKaart | null = geselecteerd ? (kolommen.flatMap((k) => k.kaarten).find((k) => k.sleutel === geselecteerd) ?? null) : null

  async function actie(fn: () => Promise<unknown>) {
    setActieFout(null)
    setBezig(true)
    try {
      await fn()
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Actie mislukt — probeer het opnieuw.')
      laad() // grid verversen: de server-staat is leidend
    } finally {
      setBezig(false)
    }
  }

  function plan(gebruikerId: string, projectId: string, datum: string) {
    void actie(() => planToewijzing({ administratie_id: administratieId!, gebruiker_id: gebruikerId, project_id: projectId, datum }))
  }

  function reserveer(projectId: string, datum: string) {
    setProjectSelectie(null)
    void actie(() => maakReservering({ administratie_id: administratieId!, project_id: projectId, datum }))
  }

  /** Eén bulk-call (vulhandvat / ploeg / hele week) → toast mét ongedaan maken. */
  async function bulk(items: PlanningBulkItemDto[], bron: 'vulhandvat' | 'ploeg', toast: { soort: 'vulhandvat' | 'ploeg'; doelDatums?: string[]; verwijderen?: PlanningBulkItemDto[] }) {
    if (items.length === 0 && (toast.verwijderen ?? []).length === 0) return
    setActieFout(null)
    setBezig(true)
    try {
      let verwijderd = 0
      if ((toast.verwijderen ?? []).length > 0) {
        const r = await planBulk({ administratie_id: administratieId!, bron, verwijderen: true, items: toast.verwijderen! })
        verwijderd = r.resultaten.filter((x) => x.uitkomst !== 'overgeslagen').length
      }
      if (items.length > 0) {
        const resultaat = await planBulk({ administratie_id: administratieId!, bron, items })
        setOngedaan(maakOngedaanStand(resultaat, { soort: toast.soort, doelDatums: toast.doelDatums, verwijderd }))
      } else {
        setOngedaan(null)
      }
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Actie mislukt — probeer het opnieuw.')
      laad()
    } finally {
      setBezig(false)
    }
  }

  async function maakOngedaan() {
    const stand = ongedaanRef.current
    if (stand && (stand.herplaats ?? []).length > 0) {
      // 21-09: ongedaan ná een conflict-verwijdering = exact de verwijderde set terugplaatsen.
      setOngedaan(null)
      await actie(() => planBulk({ administratie_id: administratieId!, bron: 'ongedaan', correlatie_id: stand.correlatie_id, items: stand.herplaats! }))
      return
    }
    if (!stand || stand.aangemaakt.length === 0) {
      setOngedaan(null)
      return
    }
    setOngedaan(null)
    await actie(() =>
      planBulk({ administratie_id: administratieId!, bron: 'ongedaan', verwijderen: true, correlatie_id: stand.correlatie_id, items: stand.aangemaakt }),
    )
  }

  function spring(sleutel: string) {
    zetWeergave('dag')
    setGeselecteerd(sleutel)
    setOplichten(sleutel)
    window.setTimeout(() => setOplichten((h) => (h === sleutel ? null : h)), 2500)
  }

  function projectNaam(projectId: string): string {
    return alleRijen.find((r) => r.project_id === projectId)?.project_naam ?? projectId
  }

  /** Conflictenpaneel (21-09): "Houd ‹A›" = de andere kaart(en) van die persoon-dag weg via de bulkroute (bron conflict);
   * toast mét "Ongedaan maken" zet exact die set terug. */
  async function houdProject(c: Conflict, projectId: string) {
    if (!c.gebruiker_id) return
    const weg = c.project_ids.filter((p) => p !== projectId).map((p) => ({ gebruiker_id: c.gebruiker_id!, project_id: p, datum: c.datum }))
    await verwijderViaConflict(weg, `${c.naam ?? '?'} houdt ${projectNaam(projectId)} op ${dagKort(c.datum)}`)
  }

  async function verwijderConflictKaart(c: Conflict) {
    if (!c.gebruiker_id) return
    await verwijderViaConflict([{ gebruiker_id: c.gebruiker_id, project_id: c.project_id, datum: c.datum }], `${c.naam ?? '?'} van ${projectNaam(c.project_id)} gehaald op ${dagKort(c.datum)}`)
  }

  async function verwijderViaConflict(items: PlanningBulkItemDto[], tekst: string) {
    if (items.length === 0) return
    setActieFout(null)
    setBezig(true)
    try {
      const r = await planBulk({ administratie_id: administratieId!, bron: 'conflict', verwijderen: true, items })
      const verwijderd = r.resultaten.filter((x) => x.uitkomst !== 'overgeslagen').length
      // Ongedaan = de verwijderde set opnieuw plannen (bron ongedaan, zelfde correlatie-id).
      setOngedaan({
        correlatie_id: r.correlatie_id,
        aangemaakt: [],
        tekst: `${tekst} · ${verwijderd} kaart${verwijderd === 1 ? '' : 'en'} verwijderd`,
        aantal_conflicten: 0,
        conflict_sleutel: null,
        verloopt_op: Date.now() + 10_000,
        herplaats: r.aangemaakt,
      })
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Actie mislukt — probeer het opnieuw.')
      laad()
    } finally {
      setBezig(false)
    }
  }

  /** "Beide (halve dagen)…" (dubbel) / "Tóch plannen…" (afwezig): bewust houden mét reden — de rij verdwijnt tot de planning wijzigt. */
  function conflictAkkoord(c: Conflict, reden: string) {
    if (!c.gebruiker_id || (c.soort !== 'dubbel' && c.soort !== 'afwezig')) return
    void actie(() =>
      bevestigConflict({ administratie_id: administratieId!, gebruiker_id: c.gebruiker_id!, datum: c.datum, soort: c.soort as 'dubbel' | 'afwezig', reden, halve_dagen: c.soort === 'dubbel' }),
    )
  }

  function dropOpDag(datum: string, payload: KaartDropPayload) {
    if (payload.soort === 'project' && payload.projectId) reserveer(payload.projectId, datum)
    // Een persoon op de lege dagruimte: geen kaart als doel — de gebruiker sleept naar een kaart (hint in het grid).
  }

  function dropOpKaart(kaart: DagKaart, payload: KaartDropPayload) {
    if (payload.soort === 'project' && payload.projectId) {
      reserveer(payload.projectId, kaart.datum)
      return
    }
    if (!payload.gebruikerId) return
    if (kaart.ploeg.some((k) => k.gebruiker_id === payload.gebruikerId)) return // al op deze kaart — niets doen
    if (payload.soort === 'pool' || payload.kopieer) {
      plan(payload.gebruikerId, kaart.project_id, kaart.datum)
      return
    }
    if (payload.soort === 'kaart' && payload.projectId && payload.datum) {
      const bron = payload
      void actie(() =>
        verplaatsToewijzing({
          administratie_id: administratieId!,
          gebruiker_id: bron.gebruikerId!,
          van_project_id: bron.projectId!,
          van_datum: bron.datum!,
          naar_project_id: kaart.project_id,
          naar_datum: kaart.datum,
        }),
      )
    }
  }

  function handvatLoslaten(kaart: DagKaart, doelDatums: string[], voorbeeld: VulhandvatVoorbeeld) {
    void bulk(
      voorbeeld.items.map((i) => ({ gebruiker_id: i.gebruiker_id, project_id: i.project_id, datum: i.datum, dagdeel: 'heel' as const })),
      'vulhandvat',
      { soort: 'vulhandvat', doelDatums },
    )
    if (voorbeeld.items.length === 0 && voorbeeld.overgeslagen_datums.length > 0) {
      setActieFout(`Niets gekopieerd: ${kaart.project_naam ?? 'dit project'} staat al op ${voorbeeld.overgeslagen_datums.map((d) => dagKort(d)).join(', ')}.`)
    }
  }

  function ploegOpslaan(kaart: DagKaart, toevoegen: string[], verwijderen: string[]) {
    const items = toevoegen.map((g) => ({ gebruiker_id: g, project_id: kaart.project_id, datum: kaart.datum, dagdeel: 'heel' as const }))
    const weg = verwijderen.map((g) => ({ gebruiker_id: g, project_id: kaart.project_id, datum: kaart.datum }))
    void bulk(items, 'ploeg', { soort: 'ploeg', verwijderen: weg })
  }

  function ploegHeleWeek(kaart: DagKaart, gebruikerIds: string[]) {
    const rij = alleRijen.find((r) => r.project_id === kaart.project_id)
    const items: PlanningBulkItemDto[] = []
    const doel: string[] = []
    for (const d of werkdagen) {
      // Overslaan-regel: een dag waarop dit project al een (andere) kaart mét ploeg heeft, blijft zoals hij is.
      if (d !== kaart.datum && (rij?.per_datum[d] ?? []).length > 0) continue
      doel.push(d)
      for (const g of gebruikerIds) {
        if (d === kaart.datum && kaart.ploeg.some((k) => k.gebruiker_id === g)) continue
        items.push({ gebruiker_id: g, project_id: kaart.project_id, datum: d, dagdeel: 'heel' })
      }
    }
    void bulk(items, 'ploeg', { soort: 'vulhandvat', doelDatums: doel })
  }

  // Archiveren vanaf het poolkaartje (31-08): open-werk-waarschuwing mét aantallen (geen
  // blokkade, feedbackronde 26-08 punt 1), daarna het bestaande archiveer-endpoint.
  async function archiveerVeldwerker(gebruikerId: string, naam: string) {
    setActieFout(null)
    try {
      const werk = await haalOpenWerkOp(gebruikerId)
      const totaalOpen = werk.open_accorderingen + werk.weekstaten_ter_keuring + werk.eigen_open_weekstaten
      const waarschuwing =
        totaalOpen > 0
          ? `\n\nLet op: er staat nog open werk (${werk.eigen_open_weekstaten} open weekstaten, ${werk.weekstaten_ter_keuring} ter keuring, ${werk.open_accorderingen} accorderingen) — dat blijft staan.`
          : ''
      if (!window.confirm(`${naam} archiveren? Toegang gaat per direct dicht; niets wordt verwijderd.${waarschuwing}`)) {
        return
      }
      await archiveerGebruiker(gebruikerId)
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Archiveren mislukt — probeer het opnieuw.')
    }
  }

  const vandaagWeek = isoWeekVan(new Date())
  const pool = (data?.pool ?? []).filter((p) => !alleenVrij || poolStand(p, werkdagen, data?.afwezigheid) === 'vrij')
  const poolGetoond = poolAlles ? pool : pool.slice(0, POOL_ZICHTBAAR)

  return (
    <div>
      <div className="topbar">
        <div>
          <Breadcrumb
            stappen={[
              { label: 'Werkvoorraad', naar: '/' },
              { label: administratieNaam, naar: `/?administratie=${administratieId}` },
            ]}
            huidige="Planning"
          />
          <h1>Planning — {administratieNaam}</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }} data-testid="planning-subkop">
            Week {week.weeknummer} · {dagLabel(dagen[0].datum)} – {dagLabel(dagen[4].datum)}
            {weekStand(dagen[4].datum, dagen[0].datum, vandaagIso) !== 'komend' && (
              <>
                {' '}
                <Badge variant={weekStand(dagen[4].datum, dagen[0].datum, vandaagIso) === 'verstreken' ? 'stil' : 'info'} data-testid="week-stand">
                  {weekStand(dagen[4].datum, dagen[0].datum, vandaagIso) === 'verstreken' ? 'verstreken week' : 'lopende week'}
                </Badge>
              </>
            )}
            {data && ` · ${totaalMan} mensen gepland · ${metPlanning} ${metPlanning === 1 ? 'project' : 'projecten'} · ${aantalActief} actieve projecten`}
            {' · '}sleep een project naar een dag, klik een kaart voor de ploeg, trek de kaart met het handvat over de week
          </div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <Button
            variant="secundair"
            maat="klein"
            aria-label="Vorige week"
            onClick={() => zetWeek(schuifWeek(week.jaar, week.weeknummer, -1))}
          >
            ‹
          </Button>
          {/* Week-/datumkiezer: zelfde vorm als de URL-parameter (2026-W41) — vrij vooruit. */}
          <input
            type="week"
            aria-label="Weekkiezer"
            value={weekNaarParam(week)}
            onChange={(e) => {
              const gekozen = parseWeekParam(e.target.value)
              if (gekozen) zetWeek(gekozen)
            }}
            style={{
              background: 'var(--panel)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              color: 'var(--text)',
              font: 'inherit',
              fontWeight: 700,
              padding: '4px 8px',
            }}
          />
          <Button
            variant="secundair"
            maat="klein"
            aria-label="Volgende week"
            onClick={() => zetWeek(schuifWeek(week.jaar, week.weeknummer, 1))}
          >
            ›
          </Button>
          <Button
            variant="secundair"
            maat="klein"
            disabled={week.jaar === vandaagWeek.jaar && week.weeknummer === vandaagWeek.weeknummer}
            onClick={() => zetWeek(vandaagWeek)}
          >
            Vandaag
          </Button>
          {/* 31-08 blok C: "+ Project aanmaken" terug op /planning — bestaande projectmotor
              (naamconventie + RLZ-PUT), geen nieuw pad. 04-09 (0.2, besluit Peter): dezelfde
              rolpoort als de combobox-ingang, dus óók Boekhouding (`mag_project_aanmaken`). */}
          {toegang?.mag_project_aanmaken === true && (
            <Button maat="klein" title="Via de projectmotor — wordt óók in RLZ aangemaakt" onClick={() => setNieuwProjectOpen(true)}>
              + Project aanmaken
            </Button>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, margin: '0 0 14px', flexWrap: 'wrap', alignItems: 'center' }} role="tablist" aria-label="Planning-tabs">
        <Button variant={tab === 'personeel' ? 'primair' : 'secundair'} maat="klein" role="tab" aria-selected={tab === 'personeel'} onClick={() => zetTab('personeel')}>
          👷 Personeel
        </Button>
        <Button variant={tab === 'transport' ? 'primair' : 'secundair'} maat="klein" role="tab" aria-selected={tab === 'transport'} onClick={() => zetTab('transport')}>
          🚚 Transport
        </Button>
        {tab === 'personeel' && (
          /* V3: toggle Per dag (bewerken) / Per project (lezen) — stand per gebruiker onthouden. */
          <div className="plan-toggle" role="group" aria-label="Weergave" style={{ marginLeft: 8 }}>
            <button type="button" className={`linkbtn${weergave === 'dag' ? ' on' : ''}`} aria-pressed={weergave === 'dag'} onClick={() => zetWeergave('dag')} data-testid="weergave-dag">
              Per dag
            </button>
            <button type="button" className={`linkbtn${weergave === 'project' ? ' on' : ''}`} aria-pressed={weergave === 'project'} onClick={() => zetWeergave('project')} data-testid="weergave-project">
              Per project
            </button>
          </div>
        )}
        {tab === 'personeel' && (
          /* 15-09 (Peter/Haci): urenstatus-filter — chips, URL-param `uren`; in v3 een kaartfilter. */
          <div style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6, alignItems: 'center' }} role="group" aria-label="Urenstatus-filter">
            {(
              [
                ['alle', 'alle kaarten'],
                ['zonder', 'alleen zonder uren'],
                ['ongekeurd', 'alleen ongekeurd'],
              ] as const
            ).map(([f, label]) => (
              <Button
                key={f}
                variant={urenFilter === f ? 'primair' : 'secundair'}
                maat="klein"
                aria-pressed={urenFilter === f}
                data-testid={`uren-filter-${f}`}
                onClick={() => zetUrenFilter(f)}
              >
                {label}
              </Button>
            ))}
          </div>
        )}
      </div>

      {tab === 'transport' && administratieId && (
        <TransportTab administratieId={administratieId} week={week} dagen={dagen} filterTerm={filterTerm} setFilterTerm={setFilterTerm} />
      )}

      {tab === 'personeel' && fout && <FoutMelding melding="De planning kon niet geladen worden." detail={fout} onOpnieuw={laad} />}
      {tab === 'personeel' && actieFout && <div className="fout">{actieFout}</div>}

      {tab === 'personeel' && (
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px', gap: 16, alignItems: 'start' }}>
        <div style={{ minWidth: 0 }}>
          {data === null && !fout && (
            <div className="panel" aria-busy="true" style={{ padding: 16 }}>
              <span className="skeleton" style={{ width: '55%', marginBottom: 8 }} />
              <span className="skeleton" style={{ width: '40%' }} />
            </div>
          )}
          {data !== null && (
            <>
              <ProjectBalk tegels={tegels} zoek={filterTerm} onZoek={setFilterTerm} selectie={projectSelectie} onSelecteer={setProjectSelectie} />
              <ConflictenPaneel
                groepen={conflictGroepen}
                weekLabel={conflictWeekLabel(week, vandaagWeek)}
                verstrekenAantal={verstrekenConflicten}
                projectNaam={projectNaam}
                bezig={bezig}
                onSpring={spring}
                onHoud={(c, p) => void houdProject(c, p)}
                onVerwijder={(c) => void verwijderConflictKaart(c)}
                onAkkoord={conflictAkkoord}
              />
              {alleRijen.length === 0 && (
                <div className="panel">
                  <p className="hint" style={{ margin: 0 }}>
                    Geen actieve projecten in deze administratie — synchroniseer de projecten of activeer ze in RLZ.
                  </p>
                </div>
              )}
              {alleRijen.length > 0 && (
                <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
                  {weergave === 'dag' ? (
                    <DagEerstGrid
                      data={data}
                      kolommen={kolommen}
                      werkdagen={werkdagen}
                      vandaagIso={vandaagIso}
                      geselecteerd={geselecteerd}
                      oplichten={oplichten}
                      projectSelectie={projectSelectie}
                      onSelecteer={(k) => setGeselecteerd(k?.sleutel ?? null)}
                      onDagKlik={(datum) => {
                        if (projectSelectie) reserveer(projectSelectie, datum)
                        else setGeselecteerd(null)
                      }}
                      onDropOpDag={dropOpDag}
                      onDropOpKaart={dropOpKaart}
                      onVerwijderPersoon={(kaart, persoon) =>
                        void actie(() => verwijderToewijzing({ administratie_id: administratieId!, gebruiker_id: persoon.gebruiker_id, project_id: kaart.project_id, datum: kaart.datum }))
                      }
                      onDagdeel={(kaart, persoon) =>
                        void actie(() =>
                          zetDagdeel({ administratie_id: administratieId!, gebruiker_id: persoon.gebruiker_id, project_id: kaart.project_id, datum: kaart.datum, dagdeel: persoon.dagdeel === 'half' ? 'heel' : 'half' }),
                        )
                      }
                      onVerwijderReservering={(kaart) => kaart.reservering && void actie(() => verwijderReservering({ administratie_id: administratieId!, id: kaart.reservering!.id }))}
                      onWerkopdracht={(kaart) => {
                        const rij = alleRijen.find((r) => r.project_id === kaart.project_id)
                        if (rij && (rij.werkopdrachten ?? []).some((w) => w.van <= kaart.datum && kaart.datum <= w.tot_en_met)) setOverrideDialoog({ rij, datum: kaart.datum })
                        else setWoDialoog({ projectId: kaart.project_id, projectNaam: kaart.project_naam ?? '' })
                      }}
                      onHandvatLoslaten={handvatLoslaten}
                      onOpenWeekstaat={(persoon) => {
                        if (persoon.weekstaat_id) window.open(`/meerwerk?administratie=${administratieId}&weekstaat=${persoon.weekstaat_id}`, '_self')
                      }}
                    />
                  ) : (
                    <PerProjectWeergave kolommen={kolommen.filter((k) => werkdagen.includes(k.datum))} data={data} vandaagIso={vandaagIso} administratieId={administratieId} weekParam={weekNaarParam(week)} onNaarKaart={spring} onNaarPerDag={() => zetWeergave('dag')} />
                  )}
                </div>
              )}
            </>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, position: 'sticky', top: 16 }}>
          {data !== null && geselecteerdeKaart && !geselecteerdeKaart.gereserveerd && weergave === 'dag' && (
            <PloegPaneel
              key={geselecteerdeKaart.sleutel}
              data={data}
              kaart={geselecteerdeKaart}
              werkdagen={werkdagen}
              bezig={bezig}
              onSluiten={() => setGeselecteerd(null)}
              onOpslaan={(toevoegen, verwijderen) => ploegOpslaan(geselecteerdeKaart, toevoegen, verwijderen)}
              onToepassenHeleWeek={(ids) => ploegHeleWeek(geselecteerdeKaart, ids)}
              onWerkopdracht={() => {
                const rij = alleRijen.find((r) => r.project_id === geselecteerdeKaart.project_id)
                if (rij && (rij.werkopdrachten ?? []).some((w) => w.van <= geselecteerdeKaart.datum && geselecteerdeKaart.datum <= w.tot_en_met)) setOverrideDialoog({ rij, datum: geselecteerdeKaart.datum })
                else setWoDialoog({ projectId: geselecteerdeKaart.project_id, projectNaam: geselecteerdeKaart.project_naam ?? '' })
              }}
            />
          )}
          {data !== null && geselecteerdeKaart?.gereserveerd && weergave === 'dag' && (
            <div className="panel plan-paneel" data-testid="reservering-paneel">
              <h2 style={{ margin: 0, fontSize: 14 }}>{geselecteerdeKaart.project_naam ?? geselecteerdeKaart.project_id}</h2>
              <p className="hint">
                {dagKort(geselecteerdeKaart.datum)} · gereserveerd, nog geen ploeg — sleep personen uit de pool op de kaart; de reservering wordt dan de ploegkaart.
              </p>
              <Button variant="secundair" maat="klein" onClick={() => setGeselecteerd(null)}>
                Sluiten
              </Button>
            </div>
          )}
          <div className="panel">
            <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
              👷 ZZP&apos;ers &amp; uitvoerders <span style={{ fontWeight: 400, color: 'var(--faint)' }}>· sleep naar een kaart</span>
              {magVeldwerkerbeheer && (
                <Button
                  maat="klein"
                  style={{ marginLeft: 'auto' }}
                  title="Veldwerker toevoegen (veldwerkerbeheer-recht: alleen veldwerkers, eigen scope, geaudit)"
                  onClick={() => setNieuweVeldwerkerOpen(true)}
                >
                  + ZZP&apos;er
                </Button>
              )}
            </h2>
            {data !== null && data.pool.length > 0 && (
              <label style={{ display: 'flex', gap: 6, alignItems: 'center', fontSize: 11.5, marginBottom: 6 }}>
                <input type="checkbox" checked={alleenVrij} onChange={(e) => setAlleenVrij(e.target.checked)} data-testid="pool-alleen-vrij" />
                alleen vrij tonen
              </label>
            )}
            {data !== null && data.pool.length === 0 && (
              <p className="hint">Nog geen veldwerkers — nodig ze uit onder Gebruikers &amp; toegang.</p>
            )}
            {poolGetoond.map((p) => {
              const dagenGepland = Number(p.geplande_dagen)
              const stand = poolStand(p, werkdagen, data?.afwezigheid)
              const tot = stand === 'afwezig' ? afwezigTot(p, werkdagen, data?.afwezigheid) : null
              return (
                <div
                  key={p.gebruiker_id}
                  draggable={stand !== 'afwezig'}
                  data-testid={`pool-${p.gebruiker_id}`}
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = 'copy'
                    e.dataTransfer.setData('text/plain', maakSleepPayload('pool', p.gebruiker_id))
                  }}
                  className={`plan-pool-p${stand === 'afwezig' ? ' afw' : ''}`}
                  style={{ background: p.rol === 'uitvoerder' ? 'var(--ok-bg)' : 'var(--info-bg)' }}
                >
                  <b style={{ fontSize: 12 }}>{p.naam}</b>
                  {p.rol === 'uitvoerder' && <span style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 700 }}>uitv.</span>}
                  {/* Besluit C: > 5 geplande dagen per week = zacht signaal (kleurt oranje). V3: + vrij / afwezig t/m … */}
                  <span
                    style={{
                      marginLeft: 'auto',
                      fontSize: 10.5,
                      fontWeight: 600,
                      color: dagenGepland > 5 ? 'var(--warn)' : stand === 'vrij' ? 'var(--ok)' : 'var(--faint)',
                    }}
                    title={dagenGepland > 5 ? 'Meer dan 5 geplande dagen deze week (zacht signaal)' : undefined}
                  >
                    {stand === 'afwezig' && tot
                      ? `afwezig t/m ${dagKort(tot).split(' ')[1]}`
                      : `${dagenGepland.toLocaleString('nl-NL', { maximumFractionDigits: 1 })} dg${stand === 'vrij' ? ' · vrij' : ''}`}
                  </span>
                  {magVeldwerkerbeheer && (
                    <button
                      className="linkbtn"
                      title="Archiveren (nooit verwijderen; veldwerkerbeheer-recht, audit oud→nieuw)"
                      aria-label={`${p.naam} archiveren`}
                      style={{ fontSize: 10.5 }}
                      onClick={() => void archiveerVeldwerker(p.gebruiker_id, p.naam)}
                    >
                      🗑
                    </button>
                  )}
                </div>
              )
            })}
            {pool.length > poolGetoond.length && (
              <button type="button" className="linkbtn" style={{ fontSize: 11.5 }} onClick={() => setPoolAlles(true)} data-testid="pool-meer">
                … {pool.length - poolGetoond.length} meer
              </button>
            )}
            {magVeldwerkerbeheer && (
              <p className="hint" style={{ fontSize: 10.5, marginTop: 6 }}>
                🗑 op een kaartje = archiveren (nooit verwijderen) — via het veldwerkerbeheer-recht, geaudit.
              </p>
            )}
          </div>
          {data !== null && (data.wachtrisico ?? []).length > 0 && (
            <div className="panel">
              <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' }}>
                ⚠ Wachtrisico&apos;s <Badge variant="danger">{(data.wachtrisico ?? []).length}</Badge>
              </h2>
              {(data.wachtrisico ?? []).map((w, i) => (
                <div key={`wr-${i}`} style={{ display: 'flex', gap: 8, padding: '7px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                  <span aria-hidden>🟥</span>
                  <span>
                    <b>{w.project_naam ?? '?'} {dagLabel(w.datum)}</b> — ploeg gepland ({w.aantal_personen} man) maar de materiaallevering is niet
                    bevestigd ({w.samenvatting}).
                    <span style={{ display: 'block', color: 'var(--muted)', fontSize: 11 }}>
                      kruissignaal personeel × transport —{' '}
                      <button className="linkbtn" style={{ fontSize: 11 }} onClick={() => zetTab('transport')}>
                        naar Transport
                      </button>
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}
          {data !== null && (data.dubbele_dagen.length > 0 || data.buiten_planning.length > 0) && (
            <div className="panel">
              <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' }}>
                ⚠ Controle-meldingen{' '}
                <Badge variant="danger">{data.dubbele_dagen.length + data.buiten_planning.length}</Badge>
              </h2>
              {data.dubbele_dagen.map((m, i) => (
                <div key={`dd-${i}`} style={{ display: 'flex', gap: 8, padding: '7px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                  <span aria-hidden>🟥</span>
                  <span>
                    <b>{m.naam ?? '?'}</b> — dubbele dag {dagLabel(m.datum)}: uren op <b>{m.project_namen.join(' én ')}</b>,
                    planning dekte{' '}
                    {m.ongedekte_project_namen.length === m.project_namen.length
                      ? 'geen van de projecten'
                      : `niet: ${m.ongedekte_project_namen.join(', ')}`}
                    .
                    <span style={{ display: 'block', color: 'var(--muted)', fontSize: 11 }}>alleen zichtbaar voor kantoor</span>
                  </span>
                </div>
              ))}
              {data.buiten_planning.map((m, i) => (
                <div key={`bp-${i}`} style={{ display: 'flex', gap: 8, padding: '7px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                  <span aria-hidden>🟧</span>
                  <span>
                    <b>{m.naam ?? '?'}</b> — uren buiten planning: {dagLabel(m.datum)},{' '}
                    {Number(m.uren).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} u op {m.project_naam ?? '?'}.
                    <span style={{ display: 'block', color: 'var(--muted)', fontSize: 11 }}>
                      kleurt oranje bij de keuring — geen blokkade
                    </span>
                  </span>
                </div>
              ))}
            </div>
          )}

          {data !== null && data.dubbele_dag_tellers.length > 0 && (
            <div className="panel">
              <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)' }}>
                📊 Dubbele-dag-teller (intern)
              </h2>
              {data.dubbele_dag_tellers.map((t) => (
                <div key={t.gebruiker_id} style={{ display: 'flex', padding: '6px 0', borderBottom: '1px solid var(--border)', fontSize: 12 }}>
                  <span>{t.naam ?? '?'}</span>
                  <span style={{ marginLeft: 'auto' }}>
                    <Badge variant={t.aantal >= 3 ? 'danger' : 'warn'}>{t.aantal}× / 30 dgn</Badge>
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      )}

      {woDialoog && administratieId && (
        <WerkopdrachtDialog
          administratieId={administratieId}
          projectId={woDialoog.projectId}
          projectNaam={woDialoog.projectNaam}
          onSluiten={() => setWoDialoog(null)}
          onGewijzigd={laad}
        />
      )}
      {overrideDialoog && administratieId && (
        <DagOverrideDialog
          administratieId={administratieId}
          rij={overrideDialoog.rij}
          datum={overrideDialoog.datum}
          onSluiten={() => setOverrideDialoog(null)}
          onGewijzigd={laad}
        />
      )}
      {nieuwProjectOpen && administratieId && (
        <NieuwProjectModal
          administratieId={administratieId}
          onKlaar={() => {
            setNieuwProjectOpen(false)
            laad()
          }}
          onAnnuleren={() => setNieuwProjectOpen(false)}
        />
      )}
      {nieuweVeldwerkerOpen && administratieId && (
        <NieuweVeldwerkerDialog
          administratieId={administratieId}
          onSluiten={() => setNieuweVeldwerkerOpen(false)}
          onKlaar={laad}
        />
      )}

      {ongedaan && (
        <div className="plan-toast" role="status" data-testid="bulk-toast">
          <span>{ongedaan.tekst}</span>
          {(ongedaan.aangemaakt.length > 0 || (ongedaan.herplaats ?? []).length > 0) && (
            <button type="button" className="linkbtn" onClick={() => void maakOngedaan()} data-testid="ongedaan-maken">
              Ongedaan maken
            </button>
          )}
          {ongedaan.conflict_sleutel && (
            <button type="button" className="linkbtn" onClick={() => spring(ongedaan.conflict_sleutel!)}>
              Toon conflict
            </button>
          )}
          <button type="button" className="linkbtn" aria-label="Melding sluiten" onClick={() => setOngedaan(null)}>
            ✕
          </button>
        </div>
      )}

      <p className="hint" style={{ marginTop: 14, maxWidth: 980 }}>
        ℹ️ Zo grijpt de planning op de weekstaten in: uren op een gepland project/dag = groen · uren búíten de
        planning = oranje &quot;buiten planning&quot; bij de keuring (geen blokkade — invallen en omplannen blijft
        mogelijk) · twee projecten op één dag zónder planning-dekking = interne melding + teller per ZZP&apos;er,
        alleen zichtbaar voor kantoor. Per dag één kaart per project mét de ploeg als initialen (½ = halve dag); een kaart zonder ploeg is
        &quot;gereserveerd&quot;. Kopiëren over de week: kaart selecteren en het handvat slepen (stopt bij vrijdag). Vooruit plannen kan onbegrensd (het hele jaar wordt vooruit gevuld); plannen ná
        de einddatum van een project mag en kleurt oranje.
      </p>
    </div>
  )
}
