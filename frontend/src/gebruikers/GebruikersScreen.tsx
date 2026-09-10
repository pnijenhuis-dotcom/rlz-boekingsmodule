import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useLocation, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { BevestigDialog } from '../instellingen/BevestigDialog'
import { QrLinkDialog } from '../ui/QrLinkDialog'
import { isVeldRol } from '../auth/rollen'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  FormField,
  Paginering,
  paginaSlice,
  Select,
  Switch,
  useToastOptioneel,
} from '../ui/basis'
import { Avatar } from '../ui/Avatar'
import { FoutMelding } from '../ui/FoutMelding'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  blokkeerGebruiker,
  haalApparatenVan,
  haalGebruikersOp,
  formatVerloop,
  heractiveerGebruiker,
  activeerLinkUrl,
  herstelLinkUrl,
  kanHerstelLinkKrijgen,
  mailUitnodigingOpnieuw,
  isVeldrol,
  rolLabel,
  stuurHerstelLink,
  wijzigEMail,
  trekApparaatIn,
  wijzigRol,
  type ApparaatDto,
  type GebruikerOverzichtDto,
  archiveerGebruiker,
  dearchiveerGebruiker,
  haalOpenWerkOp,
  isToestel,
  platformLabel,
  type OpenWerkDto,
} from './gebruikersApi'
import { ActivatiecodeBlok } from './ActivatiecodeBlok'
import {
  haalModuleRechtHouders,
  haalVeldwerkerbeheerHouders,
  zetModuleRecht,
  zetVeldwerkerbeheerRecht,
} from '../meerwerk/meerwerkApi'
import { AccordeurAdministraties } from './AccordeurAdministraties'
import { GebruikerRijMenu, type RijMenuItem } from './GebruikerRijMenu'
import { GebruikersTabelKop, gebruikersTabelStijl } from './GebruikersTabelKop'
import type { GebruikersTab } from './gebruikersKolommen'
import { ScopeModal } from './ScopeModal'
import { UitnodigModal } from './UitnodigModal'
import { VeldwerkersPanel } from './VeldwerkersPanel'

/* Gebruikers & toegang (fase 3 modernisering 15-08, mockup #scherm-gebruikers; rollenmodel
 * 0019 ongewijzigd): kantoorgebruikers (rol, scope, apparaten/passkeys, TOTP-status),
 * openstaande uitnodigingen met "opnieuw mailen", accordeurs-blok met kill-switch en staande
 * goedkeuringen. Zelfbescherming (eigen rol/scope alleen door een ándere Beheerder) wordt
 * server-side afgedwongen; de UI biedt de onmogelijke actie niet aan. */

interface ApparaatGroep {
  naam: string
  isDevStub: boolean
  /** Alle credential-id's achter deze weergave-rij — de kill-switch trekt ze ÁLLE in. */
  ids: string[]
  /** App-auth 08-09: toestel (activatiecode/link + toegangscode) of passkey (WebAuthn; ook oude app-toestellen). */
  soort: 'passkey' | 'toestel'
  platform: string | null
  aangemaaktOp: string
  laatstGebruiktOp: string | null
  /** Gevuld = passkey van een app-gebruiker die niet meer in gebruik is: grijs, kill-switch blijft. */
  nietMeerGebruiktOp: string | null
}

function formatDag(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString('nl-NL', { day: '2-digit', month: '2-digit' })
}

/** Dev-stub-registraties maakten vóór de bron-fix (2026-08-16) per activering een nieuwe
 * credential-rij aan, waardoor hetzelfde stub-apparaat dubbel in de lijst stond. Weergave
 * groepeert identieke stubs op naam; de kill-switch raakt dan álle onderliggende credentials —
 * nooit een actieve credential verbergen buiten bereik van de knop. Echte passkeys worden
 * nooit gegroepeerd: twee apparaten met dezelfde naam zijn daar echt twee apparaten. */
function groepeerApparaten(apparaten: ApparaatDto[]): ApparaatGroep[] {
  const groepen: ApparaatGroep[] = []
  for (const apparaat of apparaten) {
    const naam = apparaat.apparaat_naam ?? 'apparaat'
    const bestaande = apparaat.is_dev_stub ? groepen.find((g) => g.isDevStub && g.naam === naam) : undefined
    if (bestaande) bestaande.ids.push(apparaat.id)
    else
      groepen.push({
        naam,
        isDevStub: apparaat.is_dev_stub,
        ids: [apparaat.id],
        soort: isToestel(apparaat) ? 'toestel' : 'passkey',
        platform: apparaat.platform ?? null,
        aangemaaktOp: apparaat.aangemaakt_op,
        laatstGebruiktOp: apparaat.laatst_gebruikt_op,
        nietMeerGebruiktOp: apparaat.niet_meer_gebruikt_op ?? null,
      })
  }
  return groepen
}

/** Eén apparaat in de apparatenkolom (contract §6): toestel = chip "📱 Toestel · naam (platform)" mét de
 * detailregel "gekoppeld dd-mm · laatst gebruikt dd-mm" eronder (blok 2 10-09: twee regels i.p.v. één
 * chip van ~500 px — de chip krijgt anders een ellipsis binnen het kolomminimum); passkey = "🔑 naam",
 * grijs mét "passkey — niet meer gebruikt" als de CLI 'm zo markeerde. De kill-switch (tekstknop) staat
 * bij beide op de chipregel — zelfde endpoint, zelfde bevestiging. */
function ApparaatChip({ groep, onKillSwitch }: { groep: ApparaatGroep; onKillSwitch: () => void }) {
  const nietMeer = groep.nietMeerGebruiktOp !== null
  const killSwitch = (
    <button type="button" className="linkbtn" onClick={onKillSwitch} title={`"${groep.naam}" per direct blokkeren (bevestiging volgt)`}>
      Kill-switch
    </button>
  )
  if (groep.soort === 'toestel') {
    const platform = platformLabel(groep.platform)
    const kop = `📱 Toestel · ${groep.naam}${platform ? ` (${platform})` : ''}`
    const detail = [
      formatDag(groep.aangemaaktOp) ? `gekoppeld ${formatDag(groep.aangemaaktOp)}` : null,
      formatDag(groep.laatstGebruiktOp) ? `laatst gebruikt ${formatDag(groep.laatstGebruiktOp)}` : null,
    ].filter((d): d is string => d !== null)
    return (
      <div className="apparaat-blok" data-testid="apparaat-toestel">
        <div className="apparaat-rij">
          <span className="apparaat-chip" title={kop}>
            {kop}
          </span>
          {killSwitch}
        </div>
        {detail.length > 0 && <div className="cel-detail">{detail.join(' · ')}</div>}
      </div>
    )
  }
  const tekst = `🔑 ${groep.naam}${groep.isDevStub ? ' (dev-stub)' : ''}${nietMeer ? ' · passkey — niet meer gebruikt' : ''}`
  return (
    <div className="apparaat-blok">
      <div className="apparaat-rij">
        <span
          className="apparaat-chip"
          data-testid={nietMeer ? 'apparaat-passkey-oud' : 'apparaat-passkey'}
          style={nietMeer ? { color: 'var(--muted)', opacity: 0.75 } : undefined}
          title={nietMeer ? `Passkey — niet meer gebruikt sinds ${formatDag(groep.nietMeerGebruiktOp) ?? '?'}; nooit verwijderd` : tekst}
        >
          {tekst}
        </span>
        {killSwitch}
      </div>
    </div>
  )
}

