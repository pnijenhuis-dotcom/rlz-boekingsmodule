import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { BevestigDialog } from '../instellingen/BevestigDialog'
import { Badge, Button, Select, Switch, useToastOptioneel } from '../ui/basis'
import { FoutMelding } from '../ui/FoutMelding'
import { useAdministraties } from '../werkvoorraad/useAdministraties'
import {
  blokkeerGebruiker,
  haalApparatenVan,
  haalGebruikersOp,
  formatVerloop,
  heractiveerGebruiker,
  herstelLinkUrl,
  kanHerstelLinkKrijgen,
  mailUitnodigingOpnieuw,
  isVeldrol,
  rolLabel,
  stuurHerstelLink,
  trekApparaatIn,
  wijzigRol,
  type ApparaatDto,
  type GebruikerOverzichtDto,
} from './gebruikersApi'
import { haalModuleRechtHouders, zetModuleRecht } from '../meerwerk/meerwerkApi'
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
    else groepen.push({ naam, isDevStub: apparaat.is_dev_stub, ids: [apparaat.id] })
  }
  return groepen
}

export function GebruikersScreen() {
  const { gebruikerId, rol } = useAuth()
  const { administraties, fout: administratiesFout } = useAdministraties()
  const { meld } = useToastOptioneel()
  const [gebruikers, setGebruikers] = useState<GebruikerOverzichtDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [mailFout, setMailFout] = useState<string | null>(null)
  const [apparatenPer, setApparatenPer] = useState<Record<string, ApparaatDto[]>>({})

  const [uitnodigSoort, setUitnodigSoort] = useState<'medewerker' | 'accordeur' | 'veldwerker' | null>(null)
  const [scopeVoor, setScopeVoor] = useState<GebruikerOverzichtDto | null>(null)
  const [rolWijziging, setRolWijziging] = useState<{ gebruiker: GebruikerOverzichtDto; nieuweRol: string } | null>(
    null,
  )
  const [killSwitchVoor, setKillSwitchVoor] = useState<{ gebruiker: GebruikerOverzichtDto; groep: ApparaatGroep } | null>(null)
  const [blokkade, setBlokkade] = useState<{ gebruiker: GebruikerOverzichtDto; actie: 'blokkeren' | 'heractiveren' } | null>(null)
  const [actieBezig, setActieBezig] = useState(false)
  const [actieFout, setActieFout] = useState<string | null>(null)
  const [opnieuwBezig, setOpnieuwBezig] = useState<string | null>(null)
  const [herstelVoor, setHerstelVoor] = useState<GebruikerOverzichtDto | null>(null)

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

  const kantoor = useMemo(
    () => (gebruikers ?? []).filter((g) => g.rol !== 'klant_accordeur' && !isVeldrol(g.rol)),
    [gebruikers],
  )
  const accordeurs = useMemo(() => (gebruikers ?? []).filter((g) => g.rol === 'klant_accordeur'), [gebruikers])
  const veldwerkers = useMemo(() => (gebruikers ?? []).filter((g) => isVeldrol(g.rol)), [gebruikers])
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

  /** "Herstel-link sturen" (feedbackronde 25-08 punt 7): actieve accordeur/veldwerker die zijn
   * wachtwoord kwijt is (bv. ná een kill-switch) krijgt een eenmalige 72-uurs link — nieuw
   * wachtwoord + apparaat registreren; passkeys/akkoorden blijven, oudere links vervallen.
   * Fail-zichtbaar: mislukt de mail, dan staat de link hier om handmatig te delen. */
  async function bevestigHerstelLink() {
    if (!herstelVoor) return
    setActieBezig(true)
    setActieFout(null)
    setMailFout(null)
    try {
      const resultaat = await stuurHerstelLink(herstelVoor.id)
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

  /** Knop in de actiekolom van accordeurs/veldwerkers — alleen bij een account dat een
   * wachtwoord heeft gehad (server-side dezelfde poort; geblokkeerd = eerst heractiveren). */
  function herstelKnop(g: GebruikerOverzichtDto) {
    if (!kanHerstelLinkKrijgen(g)) return null
    return (
      <Button variant="secundair" maat="klein" onClick={() => setHerstelVoor(g)}>
        Herstel-link
      </Button>
    )
  }

  function herstelBadge(g: GebruikerOverzichtDto) {
    if (!g.open_herstel_verloopt_op) return null
    return (
      <>
        {' '}
        <Badge variant="stil">herstel-link — {formatVerloop(g.open_herstel_verloopt_op)}</Badge>
      </>
    )
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

  /** Blokkeer-/heractiveer-knop in de actiekolom — nooit bij het eigen account (server-side
   * eveneens geweigerd; de UI biedt de onmogelijke actie niet aan). */
  function blokkadeKnop(g: GebruikerOverzichtDto) {
    if (g.id === gebruikerId) return null
    if (g.status === 'geblokkeerd') {
      return (
        <Button variant="secundair" maat="klein" onClick={() => setBlokkade({ gebruiker: g, actie: 'heractiveren' })}>
          Heractiveren
        </Button>
      )
    }
    return (
      <Button variant="warn-omlijnd" maat="klein" onClick={() => setBlokkade({ gebruiker: g, actie: 'blokkeren' })}>
        Blokkeren
      </Button>
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

  return (
    <div>
      <div className="topbar">
        <div>
          <h1>Gebruikers &amp; toegang</h1>
          <div style={{ color: 'var(--muted)', fontSize: 12.5, marginTop: 3 }}>
            Medewerkers, rollen, administratie-scope en apparaten — met audit op elke wijziging.
          </div>
        </div>
        <Button onClick={() => setUitnodigSoort('medewerker')}>+ Medewerker uitnodigen</Button>
      </div>

      {fout && <FoutMelding melding="De gebruikerslijst kon niet geladen worden." detail={fout} onOpnieuw={laad} />}
      {mailFout && <FoutMelding melding={mailFout} />}
      {administratiesFout && <FoutMelding melding="Administraties konden niet geladen worden." detail={administratiesFout} />}

      <div className="panel">
        <h2>Kantoorgebruikers</h2>
        {gebruikers === null && !fout && (
          <div aria-busy="true">
            <span className="skeleton" style={{ width: '55%', marginBottom: 8 }} />
            <span className="skeleton" style={{ width: '40%' }} />
          </div>
        )}
        {gebruikers !== null && (
          <div className="tabel-scroll sticky-koppen">
            <table>
              <tbody>
                <tr>
                  <th>Gebruiker</th>
                  <th>Rol</th>
                  <th>Scope</th>
                  <th>Meerwerk &amp; urenstaten</th>
                  <th>Beveiliging</th>
                  <th>Status</th>
                  <th />
                </tr>
                {kantoor.map((g) => {
                  const isZelf = g.id === gebruikerId
                  const openUitnodiging = g.status === 'uitgenodigd' && g.open_uitnodiging_verloopt_op
                  return (
                    <tr key={g.id}>
                      <td>
                        <b>{g.naam}</b>
                        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{g.e_mail}</div>
                      </td>
                      <td>
                        {isZelf ? (
                          <Badge variant="paars">{rolLabel(g.rol)}</Badge>
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
                      </td>
                      <td>
                        {g.rol === 'beheerder' ? (
                          <Badge variant="stil">alle administraties</Badge>
                        ) : (
                          <>
                            <Badge variant="info">
                              {g.administratie_ids.length}{' '}
                              {g.administratie_ids.length === 1 ? 'administratie' : 'administraties'}
                            </Badge>{' '}
                            {!isZelf && (
                              <Button variant="ghost" maat="klein" onClick={() => setScopeVoor(g)}>
                                wijzig
                              </Button>
                            )}
                          </>
                        )}
                      </td>
                      <td>
                        {g.rol === 'beheerder' ? (
                          <span className="hint" style={{ margin: 0, fontSize: 11.5 }}>
                            altijd (Beheerder)
                          </span>
                        ) : (
                          <Switch
                            aria-label={`Meerwerk & urenstaten voor ${g.naam}`}
                            checked={rechtHouders.has(g.id)}
                            disabled={rechtBezig === g.id}
                            onChange={(e) => void toggleMeerwerkRecht(g, e.target.checked)}
                          />
                        )}
                      </td>
                      <td>
                        {g.aantal_passkeys > 0 && (
                          <span className="apparaat-chip">
                            🔑 {g.aantal_passkeys} passkey{g.aantal_passkeys === 1 ? '' : 's'}
                          </span>
                        )}{' '}
                        {g.heeft_totp ? (
                          <span className="apparaat-chip">🔐 TOTP</span>
                        ) : (
                          g.status === 'actief' && <Badge variant="warn">geen TOTP</Badge>
                        )}
                        {g.aantal_passkeys === 0 && g.status === 'actief' && (
                          <>
                            {' '}
                            <Badge variant="warn">geen passkey</Badge>
                          </>
                        )}
                      </td>
                      <td>
                        {g.status === 'actief' && <Badge variant="ok">actief</Badge>}
                        {g.status === 'geblokkeerd' && (
                          <>
                            <Badge variant="danger">geblokkeerd</Badge>
                            {blokkadeDetail(g)}
                          </>
                        )}
                        {openUitnodiging && (
                          <Badge variant="stil">uitnodiging — {formatVerloop(g.open_uitnodiging_verloopt_op!)}</Badge>
                        )}
                        {g.status === 'uitgenodigd' && !openUitnodiging && (
                          <Badge variant="warn">uitnodiging verlopen</Badge>
                        )}
                        {(g.status === 'wacht_op_totp' || g.status === 'wacht_op_passkey') && (
                          <Badge variant="warn">activatie onderbroken</Badge>
                        )}
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {g.status === 'uitgenodigd' && (
                          <Button
                            variant="secundair"
                            maat="klein"
                            disabled={opnieuwBezig === g.id}
                            onClick={() => void opnieuwMailen(g)}
                          >
                            {opnieuwBezig === g.id ? 'Bezig…' : 'Opnieuw mailen'}
                          </Button>
                        )}
                        {isZelf && (
                          <span
                            className="hint"
                            style={{ margin: 0, fontSize: 11.5, whiteSpace: 'normal', display: 'inline-block', maxWidth: 180 }}
                          >
                            eigen rol/scope wijzigt alleen een ándere Beheerder
                          </span>
                        )}{' '}
                        {blokkadeKnop(g)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <VeldwerkersPanel
        gebruikers={veldwerkers}
        administraties={administraties ?? []}
        onUitnodigen={() => setUitnodigSoort('veldwerker')}
        actieKolom={(g) => (
          <>
            {g.status === 'uitgenodigd' && (
              <Button
                variant="secundair"
                maat="klein"
                disabled={opnieuwBezig === g.id}
                onClick={() => void opnieuwMailen(g)}
              >
                {opnieuwBezig === g.id ? 'Bezig…' : 'Opnieuw mailen'}
              </Button>
            )}{' '}
            {herstelKnop(g)}
            {herstelBadge(g)}{' '}
            {blokkadeKnop(g)}
          </>
        )}
      />

      <div className="panel">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0 }}>Klant-accordeurs</h2>
          <div style={{ marginLeft: 'auto' }}>
            <Button variant="secundair" maat="klein" onClick={() => setUitnodigSoort('accordeur')}>
              + Accordeur uitnodigen
            </Button>
          </div>
        </div>
        <p className="hint" style={{ marginTop: 6 }}>
          Accordeurs gebruiken de mobiele app met passkey. Eén accordeur kan meerdere administraties bedienen —
          de wachtrij en de dagelijkse herinnering voegen alles samen.
        </p>
        {gebruikers !== null && accordeurs.length === 0 && (
          <p className="hint">Nog geen klant-accordeurs — nodig er een uit om de accorderingsflow te activeren.</p>
        )}
        {accordeurs.length > 0 && (
          <div className="tabel-scroll sticky-koppen">
            <table>
              <tbody>
                <tr>
                  <th>Accordeur</th>
                  <th>Administraties</th>
                  <th>Apparaten</th>
                  <th>Staande goedkeuringen</th>
                  <th />
                </tr>
                {accordeurs.map((g) => {
                  const apparaten = groepeerApparaten(
                    (apparatenPer[g.id] ?? []).filter((a) => a.ingetrokken_op === null),
                  )
                  const openUitnodiging = g.status === 'uitgenodigd' && g.open_uitnodiging_verloopt_op
                  return (
                    <tr key={g.id}>
                      <td>
                        <b>{g.naam}</b>
                        {g.status === 'geblokkeerd' && (
                          <>
                            {' '}
                            <Badge variant="danger">geblokkeerd</Badge>
                            {blokkadeDetail(g)}
                          </>
                        )}
                        {herstelBadge(g)}
                        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{g.e_mail}</div>
                      </td>
                      <td>
                        {g.administratie_ids.length === 0 && '—'}
                        {g.administratie_ids.map((id) => (
                          <span key={id}>
                            <Badge variant="info">{naamPerAdministratie.get(id) ?? id}</Badge>{' '}
                          </span>
                        ))}
                      </td>
                      <td>
                        {apparaten.length === 0 && (
                          <span className="hint" style={{ margin: 0 }}>
                            {openUitnodiging ? 'wacht op activatie' : 'geen actieve apparaten'}
                          </span>
                        )}
                        {apparaten.map((groep) => (
                          <span key={groep.ids[0]} style={{ whiteSpace: 'nowrap' }}>
                            <span className="apparaat-chip">
                              📱 {groep.naam}
                              {groep.isDevStub ? ' (dev-stub)' : ''}
                            </span>{' '}
                            <Button
                              variant="ghost"
                              maat="klein"
                              onClick={() => setKillSwitchVoor({ gebruiker: g, groep })}
                            >
                              Kill-switch
                            </Button>{' '}
                          </span>
                        ))}
                      </td>
                      <td className="amount">{g.staande_goedkeuringen}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {g.status === 'uitgenodigd' && (
                          <Button
                            variant="secundair"
                            maat="klein"
                            disabled={opnieuwBezig === g.id}
                            onClick={() => void opnieuwMailen(g)}
                          >
                            {opnieuwBezig === g.id ? 'Bezig…' : 'Opnieuw mailen'}
                          </Button>
                        )}{' '}
                        {herstelKnop(g)}{' '}
                        {blokkadeKnop(g)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="hint" style={{ marginBottom: 0 }}>
          Staande goedkeuringen beheren (bekijken/intrekken) en accorderingslagen instellen gebeurt per
          administratie onder Instellingen → accordering.
        </p>
      </div>

      <UitnodigModal
        soort={uitnodigSoort ?? 'medewerker'}
        open={uitnodigSoort !== null}
        administraties={administraties ?? []}
        onSluiten={() => setUitnodigSoort(null)}
        onUitgenodigd={(resultaat) => {
          if (resultaat.mail_verzonden) {
            meld('Uitnodiging gemaild — zichtbaar in de lijst tot activatie.')
          } else {
            setMailFout(
              `Uitnodiging aangemaakt, maar het mailen mislukte: ${resultaat.mail_fout ?? 'onbekende mailfout'}. Gebruik "Opnieuw mailen" of deel de link handmatig.`,
            )
          }
          laad()
        }}
      />

      {scopeVoor && (
        <ScopeModal
          gebruiker={scopeVoor}
          administraties={administraties ?? []}
          onSluiten={() => setScopeVoor(null)}
          onGewijzigd={laad}
        />
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
              ? `${blokkade.gebruiker.naam} wordt per direct geblokkeerd: inloggen wordt geweigerd, alle sessies vervallen en passkeys zijn onbruikbaar zolang de blokkade staat. Heractiveren kan altijd — er wordt niets verwijderd. De actie wordt geauditeerd.`
              : `${blokkade.gebruiker.naam} kan na heractivering weer inloggen (bestaande passkeys werken weer; oude sessies komen niet terug). De actie wordt geauditeerd.`
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

      {herstelVoor && (
        <BevestigDialog
          titel="Herstel-link sturen"
          bericht={`${herstelVoor.naam} (${herstelVoor.e_mail}) ontvangt een eenmalige link (72 uur geldig) om een nieuw wachtwoord in te stellen en daarna een apparaat te registreren. Bestaande passkeys en akkoorden blijven staan; eerder verstuurde links vervallen en lopende sessies worden beëindigd. De actie wordt geauditeerd.`}
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
          bericht={`"${killSwitchVoor.groep.naam}" van ${killSwitchVoor.gebruiker.naam} wordt per direct geblokkeerd: de passkey en alle sessies van dit apparaat vervallen. De accordeur kan met wachtwoord + nieuwe registratie weer verder — niemand raakt buitengesloten (wachtwoord kwijt? "Herstel-link").`}
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
