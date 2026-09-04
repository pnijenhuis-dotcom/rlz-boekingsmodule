import { useEffect, useMemo, useState } from 'react'
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
import {
  haalPlanning,
  haalWerkopdrachten,
  isoWeekVan,
  maakWerkopdracht,
  parseWeekParam,
  planToewijzing,
  schuifWeek,
  verplaatsToewijzing,
  verwijderToewijzing,
  weekDagen,
  weekNaarParam,
  wijzigWerkopdracht,
  zetDagdeel,
  zetWerkopdrachtDagOverride,
  type PlanningKaartDto,
  type PlanningProjectRijDto,
  type PlanningWeekDto,
  type WerkopdrachtDto,
} from './planningApi'

/* Planning-agenda steigerbouw (mockup planning-steigerbouw.html v3, besluit Peter 23-08 —
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

interface Sleep {
  gebruikerId: string
  naam: string | null
  bron: 'pool' | { projectId: string; datum: string }
}

function dagLabel(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString('nl-NL', { day: 'numeric', month: 'numeric' })
}

function lokaleIsoDatum(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function initialen(naam: string | null): string {
  if (!naam) return '?'
  return naam
    .split(/\s+/)
    .map((d) => d[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()
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
  const [sleep, setSleep] = useState<Sleep | null>(null)
  const [dragOver, setDragOver] = useState<string | null>(null) // celkey "project|datum"
  const [weigerCel, setWeigerCel] = useState<string | null>(null) // failsafe-flits (rood)
  const [kiesCel, setKiesCel] = useState<string | null>(null) // klik-alternatief: persoon kiezen
  // Filterveld boven het grid: versmalt beide blokken live (client-side — één request).
  const [filterTerm, setFilterTerm] = useState('')
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
    setKiesCel(null)
    laad()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administratieId, week.jaar, week.weeknummer])

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

  // Mockup: ma–vr als kolommen (weekendwerk loopt via de weekstaten, niet via de planning).
  const dagen = weekDagen(week.jaar, week.weeknummer).slice(0, 5)
  const vandaagIso = lokaleIsoDatum(new Date())

  // Grid-rijen (v3): de server levert ÁLLE actieve projecten (mét planning gevuld) in één
  // request. Splitsing in twee blokken op planning; het filter versmalt beide blokken live
  // op nummer/plaats (projectnaam) én opdrachtgever. Tellingen over de ongefilterde stand.
  const alleRijen = data?.projecten ?? []
  const term = filterTerm.trim().toLowerCase()
  const past = (rij: PlanningProjectRijDto) =>
    term === '' || `${rij.project_naam ?? ''} ${rij.opdrachtgever ?? ''}`.toLowerCase().includes(term)
  const metPlanning = alleRijen.filter((rij) => Object.keys(rij.per_datum).length > 0)
  const zonderPlanning = alleRijen.filter((rij) => Object.keys(rij.per_datum).length === 0)
  const bovenblok = metPlanning.filter(past)
  const onderblok = zonderPlanning.filter(past)
  const aantalActief = alleRijen.filter((rij) => rij.is_actief).length

  async function actie(fn: () => Promise<void>) {
    setActieFout(null)
    try {
      await fn()
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Actie mislukt — probeer het opnieuw.')
      laad() // grid verversen: de server-staat is leidend
    }
  }

  function plan(gebruikerId: string, projectId: string, datum: string) {
    void actie(() =>
      planToewijzing({
        administratie_id: administratieId!,
        gebruiker_id: gebruikerId,
        project_id: projectId,
        datum,
      }),
    )
  }

  function weiger(celKey: string) {
    setWeigerCel(celKey)
    window.setTimeout(() => setWeigerCel(null), 700)
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

  function kaartenIn(projectId: string, datum: string): PlanningKaartDto[] {
    return alleRijen.find((p) => p.project_id === projectId)?.per_datum[datum] ?? []
  }

  function drop(projectId: string, datum: string) {
    const celKey = `${projectId}|${datum}`
    setDragOver(null)
    if (!sleep || !administratieId) return
    const huidige = sleep
    setSleep(null)
    // FAILSAFE (besluit 22-08): zelfde persoon max 1× per project per dag — de cel weigert
    // (rode flits); de samengestelde PK in de backend is het harde vangnet.
    const cel = kaartenIn(projectId, datum)
    const zelfdeCel =
      typeof huidige.bron === 'object' && huidige.bron.projectId === projectId && huidige.bron.datum === datum
    if (!zelfdeCel && cel.some((k) => k.gebruiker_id === huidige.gebruikerId)) {
      weiger(celKey)
      return
    }
    if (huidige.bron === 'pool') {
      plan(huidige.gebruikerId, projectId, datum)
    } else if (!zelfdeCel) {
      const bron = huidige.bron
      void actie(() =>
        verplaatsToewijzing({
          administratie_id: administratieId,
          gebruiker_id: huidige.gebruikerId,
          van_project_id: bron.projectId,
          van_datum: bron.datum,
          naar_project_id: projectId,
          naar_datum: datum,
        }),
      )
    }
  }

  function Kaart({
    kaart,
    projectId,
    datum,
    naEinddatum,
  }: {
    kaart: PlanningKaartDto
    projectId: string
    datum: string
    naEinddatum: boolean
  }) {
    return (
      <div
        draggable
        title={naEinddatum ? 'Gepland ná de einddatum van het project (zacht signaal, geen blokkade)' : undefined}
        onDragStart={(e) => {
          e.dataTransfer.effectAllowed = 'move'
          e.dataTransfer.setData('text/plain', kaart.gebruiker_id)
          setSleep({ gebruikerId: kaart.gebruiker_id, naam: kaart.naam, bron: { projectId, datum } })
        }}
        onDragEnd={() => setSleep(null)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          background: naEinddatum ? 'var(--warn-bg)' : kaart.rol === 'uitvoerder' ? 'var(--ok-bg)' : 'var(--info-bg)',
          border: naEinddatum ? '1px solid var(--warn)' : '1px solid var(--border)',
          borderRadius: 9,
          padding: '4px 8px',
          fontSize: 11.5,
          marginBottom: 5,
          cursor: 'grab',
          userSelect: 'none',
        }}
      >
        <span
          aria-hidden
          style={{
            width: 20,
            height: 20,
            borderRadius: 99,
            background: 'var(--panel)',
            border: '1px solid var(--border)',
            display: 'grid',
            placeItems: 'center',
            fontSize: 9.5,
            fontWeight: 800,
            color: 'var(--primary)',
            flexShrink: 0,
          }}
        >
          {initialen(kaart.naam)}
        </span>
        <b style={{ fontSize: 12 }}>{kaart.naam ?? '?'}</b>
        {kaart.rol === 'uitvoerder' && <span style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 700 }}>uitv.</span>}
        {naEinddatum && (
          <span aria-label="ná projecteinddatum" style={{ fontSize: 10, color: 'var(--warn)', fontWeight: 700 }}>
            ⚠
          </span>
        )}
        <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 4 }}>
          <button
            className="linkbtn"
            title={kaart.dagdeel === 'half' ? 'Nu ½ dag — maak hele dag' : 'Hele dag — maak ½ dag'}
            style={{ fontSize: 10.5, fontWeight: 700 }}
            onClick={() =>
              void actie(() =>
                zetDagdeel({
                  administratie_id: administratieId!,
                  gebruiker_id: kaart.gebruiker_id,
                  project_id: projectId,
                  datum,
                  dagdeel: kaart.dagdeel === 'half' ? 'heel' : 'half',
                }),
              )
            }
          >
            {kaart.dagdeel === 'half' ? '½' : '1'}
          </button>
          <button
            className="linkbtn"
            title="Uit de planning halen"
            aria-label={`${kaart.naam ?? 'persoon'} uit de planning halen`}
            style={{ fontSize: 10.5 }}
            onClick={() =>
              void actie(() =>
                verwijderToewijzing({
                  administratie_id: administratieId!,
                  gebruiker_id: kaart.gebruiker_id,
                  project_id: projectId,
                  datum,
                }),
              )
            }
          >
            ✕
          </button>
        </span>
      </div>
    )
  }

  // Eén projectrij, gedeeld door beide blokken. compact = project zónder planning deze week
  // (lage rij, alleen nummer/plaats + opdrachtgever in de rijkop) — de cellen zijn identiek
  // en direct beplanbaar via klik én drag & drop; ná het plannen ververst het grid en schuift
  // het project naar het bovenste blok. Bewust een render-functie (geen component): met 68
  // projecten zou een per-render nieuw componenttype elke keer de hele subtree remounten.
  function renderRij(rij: PlanningProjectRijDto, compact: boolean) {
    const rijNaEinddatum = rij.looptijd_tot !== null && dagen[0].datum > rij.looptijd_tot
    // Defensief: een oudere (gecachete) response zonder werkopdracht-velden mag het grid
    // nooit breken — de chip blijft dan gewoon weg.
    const werkopdrachten = rij.werkopdrachten ?? []
    const overrides = rij.werkopdracht_overrides ?? {}
    return (
      <tr key={rij.project_id} className={compact ? 'plan-compact' : undefined}>
        <th style={{ verticalAlign: 'top', textAlign: 'left' }}>
          {rij.project_naam ?? rij.project_id}
          <div style={{ fontWeight: 400, fontSize: 10.5, color: 'var(--muted)', marginTop: 2 }}>
            {[rij.opdrachtgever, rij.soort_werk, rij.looptijd_tot ? `t/m ${dagLabel(rij.looptijd_tot)}` : null]
              .filter(Boolean)
              .join(' · ')}
            {compact && rijNaEinddatum && (
              <b style={{ color: 'var(--warn)', fontWeight: 700 }}> ⚠ ná einddatum</b>
            )}
          </div>
          {!compact && rijNaEinddatum && (
            <div style={{ fontWeight: 600, fontSize: 10.5, color: 'var(--warn)', marginTop: 3 }}>
              ⚠ deze week valt ná de einddatum
            </div>
          )}
          {!compact && rij.week_man > 0 && (
            <div style={{ marginTop: 5 }}>
              <Badge variant="info">deze week: {rij.week_man} man</Badge>
            </div>
          )}
          {/* Werkopdracht-chip + ⊕ (31-08): chip = uitklappen/wijzigen, ⊕ = toevoegen. */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 5, flexWrap: 'wrap' }}>
            {werkopdrachten.length > 0 && (
              <button
                className="linkbtn"
                title={werkopdrachten
                  .map((w) => `${dagLabel(w.van)} t/m ${dagLabel(w.tot_en_met)}: ${w.tekst}`)
                  .join('\n')}
                aria-label={`Werkopdracht ${rij.project_naam ?? ''}`}
                onClick={() => setWoDialoog({ projectId: rij.project_id, projectNaam: rij.project_naam ?? '' })}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 5,
                  maxWidth: '100%',
                  fontSize: 10.5,
                  fontWeight: 600,
                  color: 'var(--purple)',
                  background: 'var(--purple-bg)',
                  border: '1px solid var(--border)',
                  borderRadius: 99,
                  padding: '2px 9px',
                }}
              >
                📋{' '}
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {werkopdrachten[0].tekst}
                </span>
                {werkopdrachten.length > 1 && <b>+{werkopdrachten.length - 1}</b>}
              </button>
            )}
            <button
              className="linkbtn"
              title="Werkopdracht toevoegen"
              aria-label={`Werkopdracht toevoegen voor ${rij.project_naam ?? ''}`}
              onClick={() => setWoDialoog({ projectId: rij.project_id, projectNaam: rij.project_naam ?? '' })}
              style={{
                display: 'inline-grid',
                placeItems: 'center',
                width: 18,
                height: 18,
                borderRadius: 99,
                border: '1px dashed var(--faint)',
                color: 'var(--faint)',
                fontSize: 12,
              }}
            >
              +
            </button>
          </div>
        </th>
        {dagen.map((d) => {
          const celKey = `${rij.project_id}|${d.datum}`
          const kaarten = rij.per_datum[d.datum] ?? []
          const naEinddatum = rij.looptijd_tot !== null && d.datum > rij.looptijd_tot
          // De persoon-kiezer alleen berekenen voor de éne open cel (68 rijen × 5 dagen).
          const kiesbaar =
            kiesCel === celKey
              ? (data?.pool ?? []).filter((p) => !kaarten.some((k) => k.gebruiker_id === p.gebruiker_id))
              : []
          return (
            <td
              key={d.datum}
              data-testid={`cel-${celKey}`}
              className={`plan-cel${d.datum === vandaagIso ? ' plan-vandaag' : ''}`}
              title="Klik om een persoon te plannen"
              onClick={(e) => {
                // Klik-alternatief voor DnD: alleen op de lege celruimte zelf
                // (kliks op kaartjes/kiezer raken de td niet als target).
                if (e.target === e.currentTarget) setKiesCel((h) => (h === celKey ? null : celKey))
              }}
              onDragEnter={(e) => e.preventDefault()}
              onDragOver={(e) => {
                e.preventDefault()
                e.dataTransfer.dropEffect = sleep?.bron === 'pool' ? 'copy' : 'move'
                setDragOver(celKey)
              }}
              onDragLeave={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                  setDragOver((h) => (h === celKey ? null : h))
                }
              }}
              onDrop={(e) => {
                e.preventDefault()
                drop(rij.project_id, d.datum)
              }}
              style={{
                padding: 5,
                verticalAlign: 'top',
                outline:
                  weigerCel === celKey
                    ? '2px solid var(--danger)'
                    : dragOver === celKey
                      ? '2px dashed var(--primary)'
                      : undefined,
                outlineOffset: -3,
                background: dragOver === celKey ? 'var(--accent-bg)' : undefined,
              }}
            >
              {/* Dag-override (31-08): alleen deze dag wijkt de werkopdracht af — klik = wijzigen. */}
              {(overrides[d.datum] ?? []).map((o) => (
                <button
                  key={o.groep_id}
                  className="linkbtn"
                  title="Alleen deze dag wijkt de werkopdracht af — klik om te wijzigen"
                  onClick={() => setOverrideDialoog({ rij, datum: d.datum })}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 5,
                    width: '100%',
                    textAlign: 'left',
                    background: 'var(--purple-bg)',
                    border: '1px dashed var(--purple)',
                    borderRadius: 8,
                    padding: '4px 7px',
                    fontSize: 10.5,
                    color: 'var(--purple)',
                    marginBottom: 5,
                    lineHeight: 1.35,
                  }}
                >
                  📋{' '}
                  <span>
                    <b>{d.naam} afwijkend:</b> {o.tekst}
                  </span>
                </button>
              ))}
              {kaarten.map((k) => (
                <Kaart
                  key={k.gebruiker_id}
                  kaart={k}
                  projectId={rij.project_id}
                  datum={d.datum}
                  naEinddatum={naEinddatum}
                />
              ))}
              {kiesCel === celKey && (
                <div
                  style={{
                    background: 'var(--panel)',
                    border: '1px solid var(--border)',
                    borderRadius: 9,
                    boxShadow: 'var(--schaduw, 0 4px 16px rgba(0,0,0,.12))',
                    fontSize: 12,
                    marginTop: 2,
                    padding: 6,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                    <b style={{ fontSize: 11 }}>Plan op {dagLabel(d.datum)}</b>
                    <button
                      className="linkbtn"
                      aria-label="Kiezer sluiten"
                      style={{ marginLeft: 'auto' }}
                      onClick={() => setKiesCel(null)}
                    >
                      ✕
                    </button>
                  </div>
                  {kiesbaar.length === 0 && <p className="hint" style={{ margin: 0 }}>Iedereen staat al in deze cel.</p>}
                  {kiesbaar.map((p) => (
                    <button
                      key={p.gebruiker_id}
                      className="linkbtn"
                      style={{ display: 'block', padding: '3px 4px', textAlign: 'left', width: '100%' }}
                      onClick={() => {
                        setKiesCel(null)
                        plan(p.gebruiker_id, rij.project_id, d.datum)
                      }}
                    >
                      {p.naam}
                      {p.rol === 'uitvoerder' ? ' · uitv.' : ''}
                    </button>
                  ))}
                  {/* Dag-override via de dagcel (31-08) — alleen als er hier een opdracht loopt. */}
                  {werkopdrachten.some((w) => w.van <= d.datum && d.datum <= w.tot_en_met) && (
                    <button
                      className="linkbtn"
                      style={{
                        display: 'block',
                        padding: '3px 4px',
                        textAlign: 'left',
                        width: '100%',
                        color: 'var(--purple)',
                        borderTop: '1px dashed var(--border)',
                        marginTop: 3,
                      }}
                      onClick={() => {
                        setKiesCel(null)
                        setOverrideDialoog({ rij, datum: d.datum })
                      }}
                    >
                      📋 afwijkende opdracht voor deze dag…
                    </button>
                  )}
                </div>
              )}
            </td>
          )
        })}
      </tr>
    )
  }

  const vandaagWeek = isoWeekVan(new Date())

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
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Week {week.weeknummer} · {dagLabel(dagen[0].datum)} – {dagLabel(dagen[4].datum)} · álle actieve projecten
            (mét planning bovenaan) · sleep een persoon naar een project-dag, of klik een cel om te plannen
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
          {/* 31-08 blok C: "+ Project aanmaken" terug op /planning voor B+P — bestaande
              projectmotor (naamconventie + RLZ-PUT), geen nieuw pad. */}
          {toegang?.is_beheerder_of_bp === true && (
            <Button maat="klein" title="Via de projectmotor — wordt óók in RLZ aangemaakt" onClick={() => setNieuwProjectOpen(true)}>
              + Project aanmaken
            </Button>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, margin: '0 0 14px' }} role="tablist" aria-label="Planning-tabs">
        <Button variant={tab === 'personeel' ? 'primair' : 'secundair'} maat="klein" role="tab" aria-selected={tab === 'personeel'} onClick={() => zetTab('personeel')}>
          👷 Personeel
        </Button>
        <Button variant={tab === 'transport' ? 'primair' : 'secundair'} maat="klein" role="tab" aria-selected={tab === 'transport'} onClick={() => zetTab('transport')}>
          🚚 Transport
        </Button>
      </div>

      {tab === 'transport' && administratieId && (
        <TransportTab administratieId={administratieId} week={week} dagen={dagen} filterTerm={filterTerm} setFilterTerm={setFilterTerm} />
      )}

      {tab === 'personeel' && fout && <FoutMelding melding="De planning kon niet geladen worden." detail={fout} onOpnieuw={laad} />}
      {tab === 'personeel' && actieFout && <div className="fout">{actieFout}</div>}

      {tab === 'personeel' && (
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px', gap: 16, alignItems: 'start' }}>
        <div className="panel" style={{ padding: 0, overflow: 'hidden' }}>
          {data === null && !fout && (
            <div aria-busy="true" style={{ padding: 16 }}>
              <span className="skeleton" style={{ width: '55%', marginBottom: 8 }} />
              <span className="skeleton" style={{ width: '40%' }} />
            </div>
          )}
          {data !== null && (
            <>
              {/* Filter (client-side, live) + telling — mockup v3. */}
              <div
                style={{
                  alignItems: 'center',
                  borderBottom: '1px solid var(--border)',
                  display: 'flex',
                  flexWrap: 'wrap',
                  gap: 10,
                  padding: '10px 12px',
                }}
              >
                <input
                  type="search"
                  aria-label="Filter projecten"
                  placeholder="Filter projecten… (nummer, plaats of opdrachtgever)"
                  value={filterTerm}
                  onChange={(e) => setFilterTerm(e.target.value)}
                  style={{
                    background: 'var(--panel-2)',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    color: 'var(--text)',
                    flex: '0 1 340px',
                    font: 'inherit',
                    fontSize: 12.5,
                    padding: '7px 11px',
                  }}
                />
                <span style={{ color: 'var(--faint)', fontSize: 11.5 }}>
                  {aantalActief} actieve projecten · {metPlanning.length} mét planning deze week
                </span>
              </div>
              <div className="tabel-scroll">
              <table className="plan-grid" style={{ tableLayout: 'fixed', minWidth: 760 }}>
                <thead>
                  <tr>
                    <th style={{ width: 180 }}>Project</th>
                    {dagen.map((d) => (
                      <th
                        key={d.datum}
                        className={d.datum === vandaagIso ? 'plan-vandaag' : undefined}
                        style={{ textAlign: 'center' }}
                      >
                        {d.naam} {dagLabel(d.datum)}
                        {d.datum === vandaagIso && (
                          <span style={{ display: 'block', textTransform: 'none', letterSpacing: 0, fontWeight: 500 }}>
                            vandaag
                          </span>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {alleRijen.length === 0 && (
                    <tr>
                      <td colSpan={6}>
                        <p className="hint" style={{ margin: 0 }}>
                          Geen actieve projecten in deze administratie — synchroniseer de projecten of activeer ze in
                          RLZ.
                        </p>
                      </td>
                    </tr>
                  )}
                  {alleRijen.length > 0 && bovenblok.length === 0 && onderblok.length === 0 && (
                    <tr>
                      <td colSpan={6}>
                        <p className="hint" style={{ margin: 0 }}>
                          Geen project past bij &quot;{filterTerm.trim()}&quot; — pas het filter aan.
                        </p>
                      </td>
                    </tr>
                  )}
                  {bovenblok.map((rij) => renderRij(rij, false))}
                  {/* Overige actieve projecten: compact, leeg maar direct beplanbaar (v3). */}
                  {onderblok.length > 0 && (
                    <tr className="plan-scheider">
                      <th colSpan={6}>Overige actieve projecten — nog niemand gepland deze week</th>
                    </tr>
                  )}
                  {onderblok.map((rij) => renderRij(rij, true))}
                </tbody>
              </table>
              </div>
            </>
          )}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, position: 'sticky', top: 16 }}>
          <div className="panel">
            <h2 style={{ margin: '0 0 8px', fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: 6 }}>
              👷 ZZP&apos;ers &amp; uitvoerders <span style={{ fontWeight: 400, color: 'var(--faint)' }}>· sleep naar het grid</span>
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
            {data !== null && data.pool.length === 0 && (
              <p className="hint">Nog geen veldwerkers — nodig ze uit onder Gebruikers &amp; toegang.</p>
            )}
            {(data?.pool ?? []).map((p) => {
              const dagenGepland = Number(p.geplande_dagen)
              return (
                <div
                  key={p.gebruiker_id}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.effectAllowed = 'copy'
                    e.dataTransfer.setData('text/plain', p.gebruiker_id)
                    setSleep({ gebruikerId: p.gebruiker_id, naam: p.naam, bron: 'pool' })
                  }}
                  onDragEnd={() => setSleep(null)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    background: p.rol === 'uitvoerder' ? 'var(--ok-bg)' : 'var(--info-bg)',
                    border: '1px solid var(--border)',
                    borderRadius: 9,
                    padding: '5px 8px',
                    fontSize: 11.5,
                    marginBottom: 6,
                    cursor: 'grab',
                    userSelect: 'none',
                  }}
                >
                  <b style={{ fontSize: 12 }}>{p.naam}</b>
                  {p.rol === 'uitvoerder' && <span style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 700 }}>uitv.</span>}
                  {/* Besluit C: > 5 geplande dagen per week = zacht signaal (kleurt oranje). */}
                  <span
                    style={{
                      marginLeft: 'auto',
                      fontSize: 10.5,
                      fontWeight: 600,
                      color: dagenGepland > 5 ? 'var(--warn)' : 'var(--faint)',
                    }}
                    title={dagenGepland > 5 ? 'Meer dan 5 geplande dagen deze week (zacht signaal)' : undefined}
                  >
                    {dagenGepland.toLocaleString('nl-NL', { maximumFractionDigits: 1 })} dg
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

      <p className="hint" style={{ marginTop: 14, maxWidth: 980 }}>
        ℹ️ Zo grijpt de planning op de weekstaten in: uren op een gepland project/dag = groen · uren búíten de
        planning = oranje &quot;buiten planning&quot; bij de keuring (geen blokkade — invallen en omplannen blijft
        mogelijk) · twee projecten op één dag zónder planning-dekking = interne melding + teller per ZZP&apos;er,
        alleen zichtbaar voor kantoor. Meerdere mensen op één project/dag = meerdere kaartjes in één cel; halve
        dagen dragen een ½-label. Vooruit plannen kan onbegrensd (het hele jaar wordt vooruit gevuld); plannen ná
        de einddatum van een project mag en kleurt oranje.
      </p>
    </div>
  )
}