export type GebruikersGroep = GebruikersTab

const GROEPEN: { key: GebruikersGroep; label: string }[] = [
  { key: 'kantoor', label: 'Kantoor' },
  { key: 'veldwerkers', label: 'Veldwerkers' },
  { key: 'accordeurs', label: 'Klant-accordeurs' },
]

/** Tab uit de URL: `?groep=` is de norm; oude `#accordeurs`-/`#veldwerkers`-ankers en onbekende
 * waarden vallen terug op Kantoor — bestaande deep-links blijven werken (punt 3, 25-08 deel 3). */
export function groepUitUrl(zoek: string | null, hash: string): GebruikersGroep {
  const kandidaat = (zoek ?? hash.replace(/^#/, '')).toLowerCase()
  if (kandidaat.startsWith('accordeur') || kandidaat === 'klant-accordeurs') return 'accordeurs'
  if (kandidaat.startsWith('veldwerker')) return 'veldwerkers'
  return 'kantoor'
}

/** Zoekfilter per tab: naam, e-mail, rol-label en administratienamen (punt 3). */
export function filterGebruikers(
  lijst: GebruikerOverzichtDto[],
  zoekterm: string,
  naamPerAdministratie: Map<string, string>,
): GebruikerOverzichtDto[] {
  const term = zoekterm.trim().toLowerCase()
  if (!term) return lijst
  return lijst.filter((g) =>
    [g.naam, g.e_mail, rolLabel(g.rol), ...g.administratie_ids.map((id) => naamPerAdministratie.get(id) ?? '')]
      .join(' ')
      .toLowerCase()
      .includes(term),
  )
}

/** Waarschuwingstekst mét aantallen in de archiveer-dialoog (besluit 26-08: waarschuwing, geen
 * blokkade). Telling nog bezig of onbeschikbaar → geen aantallen, de dialoog blijft bruikbaar. */
export function openWerkTekst(werk: OpenWerkDto | null | 'laden'): string {
  if (werk === null || werk === 'laden') return ''
  const delen: string[] = []
  if (werk.open_accorderingen > 0) delen.push(`${werk.open_accorderingen} open accordering${werk.open_accorderingen === 1 ? '' : 'en'}`)
  if (werk.weekstaten_ter_keuring > 0) delen.push(`${werk.weekstaten_ter_keuring} weekstaat${werk.weekstaten_ter_keuring === 1 ? '' : 'staten'} ter keuring`)
  if (werk.eigen_open_weekstaten > 0) delen.push(`${werk.eigen_open_weekstaten} eigen open weekstaat${werk.eigen_open_weekstaten === 1 ? '' : 'staten'}`)
  if (delen.length === 0) return ''
  return ` LET OP — open werk: ${delen.join(', ')}. Dit werk blijft staan maar niemand handelt het af tot je het opnieuw toewijst (accorderingslagen / keurders).`
}

export function GebruikersScreen() {
  const { gebruikerId, rol } = useAuth()
  const { administraties, fout: administratiesFout } = useAdministraties()
  const { meld } = useToastOptioneel()
  const [gebruikers, setGebruikers] = useState<GebruikerOverzichtDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [mailFout, setMailFout] = useState<string | null>(null)
  // D3 (01-09): "Toon QR" — de laatste uitnodigingslink van een veldwerker als QR voor de bouwplaats.
  // App-auth 08-09: dezelfde banner draagt de activatiecode van een app-rol-uitnodiging/herstel-link (alleen als
  // de server er één meegaf; kantoor-rollen krijgen null) — één plek, geen tweede melding.
  const [aanbod, setAanbod] = useState<{ link: string | null; code: string | null; naam: string } | null>(null)
  const [qrOpen, setQrOpen] = useState(false)
  const [apparatenPer, setApparatenPer] = useState<Record<string, ApparaatDto[]>>({})

  const [uitnodigSoort, setUitnodigSoort] = useState<'medewerker' | 'accordeur' | 'veldwerker' | null>(null)
  const [scopeVoor, setScopeVoor] = useState<GebruikerOverzichtDto | null>(null)
  const [rolWijziging, setRolWijziging] = useState<{ gebruiker: GebruikerOverzichtDto; nieuweRol: string } | null>(
    null,
  )
  const [killSwitchVoor, setKillSwitchVoor] = useState<{ gebruiker: GebruikerOverzichtDto; groep: ApparaatGroep } | null>(null)
  const [blokkade, setBlokkade] = useState<{ gebruiker: GebruikerOverzichtDto; actie: 'blokkeren' | 'heractiveren' } | null>(null)
  // Archiveren (feedbackronde 26-08 punt 1, 0052-patroon): bevestigingsdialoog mét open-werk-
  // aantallen (waarschuwing, geen blokkade); gearchiveerden zitten achter het filter per tab.
  const [archivering, setArchivering] = useState<{ gebruiker: GebruikerOverzichtDto; actie: 'archiveren' | 'dearchiveren' } | null>(null)
  const [openWerk, setOpenWerk] = useState<OpenWerkDto | null | 'laden'>(null)
  const [toonGearchiveerd, setToonGearchiveerd] = useState(false)
  const [actieBezig, setActieBezig] = useState(false)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [opnieuwBezig, setOpnieuwBezig] = useState<string | null>(null)
  const [herstelVoor, setHerstelVoor] = useState<GebruikerOverzichtDto | null>(null)
  const [eMailVoor, setEMailVoor] = useState<GebruikerOverzichtDto | null>(null)
  const [nieuwEMail, setNieuwEMail] = useState('')

  const laad = useCallback(() => {
    setFout(null)
    haalGebruikersOp()
      .then((data) => setGebruikers(data.gebruikers))
      .catch((err: unknown) =>
        setFout(
          err instanceof ApiError && err.status === 403
            ? 'Gebruikersbeheer is alleen toegankelijk voor de Beheerder-rol.'
            : err instanceof Error
              ? err.message
              : 'Onbekende fout',
        ),
      )
  }, [])

  useEffect(() => {
    laad()
  }, [laad])

  // Module-recht "Meerwerk & urenstaten" (0019-patroon, migratie 0056): houders laden en per
  // kantoormedewerker tonen als switch — Beheerder heeft het recht altijd (niet instelbaar).
  const [rechtHouders, setRechtHouders] = useState<Set<string>>(new Set())
  const [rechtBezig, setRechtBezig] = useState<string | null>(null)
  useEffect(() => {
    haalModuleRechtHouders()
      .then((data) => setRechtHouders(new Set(data.gebruiker_ids)))
      .catch(() => undefined)
  }, [])
  async function toggleMeerwerkRecht(g: GebruikerOverzichtDto, ingeschakeld: boolean) {
    setRechtBezig(g.id)
    try {
      await zetModuleRecht(g.id, ingeschakeld)
      setRechtHouders((huidig) => {
        const kopie = new Set(huidig)
        if (ingeschakeld) kopie.add(g.id)
        else kopie.delete(g.id)
        return kopie
      })
      meld(
        ingeschakeld
          ? `${g.naam} heeft nu het module-recht Meerwerk & urenstaten.`
          : `${g.naam} verliest het module-recht — meerwerk verdwijnt overal (menu, standen, zoeken, API).`,
      )
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Recht wijzigen mislukt.')
    } finally {
      setRechtBezig(null)
    }
  }

  // Fijnmazig recht 'veldwerkerbeheer' (31-08, migratie 0091): B+P mét dit recht mag
  // uitsluitend veldwerkers aanmaken/archiveren binnen de eigen scope — toekennen Beheerder-only.
  const [vwbHouders, setVwbHouders] = useState<Set<string>>(new Set())
  useEffect(() => {
    haalVeldwerkerbeheerHouders()
      .then((data) => setVwbHouders(new Set(data.gebruiker_ids)))
      .catch(() => undefined)
  }, [])
  async function toggleVeldwerkerbeheer(g: GebruikerOverzichtDto, ingeschakeld: boolean) {
    setRechtBezig(g.id)
    try {
      await zetVeldwerkerbeheerRecht(g.id, ingeschakeld)
      setVwbHouders((huidig) => {
        const kopie = new Set(huidig)
        if (ingeschakeld) kopie.add(g.id)
        else kopie.delete(g.id)
        return kopie
      })
      meld(
        ingeschakeld
          ? `${g.naam} mag nu veldwerkers aanmaken en archiveren binnen de eigen scope (veldwerkerbeheer).`
          : `${g.naam} verliest het veldwerkerbeheer-recht.`,
      )
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Recht wijzigen mislukt.')
    } finally {
      setRechtBezig(null)
    }
  }

  // Gearchiveerden (0075) zitten wél in de response (één request) maar nooit in de default-
  // lijsten: per tab schakelt het filter "gearchiveerd (N)" naar uitsluitend de gearchiveerden.
  const zichtbaar = useMemo(
    () => (gebruikers ?? []).filter((g) => (g.status === 'gearchiveerd') === toonGearchiveerd),
    [gebruikers, toonGearchiveerd],
  )
  const gearchiveerdTelling = useMemo(() => {
    const alle = (gebruikers ?? []).filter((g) => g.status === 'gearchiveerd')
    return {
      kantoor: alle.filter((g) => g.rol !== 'klant_accordeur' && !isVeldrol(g.rol)).length,
      accordeurs: alle.filter((g) => g.rol === 'klant_accordeur').length,
      veldwerkers: alle.filter((g) => isVeldrol(g.rol)).length,
    }
  }, [gebruikers])
  const kantoor = useMemo(() => zichtbaar.filter((g) => g.rol !== 'klant_accordeur' && !isVeldrol(g.rol)), [zichtbaar])
  const accordeurs = useMemo(() => zichtbaar.filter((g) => g.rol === 'klant_accordeur'), [zichtbaar])
  const veldwerkers = useMemo(() => zichtbaar.filter((g) => isVeldrol(g.rol)), [zichtbaar])

  // Tabs per groep + zoekveld + paginering (punt 3, 25-08 deel 3): tab in de URL (?groep=),
  // zoekterm en pagina lokaal; tab-wissel wist zoek + pagina.
  const [searchParams, setSearchParams] = useSearchParams()
  const { hash } = useLocation()
  const groep = groepUitUrl(searchParams.get('groep'), hash)
  const [zoekterm, setZoekterm] = useState('')
  const [pagina, setPagina] = useState(1)
  const kiesGroep = (nieuwe: GebruikersGroep) => {
    setZoekterm('')
    setPagina(1)
    setToonGearchiveerd(false)
    setSearchParams(nieuwe === 'kantoor' ? {} : { groep: nieuwe }, { replace: true })
  }
  const naamPerAdministratie = useMemo(() => new Map((administraties ?? []).map((a) => [a.id, a.naam])), [administraties])

  // Apparaten per accordeur (kill-switch-blok) — best-effort per gebruiker, een fout daar
  // blokkeert de lijst niet.
  useEffect(() => {
    let actueel = true
    for (const accordeur of [...accordeurs, ...veldwerkers]) {
      if (apparatenPer[accordeur.id]) continue
      haalApparatenVan(accordeur.id)
        .then((data) => {
          if (actueel) setApparatenPer((huidig) => ({ ...huidig, [accordeur.id]: data.apparaten }))
        })
        .catch(() => undefined)
    }
    return () => {
      actueel = false
    }
  }, [accordeurs, veldwerkers, apparatenPer])

  async function opnieuwMailen(gebruiker: GebruikerOverzichtDto) {
    setOpnieuwBezig(gebruiker.id)
    setMailFout(null)
    try {
      const resultaat = await mailUitnodigingOpnieuw(gebruiker.id)
      const link = isVeldRol(gebruiker.rol) && resultaat.token ? activeerLinkUrl(resultaat.token) : null
      const code = resultaat.activatiecode ?? null
      if (link || code) setAanbod({ link, code, naam: gebruiker.naam })
      if (resultaat.mail_verzonden) {
        meld(`Uitnodiging opnieuw gemaild aan ${gebruiker.e_mail} — de oude link is vervallen.`)
      } else {
        setMailFout(
          `Nieuwe uitnodiging aangemaakt voor ${gebruiker.e_mail}, maar het mailen mislukte: ${resultaat.mail_fout ?? 'onbekende mailfout'}. De oude link is al vervallen — probeer opnieuw of deel de link handmatig.`,
        )
      }
      laad()
    } catch (err) {
      setMailFout(err instanceof ApiError ? err.message : 'Opnieuw mailen mislukt.')
    } finally {
      setOpnieuwBezig(null)
    }
  }

  /** "Herstel-link sturen" (feedbackronde 25-08 punt 7; app-auth 08-09): actieve accordeur/veldwerker die de app
   * opnieuw moet koppelen (nieuw toestel, toegangscode kwijt, ná een kill-switch) krijgt een eenmalige 72-uurs link
   * + activatiecode; akkoorden blijven, oudere links vervallen, lopende sessies eindigen.
   * Fail-zichtbaar: mislukt de mail, dan staan link én code hier om handmatig te delen. */
  async function bevestigHerstelLink() {
    if (!herstelVoor) return
    setActieBezig(true)
    setActieFout(null)
    setMailFout(null)
    try {
      const resultaat = await stuurHerstelLink(herstelVoor.id)
      if (resultaat.activatiecode) setAanbod({ link: null, code: resultaat.activatiecode, naam: herstelVoor.naam })
      if (resultaat.mail_verzonden) {
        meld(`Herstel-link gemaild aan ${herstelVoor.e_mail} — eerder verstuurde links zijn vervallen.`)
      } else {
        setMailFout(
          `Herstel-link aangemaakt voor ${herstelVoor.e_mail}, maar het mailen mislukte: ${resultaat.mail_fout ?? 'onbekende mailfout'}. Deel de link handmatig (eenmalig, 72 uur geldig): ${herstelLinkUrl(resultaat.token)}`,
        )
      }
      setHerstelVoor(null)
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Herstel-link sturen mislukt.')
    } finally {
      setActieBezig(false)
    }
  }

  /** De ENE zichtbare knop in de actiekolom (UX-norm "één primaire knop + ⋯", blok 2 10-09): een open
   * uitnodiging → "Opnieuw mailen"; een actieve externe app-gebruiker → "Herstel-link" (alleen bij een
   * account dat een wachtwoord heeft gehad — server-side dezelfde poort; geblokkeerd = eerst
   * heractiveren). Anders geen knop: alles overige zit in het ⋯-menu. */
  function primaireKnop(g: GebruikerOverzichtDto): ReactNode {
    if (g.status === 'uitgenodigd') {
      return (
        <Button variant="secundair" maat="klein" disabled={opnieuwBezig === g.id} onClick={() => void opnieuwMailen(g)}>
          {opnieuwBezig === g.id ? 'Bezig…' : 'Opnieuw mailen'}
        </Button>
      )
    }
    if (kanHerstelLinkKrijgen(g)) {
      return (
        <Button variant="secundair" maat="klein" onClick={() => setHerstelVoor(g)}>
          Herstel-link
        </Button>
      )
    }
    return null
  }

  /** ⋯-menu-items per rij — dezelfde handelingen als vóór 10-09, alleen niet meer als losse knoppen:
   * - E-mail wijzigen (A5 25-08, Beheerder-only; punt 22 opruimrun 28-08: óók geblokkeerd/gearchiveerd én
   *   op de Kantoor-tab — een adres vrijmaken hoeft niet via dearchiveren → wijzigen → archiveren);
   * - Scope wijzigen (alleen Kantoor, niet-Beheerder, niet de eigen rij);
   * - Blokkeren/Heractiveren en Archiveren/Dearchiveren — nooit bij het eigen account (server-side
   *   eveneens geweigerd); een gearchiveerde heeft alleen "Dearchiveren". */
  function menuItems(g: GebruikerOverzichtDto, opties: { scope?: boolean } = {}): RijMenuItem[] {
    const isZelf = g.id === gebruikerId
    const items: RijMenuItem[] = [
      {
        label: 'E-mail wijzigen…',
        onClick: () => {
          setEMailVoor(g)
          setNieuwEMail(g.e_mail)
        },
      },
    ]
    if (opties.scope && g.rol !== 'beheerder' && !isZelf) {
      items.push({ label: 'Scope wijzigen…', onClick: () => setScopeVoor(g) })
    }
    if (isZelf) return items
    if (g.status === 'gearchiveerd') {
      items.push({ label: 'Dearchiveren…', onClick: () => setArchivering({ gebruiker: g, actie: 'dearchiveren' }) })
      return items
    }
    if (g.status === 'geblokkeerd') {
      items.push({ label: 'Heractiveren…', onClick: () => setBlokkade({ gebruiker: g, actie: 'heractiveren' }) })
    } else {
      items.push({ label: 'Blokkeren…', gevaar: true, onClick: () => setBlokkade({ gebruiker: g, actie: 'blokkeren' }) })
    }
    items.push({ label: 'Archiveren…', onClick: () => openArchivering(g) })
    return items
  }

  function actieKolom(g: GebruikerOverzichtDto, opties: { scope?: boolean } = {}): ReactNode {
    return <GebruikerRijMenu naam={g.naam} primair={primaireKnop(g)} items={menuItems(g, opties)} />
  }

  async function bevestigEMailWijziging() {
    if (!eMailVoor) return
    setActieBezig(true)
    setActieFout(null)
    setMailFout(null)
    try {
      const r = await wijzigEMail(eMailVoor.id, nieuwEMail.trim())
      if (r.uitnodiging_vernieuwd) {
        if (r.activatiecode) setAanbod({ link: null, code: r.activatiecode, naam: eMailVoor.naam })
        if (r.mail_verzonden) {
          meld(`E-mailadres gewijzigd naar ${r.nieuw_e_mail} — verse uitnodiging gemaild, oude links zijn vervallen.`)
        } else {
          setMailFout(
            `E-mailadres gewijzigd naar ${r.nieuw_e_mail}, maar het mailen van de nieuwe uitnodiging mislukte: ${r.mail_fout ?? 'onbekende mailfout'}. Gebruik "Opnieuw mailen".`,
          )
        }
      } else {
        meld(`E-mailadres (login) gewijzigd naar ${r.nieuw_e_mail} — passkeys, toestellen, TOTP en historie blijven aan het account hangen.`)
      }
      setEMailVoor(null)
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'E-mail wijzigen mislukt.')
    } finally {
      setActieBezig(false)
    }
  }

  /** Casus Haci (28-08): activatie ooit halverwege gestrand (wachtwoord gezet, toestel nooit gekoppeld) — de
   * Herstel-link (rechts) ruimt dit op. Nieuwe activaties zijn atomair; dit is de terugwerkende-kracht-detectie. */
  function halfGeactiveerdBadge(g: GebruikerOverzichtDto) {
    if (!g.half_geactiveerd) return null
    return (
      <>
        {' '}
        <Badge variant="warn" title="Activatie niet afgerond, geen gekoppeld toestel — stuur een herstel-link">
          half geactiveerd — geen toestel
        </Badge>
      </>
    )
  }

  /** Open herstel-link als detailregel onder de statuschips (blok 2 10-09: was een badge van ~200 px). */
  function herstelDetail(g: GebruikerOverzichtDto) {
    if (!g.open_herstel_verloopt_op) return null
    return <div className="cel-detail">herstel-link {formatVerloop(g.open_herstel_verloopt_op)}</div>
  }

  async function bevestigRolWijziging() {
    if (!rolWijziging) return
    setActieBezig(true)
    setActieFout(null)
    try {
      await wijzigRol(rolWijziging.gebruiker.id, rolWijziging.nieuweRol)
      meld(`${rolWijziging.gebruiker.naam} is nu ${rolLabel(rolWijziging.nieuweRol)}.`)
      setRolWijziging(null)
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Rol wijzigen mislukt.')
    } finally {
      setActieBezig(false)
    }
  }

  async function bevestigKillSwitch() {
    if (!killSwitchVoor) return
    setActieBezig(true)
    setActieFout(null)
    try {
      // Eén weergave-rij kan meerdere credentials dragen (gegroepeerde dev-stubs) — allemaal
      // intrekken, anders blijft er stil een werkende credential achter.
      for (const id of killSwitchVoor.groep.ids) {
        await trekApparaatIn(id)
      }
      meld(
        `Kill-switch: "${killSwitchVoor.groep.naam}" van ${killSwitchVoor.gebruiker.naam} is per direct geblokkeerd.`,
      )
      setApparatenPer((huidig) => {
        const kopie = { ...huidig }
        delete kopie[killSwitchVoor.gebruiker.id]
        return kopie
      })
      setKillSwitchVoor(null)
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Intrekken mislukt.')
    } finally {
      setActieBezig(false)
    }
  }

  async function bevestigBlokkade() {
    if (!blokkade) return
    setActieBezig(true)
    setActieFout(null)
    try {
      if (blokkade.actie === 'blokkeren') {
        await blokkeerGebruiker(blokkade.gebruiker.id)
        meld(`${blokkade.gebruiker.naam} is per direct geblokkeerd — alle sessies zijn beëindigd.`)
      } else {
        await heractiveerGebruiker(blokkade.gebruiker.id)
        meld(`${blokkade.gebruiker.naam} is geheractiveerd en kan weer inloggen.`)
      }
      setBlokkade(null)
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Actie mislukt.')
    } finally {
      setActieBezig(false)
    }
  }

  function openArchivering(g: GebruikerOverzichtDto) {
    setActieFout(null)
    setArchivering({ gebruiker: g, actie: 'archiveren' })
    setOpenWerk('laden')
    haalOpenWerkOp(g.id)
      .then(setOpenWerk)
      .catch(() => setOpenWerk(null)) // telling onbeschikbaar ≠ blokkade: dialoog blijft bruikbaar
  }

  async function bevestigArchivering() {
    if (!archivering) return
    setActieBezig(true)
    setActieFout(null)
    try {
      if (archivering.actie === 'archiveren') {
        await archiveerGebruiker(archivering.gebruiker.id)
        meld(`${archivering.gebruiker.naam} is gearchiveerd — toegang dicht, historie blijft staan (filter "gearchiveerd").`)
      } else {
        await dearchiveerGebruiker(archivering.gebruiker.id)
        meld(`${archivering.gebruiker.naam} is uit het archief gehaald (status van vóór archivering hersteld).`)
      }
      setArchivering(null)
      laad()
    } catch (err) {
      setActieFout(err instanceof ApiError ? err.message : 'Actie mislukt.')
    } finally {
      setActieBezig(false)
    }
  }

  function archiveringDetail(g: GebruikerOverzichtDto) {
    if (g.status !== 'gearchiveerd' || !g.gearchiveerd_op) return null
    return (
      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
        gearchiveerd sinds {new Date(g.gearchiveerd_op).toLocaleDateString('nl-NL')}
        {g.gearchiveerd_door_naam ? ` door ${g.gearchiveerd_door_naam}` : ''}
      </div>
    )
  }

  function blokkadeDetail(g: GebruikerOverzichtDto) {
    if (g.status !== 'geblokkeerd' || !g.geblokkeerd_op) return null
    return (
      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
        sinds {new Date(g.geblokkeerd_op).toLocaleDateString('nl-NL')}
        {g.geblokkeerd_door_naam ? ` door ${g.geblokkeerd_door_naam}` : ''}
      </div>
    )
  }

  if (rol !== 'beheerder') {
    return <p className="hint">Gebruikersbeheer is alleen toegankelijk voor de Beheerder-rol.</p>
  }

  const gefilterd = {
    kantoor: filterGebruikers(kantoor, zoekterm, naamPerAdministratie),
    veldwerkers: filterGebruikers(veldwerkers, zoekterm, naamPerAdministratie),
    accordeurs: filterGebruikers(accordeurs, zoekterm, naamPerAdministratie),
  }
  const kantoorPagina = paginaSlice(gefilterd.kantoor, pagina)
  const veldwerkersPagina = paginaSlice(gefilterd.veldwerkers, pagina)
  const accordeursPagina = paginaSlice(gefilterd.accordeurs, pagina)
  const tellers: Record<GebruikersGroep, number> = {
    kantoor: kantoor.length,
    veldwerkers: veldwerkers.length,
    accordeurs: accordeurs.length,
  }
  const zoekveld = (
    <div className="lijst-kop">
      <input
        type="search"
        aria-label="Zoek gebruikers"
        placeholder="Zoek op naam, e-mail, rol of administratie…"
        value={zoekterm}
        onChange={(e) => {
          setZoekterm(e.target.value)
          setPagina(1)
        }}
      />
      <span className="hint" style={{ margin: 0 }}>
        {gefilterd[groep].length === tellers[groep]
          ? `${tellers[groep]} ${tellers[groep] === 1 ? 'gebruiker' : 'gebruikers'}`
          : `${gefilterd[groep].length} van ${tellers[groep]} gebruikers`}
        {toonGearchiveerd ? ' (archief)' : ''}
      </span>
      {(gearchiveerdTelling[groep] > 0 || toonGearchiveerd) && (
        <button
          type="button"
          className={`chip ${toonGearchiveerd ? 'afwijking' : 'stil'}`}
          style={{ cursor: 'pointer', marginLeft: 'auto' }}
          aria-pressed={toonGearchiveerd}
          title={
            toonGearchiveerd
              ? 'Terug naar de actieve gebruikers'
              : 'Toon uitsluitend de gearchiveerde gebruikers van deze groep (toegang dicht, historie bewaard)'
          }
          onClick={() => {
            setToonGearchiveerd((v) => !v)
            setPagina(1)
          }}
        >
          {toonGearchiveerd ? '← actieve gebruikers' : `gearchiveerd (${gearchiveerdTelling[groep]})`}
        </button>
      )}
    </div>
  )

  return (
    <div>
      <div className="topbar">
        <div>
          <h1>Gebruikers &amp; toegang</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Medewerkers, rollen, administratie-scope en apparaten — met audit op elke wijziging.
          </div>
        </div>
        {groep === 'kantoor' && <Button onClick={() => setUitnodigSoort('medewerker')}>+ Medewerker uitnodigen</Button>}
        {/* Veldwerkers: de uitnodig-knop zit in het paneel zelf (VeldwerkersPanel, eigen kop). */}
        {groep === 'accordeurs' && <Button onClick={() => setUitnodigSoort('accordeur')}>+ Accordeur uitnodigen</Button>}
      </div>

      {fout && <FoutMelding melding="De gebruikerslijst kon niet geladen worden." detail={fout} onOpnieuw={laad} />}
      {mailFout && <FoutMelding melding={mailFout} />}
      {aanbod && (
        <div className="hint" role="status" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }} data-testid="qr-aanbod">
          {aanbod.link && (
            <>
              Uitnodigingslink voor {aanbod.naam} — op de bouwplaats scannen?
              <Button variant="secundair" maat="klein" onClick={() => setQrOpen(true)}>
                Toon QR
              </Button>
            </>
          )}
          <ActivatiecodeBlok code={aanbod.code} naam={aanbod.link ? undefined : aanbod.naam} />
          <button type="button" className="linkbtn" onClick={() => setAanbod(null)}>
            verbergen
          </button>
        </div>
      )}
      <QrLinkDialog link={qrOpen && aanbod?.link ? aanbod.link : null} titel={`QR-uitnodiging — ${aanbod?.naam ?? ''}`} onSluiten={() => setQrOpen(false)} />
      {administratiesFout && <FoutMelding melding="Administraties konden niet geladen worden." detail={administratiesFout} />}

      {/* Tabs per groep (besluit Peter 25-08 "net zoals instellingen"): tellers per tab, eigen
          zoekveld + paginering + uitnodig-knop per tab; ?groep= in de URL. */}
      <div className="segment tabs-gebruikers" role="tablist" aria-label="Gebruikersgroep" style={{ marginBottom: 12 }}>
        {GROEPEN.map((g) => (
          <button
            key={g.key}
            type="button"
            role="tab"
            aria-selected={groep === g.key}
            className={groep === g.key ? 'actief' : undefined}
            onClick={() => kiesGroep(g.key)}
          >
            {g.label} ({tellers[g.key]})
          </button>
        ))}
      </div>

      {groep === 'kantoor' && (
        <div className="panel" role="tabpanel">
          <h2>Kantoorgebruikers</h2>
          {gebruikers === null && !fout && (
            <div aria-busy="true">
              <span className="skeleton" style={{ width: '55%', marginBottom: 8 }} />
              <span className="skeleton" style={{ width: '40%' }} />
            </div>
          )}
          {gebruikers !== null && (
            <>
              {zoekveld}
          <div className="tabel-scroll sticky-koppen">
            {/* Blok 2 (10-09): kolomminima uit één bron (gebruikersKolommen.ts), koppen nooit afgekapt,
                Rol · scope en Rechten samengevoegd zodat de tabel op 1440 zonder interne scroll past;
                acties = één primaire knop + ⋯-menu. */}
            <table className="gebruikers-tabel" style={gebruikersTabelStijl('kantoor')} data-testid="gebruikers-tabel-kantoor">
              <GebruikersTabelKop tab="kantoor" />
              <tbody>
                {kantoorPagina.map((g) => {
                  const isZelf = g.id === gebruikerId
                  const openUitnodiging = g.status === 'uitgenodigd' && g.open_uitnodiging_verloopt_op
                  return (
                    <tr key={g.id}>
                      <td>
                        <div className="naam-met-avatar">
                          <Avatar id={g.id} naam={g.naam} />
                          <div style={{ minWidth: 0 }}>
                            <b>{g.naam}</b>
                            <div className="gebruiker-email" title={g.e_mail}>
                              {g.e_mail}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td>
                        {isZelf ? (
                          <>
                            <Badge variant="paars">{rolLabel(g.rol)}</Badge>
                            <div className="cel-detail">eigen rol/scope wijzigt alleen een ándere Beheerder</div>
                          </>
                        ) : (
                          <Select
                            aria-label={`Rol van ${g.naam}`}
                            value={g.rol}
                            onChange={(e) => setRolWijziging({ gebruiker: g, nieuweRol: e.target.value })}
                          >
                            <option value="boekhouding">Boekhouding</option>
                            <option value="boekhouding_projecten">Boekhouding + Projecten</option>
                            <option value="beheerder">Beheerder</option>
                          </Select>
                        )}
                        <div className="chips-regel" style={{ marginTop: 4 }}>
                          {g.rol === 'beheerder' ? (
                            <Badge variant="stil">alle administraties</Badge>
                          ) : (
                            <Badge variant="info">
                              {g.administratie_ids.length} {g.administratie_ids.length === 1 ? 'administratie' : 'administraties'}
                            </Badge>
                          )}
                        </div>
                      </td>
                      <td>
                        {g.rol === 'beheerder' ? (
                          <span className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                            altijd (Beheerder)
                          </span>
                        ) : (
                          <div className="rechten-regels">
                            <label className="recht-regel">
                              <Switch
                                aria-label={`Meerwerk & urenstaten voor ${g.naam}`}
                                checked={rechtHouders.has(g.id)}
                                disabled={rechtBezig === g.id}
                                onChange={(e) => void toggleMeerwerkRecht(g, e.target.checked)}
                              />
                              <span>Meerwerk &amp; urenstaten</span>
                            </label>
                            <label
                              className="recht-regel"
                              title="Mag uitsluitend veldwerkers (ZZP'er/uitvoerder/detacheerder) aanmaken en archiveren binnen de eigen scope — nooit kantoorrollen of rol-/scope-mutaties"
                            >
                              <Switch
                                aria-label={`Veldwerkerbeheer voor ${g.naam}`}
                                checked={vwbHouders.has(g.id)}
                                disabled={rechtBezig === g.id}
                                onChange={(e) => void toggleVeldwerkerbeheer(g, e.target.checked)}
                              />
                              <span>Veldwerkerbeheer</span>
                            </label>
                          </div>
                        )}
                      </td>
                      <td>
                        <div className="chips-regel">
                          {g.aantal_passkeys > 0 && (
                            <span className="apparaat-chip">
                              🔑 {g.aantal_passkeys} passkey{g.aantal_passkeys === 1 ? '' : 's'}
                            </span>
                          )}
                          {g.heeft_totp ? (
                            <span className="apparaat-chip">🔐 TOTP</span>
                          ) : (
                            g.status === 'actief' && <Badge variant="warn">geen TOTP</Badge>
                          )}
                          {g.aantal_passkeys === 0 && g.status === 'actief' && <Badge variant="warn">geen passkey</Badge>}
                        </div>
                      </td>
                      <td>
                        <div className="chips-regel">
                          {g.status === 'actief' && <Badge variant="ok">actief</Badge>}
                          {g.status === 'geblokkeerd' && <Badge variant="danger">geblokkeerd</Badge>}
                          {g.status === 'gearchiveerd' && <Badge variant="stil">gearchiveerd</Badge>}
                          {openUitnodiging && <Badge variant="stil">uitgenodigd</Badge>}
                          {g.status === 'uitgenodigd' && !openUitnodiging && <Badge variant="warn">uitnodiging verlopen</Badge>}
                          {(g.status === 'wacht_op_totp' || g.status === 'wacht_op_passkey') && (
                            <Badge variant="warn">activatie onderbroken</Badge>
                          )}
                        </div>
                        {g.status === 'geblokkeerd' && blokkadeDetail(g)}
                        {g.status === 'gearchiveerd' && archiveringDetail(g)}
                        {openUitnodiging && <div className="cel-detail">uitnodiging {formatVerloop(g.open_uitnodiging_verloopt_op!)}</div>}
                      </td>
                      <td className="acties">{actieKolom(g, { scope: true })}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
              <Paginering pagina={pagina} totaal={gefilterd.kantoor.length} onPagina={setPagina} label="gebruikers" />
            </>
          )}
        </div>
      )}

      {groep === 'veldwerkers' && (
        <div role="tabpanel">
          {gebruikers !== null && <div className="panel" style={{ paddingBottom: 4 }}>{zoekveld}</div>}
      <VeldwerkersPanel
        gebruikers={veldwerkersPagina}
        administraties={administraties ?? []}
        onUitnodigen={() => setUitnodigSoort('veldwerker')}
        actieKolom={(g) => actieKolom(g)}
      />
          <Paginering pagina={pagina} totaal={gefilterd.veldwerkers.length} onPagina={setPagina} label="veldwerkers" />
        </div>
      )}

      {groep === 'accordeurs' && (
        <div className="panel" role="tabpanel">
          <h2 style={{ margin: 0 }}>Klant-accordeurs</h2>
          <p className="hint" style={{ marginTop: 6 }}>
            Accordeurs gebruiken de mobiele app: activeren met de link of activatiecode uit de uitnodiging, daarna een eigen
            toegangscode. Eén accordeur kan meerdere administraties bedienen —
            de wachtrij en de dagelijkse herinnering voegen alles samen.
          </p>
          {gebruikers !== null && accordeurs.length === 0 && (
            <p className="hint">Nog geen klant-accordeurs — nodig er een uit om de accorderingsflow te activeren.</p>
          )}
          {accordeurs.length > 0 && (
            <>
              {zoekveld}
          <div className="tabel-scroll sticky-koppen">
            <table className="gebruikers-tabel" style={gebruikersTabelStijl('accordeurs')} data-testid="gebruikers-tabel-accordeurs">
              <GebruikersTabelKop tab="accordeurs" />
              <tbody>
                {accordeursPagina.map((g) => {
                  const apparaten = groepeerApparaten(
                    (apparatenPer[g.id] ?? []).filter((a) => a.ingetrokken_op === null),
                  )
                  const openUitnodiging = g.status === 'uitgenodigd' && g.open_uitnodiging_verloopt_op
                  return (
                    <tr key={g.id}>
                      <td>
                        <div className="naam-met-avatar">
                          <Avatar id={g.id} naam={g.naam} klein />
                          <div style={{ minWidth: 0 }}>
                            <b>{g.naam}</b>
                            <div className="chips-regel">
                              {g.status === 'geblokkeerd' && <Badge variant="danger">geblokkeerd</Badge>}
                              {g.status === 'gearchiveerd' && <Badge variant="stil">gearchiveerd</Badge>}
                              {halfGeactiveerdBadge(g)}
                            </div>
                            {g.status === 'geblokkeerd' && blokkadeDetail(g)}
                            {g.status === 'gearchiveerd' && archiveringDetail(g)}
                            {herstelDetail(g)}
                            <div className="gebruiker-email" title={g.e_mail}>
                              {g.e_mail}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td>
                        {/* Blok 5 (08-09): scope vanuit de accordeur — toevoegen (bulk-route, accordeur vooringevuld),
                            verwijderen (vervallen-waarschuwing), namen als links naar Instellingen › ‹BV› › Klant-accordering. */}
                        <AccordeurAdministraties
                          gebruiker={g}
                          administraties={administraties ?? []}
                          naamPerAdministratie={naamPerAdministratie}
                          onGewijzigd={laad}
                        />
                      </td>
                      <td>
                        {apparaten.length === 0 && (
                          <span className="hint" style={{ margin: 0 }}>
                            {openUitnodiging ? 'wacht op activatie' : 'geen actieve apparaten'}
                          </span>
                        )}
                        {apparaten.map((groep) => (
                          <ApparaatChip key={groep.ids[0]} groep={groep} onKillSwitch={() => setKillSwitchVoor({ gebruiker: g, groep })} />
                        ))}
                      </td>
                      <td className="amount">{g.staande_goedkeuringen}</td>
                      <td className="acties">{actieKolom(g)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
              <Paginering pagina={pagina} totaal={gefilterd.accordeurs.length} onPagina={setPagina} label="accordeurs" />
            </>
          )}
          <p className="hint" style={{ marginBottom: 0 }}>
            Administraties van een accordeur beheer je via &ldquo;beheren&rdquo; in de kolom Administraties (toevoegen =
            de bulk-instelling mét deze accordeur in laag 1; verwijderen = uit de lagen én de toegang). Staande
            goedkeuringen beheren (bekijken/intrekken) en de volledige lagen instellen gebeurt per administratie onder
            Instellingen → Klant-accordering.
          </p>
        </div>
      )}

      {/* Bugfix 04-09: de dialoog wordt PER SOORT gemount (key + conditioneel) — verse rol-state per ingang, zoals de
          "+ ZZP'er"-dialoog in de planning-zijbalk al deed; nooit meer een kantoor-default die blijft hangen. */}
      {uitnodigSoort !== null && (
      <UitnodigModal
        key={uitnodigSoort}
        soort={uitnodigSoort}
        open
        administraties={administraties ?? []}
        onSluiten={() => setUitnodigSoort(null)}
        onUitgenodigd={(resultaat) => {
          const link = uitnodigSoort === 'veldwerker' && resultaat.token ? activeerLinkUrl(resultaat.token) : null
          const code = resultaat.activatiecode ?? null
          if (link || code) {
            setAanbod({ link, code, naam: uitnodigSoort === 'veldwerker' ? 'de nieuwe veldwerker' : 'de nieuwe accordeur' })
          }
          if (resultaat.mail_uitgesteld) {
            meld('Account aangemaakt zonder mail (status uitgenodigd) — nodig later uit via "Opnieuw mailen".')
          } else if (resultaat.mail_verzonden) {
            meld('Uitnodiging gemaild — zichtbaar in de lijst tot activatie.')
          } else {
            setMailFout(
              `Uitnodiging aangemaakt, maar het mailen mislukte: ${resultaat.mail_fout ?? 'onbekende mailfout'}. Gebruik "Opnieuw mailen" of deel de link handmatig.`,
            )
          }
          laad()
        }}
      />
      )}

      {scopeVoor && (
        <ScopeModal
          gebruiker={scopeVoor}
          administraties={administraties ?? []}
          onSluiten={() => setScopeVoor(null)}
          onGewijzigd={laad}
        />
      )}

      {eMailVoor && (
        <Dialog open onOpenChange={(open) => !open && !actieBezig && setEMailVoor(null)}>
          <DialogContent>
            <DialogTitle>E-mailadres wijzigen — {eMailVoor.naam}</DialogTitle>
            <DialogDescription>
              Het e-mailadres is de login.{' '}
              {eMailVoor.status === 'gearchiveerd'
                ? 'Dit account is gearchiveerd: alleen het adres wijzigt (zodat het vrijkomt voor een ander account) — er gaat géén uitnodiging uit en het account blijft gearchiveerd.'
                : eMailVoor.status === 'uitgenodigd'
                  ? 'Dit account is nog niet geactiveerd: de oude uitnodigingslink vervalt en er gaat direct een verse uitnodiging naar het nieuwe adres.'
                  : eMailVoor.status === 'geblokkeerd'
                    ? 'Dit account is geblokkeerd: alleen de login wijzigt, de blokkade blijft staan.'
                    : 'Alleen de login wijzigt — passkeys, gekoppelde toestellen, TOTP, sessies en historie blijven aan het account hangen.'}{' '}
              De wijziging wordt geauditeerd (oud → nieuw).
            </DialogDescription>
            <FormField label="Nieuw e-mailadres" htmlFor="nieuw-e-mail">
              <input id="nieuw-e-mail" type="email" value={nieuwEMail} onChange={(e) => setNieuwEMail(e.target.value)} />
            </FormField>
            {actieFout && <div className="fout">{actieFout}</div>}
            <DialogFooter>
              <Button variant="secundair" disabled={actieBezig} onClick={() => setEMailVoor(null)}>
                Annuleren
              </Button>
              <Button
                disabled={actieBezig || !nieuwEMail.includes('@') || nieuwEMail.trim().toLowerCase() === eMailVoor.e_mail}
                onClick={() => void bevestigEMailWijziging()}
              >
                {actieBezig ? 'Bezig…' : 'Wijzigen'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {rolWijziging && (
        <BevestigDialog
          titel="Rol wijzigen"
          bericht={`${rolWijziging.gebruiker.naam} krijgt de rol ${rolLabel(rolWijziging.nieuweRol)} (was ${rolLabel(rolWijziging.gebruiker.rol)}). De wijziging wordt geauditeerd.`}
          bezig={actieBezig}
          fout={actieFout}
          onBevestigen={() => void bevestigRolWijziging()}
          onAnnuleren={() => {
            setRolWijziging(null)
            setActieFout(null)
            laad()
          }}
        />
      )}

      {blokkade && (
        <BevestigDialog
          titel={blokkade.actie === 'blokkeren' ? 'Gebruiker blokkeren' : 'Gebruiker heractiveren'}
          bericht={
            blokkade.actie === 'blokkeren'
              ? `${blokkade.gebruiker.naam} wordt per direct geblokkeerd: inloggen wordt geweigerd, alle sessies vervallen en passkeys/gekoppelde toestellen zijn onbruikbaar zolang de blokkade staat. Heractiveren kan altijd — er wordt niets verwijderd. De actie wordt geauditeerd.`
              : `${blokkade.gebruiker.naam} kan na heractivering weer inloggen (bestaande passkeys en gekoppelde toestellen werken weer; oude sessies komen niet terug). De actie wordt geauditeerd.`
          }
          bezig={actieBezig}
          fout={actieFout}
          onBevestigen={() => void bevestigBlokkade()}
          onAnnuleren={() => {
            setBlokkade(null)
            setActieFout(null)
          }}
        />
      )}

      {archivering && (
        <BevestigDialog
          titel={archivering.actie === 'archiveren' ? 'Gebruiker archiveren' : 'Gebruiker dearchiveren'}
          bericht={
            archivering.actie === 'archiveren'
              ? `${archivering.gebruiker.naam} wordt gearchiveerd: verdwijnt uit alle lijsten en tabs (terug te vinden via het filter "gearchiveerd"), inloggen wordt per direct geweigerd, sessies vervallen en passkeys/gekoppelde toestellen zijn onbruikbaar. Historie, audit en akkoord-sporen blijven volledig staan — er wordt niets verwijderd. Dearchiveren kan altijd. De actie wordt geauditeerd.${openWerkTekst(openWerk)}`
              : `${archivering.gebruiker.naam} krijgt de status van vóór archivering terug (een blokkade van toen blijft dan staan). Oude sessies komen niet terug. De actie wordt geauditeerd.`
          }
          bezig={actieBezig || openWerk === 'laden'}
          fout={actieFout}
          onBevestigen={() => void bevestigArchivering()}
          onAnnuleren={() => {
            setArchivering(null)
            setActieFout(null)
          }}
        />
      )}

      {herstelVoor && (
        <BevestigDialog
          titel="Herstel-link sturen"
          bericht={`${herstelVoor.naam} (${herstelVoor.e_mail}) ontvangt een eenmalige link én activatiecode (72 uur geldig) om de app op een toestel opnieuw te koppelen en een nieuwe toegangscode te kiezen. Akkoorden en instellingen blijven staan; eerder verstuurde links vervallen en lopende sessies worden beëindigd. De actie wordt geauditeerd.`}
          bezig={actieBezig}
          fout={actieFout}
          onBevestigen={() => void bevestigHerstelLink()}
          onAnnuleren={() => {
            setHerstelVoor(null)
            setActieFout(null)
          }}
        />
      )}

      {killSwitchVoor && (
        <BevestigDialog
          titel="Kill-switch — apparaat blokkeren"
          bericht={`"${killSwitchVoor.groep.naam}" van ${killSwitchVoor.gebruiker.naam} wordt per direct geblokkeerd: ${killSwitchVoor.groep.soort === 'toestel' ? 'de toestelkoppeling' : 'de passkey'} en alle sessies van dit apparaat vervallen. Verder kan alleen met een nieuwe uitnodiging of "Herstel-link" (link of activatiecode op een toestel) — niemand raakt buitengesloten.`}
          bezig={actieBezig}
          fout={actieFout}
          onBevestigen={() => void bevestigKillSwitch()}
          onAnnuleren={() => {
            setKillSwitchVoor(null)
            setActieFout(null)
          }}
        />
      )}
    </div>
  )
}
