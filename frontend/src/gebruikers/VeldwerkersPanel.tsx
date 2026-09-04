import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ApiError, apiJson } from '../api/client'
import type { AdministratieDto } from '../api/types'
import {
  haalVeldgebruikers,
  koppelDetacheerder,
  koppelVeldwerkerCrediteur,
  ontkoppelDetacheerder,
  ontkoppelVeldwerkerCrediteur,
  zetDetacheerderTarief,
  zetVeldwerkerAutoboeken,
  type VeldgebruikerDto,
} from '../meerwerk/meerwerkApi'
import type { VendorLijstDto } from '../api/types'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  FormField,
  MultiSelect,
  Select,
  Switch,
  useToastOptioneel,
} from '../ui/basis'
import { AdministratieCombobox } from '../ui/AdministratieCombobox'
import { DossierModal, dossierBadge } from './DossierModal'
import {
  formatVerloop, rolLabel, type GebruikerOverzichtDto } from './gebruikersApi'

/* Veldwerkers-paneel (Gebruikers & toegang, fase 3 uren & meerwerk — mockup meerwerk-kantoor
 * "Gebruikers & toegang" + bouwopdracht 21-08): kantoor beheert hier de koppeling detacheerder↔zzp'er,
 * crediteur + tarieven — Beheerder-only, elke wijziging in het audit_event. De projecttoegang van
 * ZZP'ers/uitvoerders is sinds het addendum Peter 04-09 (C1/C2) volledig PLANNING-GESTUURD: de
 * koppeling ontstaat bij plannen (bron 'planning') of bij uren buiten planning ("+ ander project",
 * bron 'weekstaat'); het paneel toont die afgeleide toegang alleen-lezen ("actief op N projecten
 * (via planning)" mét uitklap). Bestaande handmatige koppelingen blijven staan, er komen geen nieuwe bij. */

export function VeldwerkersPanel({
  gebruikers,
  administraties,
  onUitnodigen,
  actieKolom,
}: {
  /** De veldrol-gebruikers uit de algemene gebruikerslijst (status/uitnodiging/blokkade). */
  gebruikers: GebruikerOverzichtDto[]
  administraties: AdministratieDto[]
  onUitnodigen: () => void
  /** Actiekolom (opnieuw mailen / blokkeren) — gedeeld met de andere panelen. */
  actieKolom: (g: GebruikerOverzichtDto) => ReactNode
}) {
  const { meld } = useToastOptioneel()
  const [veld, setVeld] = useState<VeldgebruikerDto[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [projectenUitgeklapt, setProjectenUitgeklapt] = useState<Set<string>>(() => new Set())
  const [zzperModal, setZzperModal] = useState<VeldgebruikerDto | null>(null)
  const [crediteurModal, setCrediteurModal] = useState<VeldgebruikerDto | null>(null)
  const [tarievenModal, setTarievenModal] = useState<VeldgebruikerDto | null>(null)
  const [dossierModal, setDossierModal] = useState<VeldgebruikerDto | null>(null)

  const laad = useCallback(() => {
    setFout(null)
    haalVeldgebruikers()
      .then(setVeld)
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [])

  useEffect(() => {
    laad()
  }, [laad, gebruikers])

  const veldPer = new Map((veld ?? []).map((v) => [v.gebruiker_id, v]))

  return (
    <div className="panel">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>Veldwerkers — uren &amp; meerwerk</h2>
        <div style={{ marginLeft: 'auto' }}>
          <Button variant="secundair" maat="klein" onClick={onUitnodigen}>
            + Veldwerker uitnodigen
          </Button>
        </div>
      </div>
      <p className="hint" style={{ marginTop: 6 }}>
        ZZP'ers schrijven weekstaten, uitvoerders keuren per week, detacheerders vullen in namens gekoppelde
        ZZP'ers — crediteur + tarieven voeden de factuurmatch.
      </p>
      {fout && <div className="fout">{fout}</div>}
      {gebruikers.length === 0 && (
        <p className="hint">Nog geen veldwerkers — nodig een ZZP'er, uitvoerder of detacheerder uit.</p>
      )}
      {gebruikers.length > 0 && (
        <div className="tabel-scroll">
          <table>
            <tbody>
              <tr>
                <th>Veldwerker</th>
                <th>Rol</th>
                <th>Koppelingen</th>
                <th>Status</th>
                <th className="acties" />
              </tr>
              {gebruikers.map((g) => {
                const info = veldPer.get(g.id)
                return (
                  <tr key={g.id}>
                    <td>
                      <b>{g.naam}</b>
                      <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>{g.e_mail}</div>
                    </td>
                    <td>
                      <Badge variant="paars">{rolLabel(g.rol)}</Badge>
                    </td>
                    <td>
                      {g.rol !== 'detacheerder' && info !== undefined && (
                        <ProjectToegang
                          info={info}
                          rol={g.rol}
                          uitgeklapt={projectenUitgeklapt.has(g.id)}
                          toggle={() =>
                            setProjectenUitgeklapt((huidig) => {
                              const volgende = new Set(huidig)
                              if (volgende.has(g.id)) volgende.delete(g.id)
                              else volgende.add(g.id)
                              return volgende
                            })
                          }
                        />
                      )}
                      {g.rol === 'detacheerder' && (
                        <>
                          {(info?.zzpers ?? []).map((z) => (
                            <span key={z.gebruiker_id}>
                              <Badge variant="info">
                                {z.naam}
                                {z.uurtarief !== null ? ` · ${tariefLabel(z.uurtarief)}` : ' · geen tarief'}
                              </Badge>{' '}
                            </span>
                          ))}
                          {info !== undefined && (
                            <Button variant="ghost" maat="klein" onClick={() => setZzperModal(info)}>
                              {info.zzpers.length === 0 ? "ZZP'ers koppelen" : 'wijzig'}
                            </Button>
                          )}
                          {info !== undefined && info.zzpers.length > 0 && (
                            <Button variant="ghost" maat="klein" onClick={() => setTarievenModal(info)}>
                              tarieven…
                            </Button>
                          )}
                        </>
                      )}
                      {info !== undefined && g.rol !== 'uitvoerder' && (
                        <div style={{ marginTop: 4 }}>
                          {info.crediteuren.map((c) => (
                            <span key={`${c.administratie_id}-${c.vendor_id}`}>
                              <Badge variant="stil">
                                € {c.vendor_naam ?? c.vendor_id}
                                {c.uurtarief !== null && ` · ${tariefLabel(c.uurtarief)}`}
                              </Badge>{' '}
                              {c.autoboeken_ingeschakeld && (
                                <Badge variant="ok" title="Autoboeken bij een groene urenmatch (fase 4) staat aan voor deze koppeling">
                                  ⚡ autoboeken
                                </Badge>
                              )}{' '}
                            </span>
                          ))}
                          <Button variant="ghost" maat="klein" onClick={() => setCrediteurModal(info)}>
                            {info.crediteuren.length === 0 ? 'crediteur koppelen' : 'crediteur/tarief'}
                          </Button>
                          {info.crediteuren.length === 0 && (
                            <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                              zonder crediteur-koppeling geen factuurmatch
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    <td>
                      {g.status === 'actief' && <Badge variant="ok">actief</Badge>}
                      {g.status === 'geblokkeerd' && <Badge variant="danger">geblokkeerd</Badge>}
                      {g.status === 'gearchiveerd' && <Badge variant="stil">gearchiveerd</Badge>}
                      {g.status === 'uitgenodigd' && <Badge variant="stil">uitgenodigd</Badge>}
                      {g.status === 'wacht_op_passkey' && <Badge variant="warn">activatie onderbroken</Badge>}
                      {g.half_geactiveerd && (
                        <Badge variant="warn" title="Wachtwoord staat, passkey ontbreekt — stuur een herstel-link">
                          half geactiveerd — geen passkey
                        </Badge>
                      )}
                      {g.open_herstel_verloopt_op && (
                        <Badge variant="stil">herstel-link — {formatVerloop(g.open_herstel_verloopt_op)}</Badge>
                      )}
                      {/* ZZP-dossier (A1, 25-08 — mockup: "📁 dossier 4/6"): klik opent het dossier. */}
                      {info !== undefined && g.rol !== 'detacheerder' && (() => {
                        const badge = dossierBadge(info)
                        return (
                          <>
                            {' '}
                            <button
                              type="button"
                              className="linkbtn"
                              style={{ padding: 0 }}
                              onClick={() => setDossierModal(info)}
                              title="ZZP-dossier openen (documenten, KvK/btw, herinneringen)"
                            >
                              {badge ? <Badge variant={badge.variant}>{badge.label}</Badge> : <Badge variant="stil">📁 dossier</Badge>}
                            </button>
                          </>
                        )
                      })()}
                      {info !== undefined && info.uren_afwijking_aantal > 0 && (
                        <div
                          style={{ fontSize: 11, color: 'var(--warn)', marginTop: 2 }}
                          title="Afkeuringen mét correctievoorstel; delta = ingediend − uiteindelijk goedgekeurd. Alleen zichtbaar voor kantoor — de veldwerker ziet dit niet."
                        >
                          ⚠ {info.uren_afwijking_aantal}× correctie bij keuring ·{' '}
                          {Number(info.uren_afwijking_som).toLocaleString('nl-NL', { maximumFractionDigits: 2 })} u
                          meer ingediend dan goedgekeurd
                        </div>
                      )}
                    </td>
                    <td className="acties" style={{ whiteSpace: 'nowrap' }}>
                      {actieKolom(g)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {zzperModal && (
        <DetacheerderKoppelModal
          detacheerder={zzperModal}
          zzpers={(veld ?? []).filter((v) => v.rol === 'zzper')}
          onSluiten={() => setZzperModal(null)}
          onGewijzigd={() => {
            meld("ZZP'er-koppelingen bijgewerkt — geauditeerd.")
            laad()
          }}
        />
      )}
      {crediteurModal && (
        <CrediteurModal
          veldwerker={crediteurModal}
          administraties={administraties}
          onSluiten={() => setCrediteurModal(null)}
          onGewijzigd={() => {
            meld('Crediteur-koppeling bijgewerkt — geauditeerd.')
            laad()
          }}
        />
      )}
      {dossierModal && (
        <DossierModal
          veldwerker={dossierModal}
          administraties={administraties}
          onSluiten={() => setDossierModal(null)}
          onGewijzigd={laad}
        />
      )}
      {tarievenModal && (
        <BureauTarievenModal
          detacheerder={tarievenModal}
          onSluiten={() => setTarievenModal(null)}
          onGewijzigd={() => {
            meld('Bureau-tarieven bijgewerkt — geauditeerd.')
            laad()
          }}
        />
      )}
    </div>
  )
}

function tariefLabel(uurtarief: string): string {
  return `€ ${Number(uurtarief).toLocaleString('nl-NL', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}/u`
}

const BRON_LABEL: Record<string, string> = { planning: 'via planning', weekstaat: 'via uren buiten planning', handmatig: 'handmatig (vóór 04-09)' }

/** Afgeleide projecttoegang, alleen-lezen (C2 04-09): "actief op N projecten (via planning)" mét uitklap
 * per project + herkomst. Geen selectie-UI meer — koppelingen ontstaan uitsluitend via de planning
 * (of uren buiten planning); bestaande handmatige koppelingen blijven zichtbaar en staan. */
function ProjectToegang({
  info,
  rol,
  uitgeklapt,
  toggle,
}: {
  info: VeldgebruikerDto
  rol: string
  uitgeklapt: boolean
  toggle: () => void
}) {
  const aantal = info.projecten.length
  const viaPlanning = info.projecten.filter((t) => t.bron === 'planning').length
  if (aantal === 0) {
    return (
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>
        nog geen projecten — toegang ontstaat zodra deze {rol === 'zzper' ? "ZZP'er" : 'uitvoerder'} in de planning staat
      </div>
    )
  }
  return (
    <div>
      <button type="button" className="linkbtn" onClick={toggle} aria-expanded={uitgeklapt} data-testid="projecttoegang">
        actief op {aantal} {aantal === 1 ? 'project' : 'projecten'}
        {viaPlanning === aantal ? ' (via planning)' : viaPlanning > 0 ? ` (${viaPlanning} via planning)` : ''} {uitgeklapt ? '▾' : '▸'}
      </button>
      {uitgeklapt && (
        <ul style={{ margin: '4px 0 0', paddingLeft: 16, fontSize: 12 }}>
          {info.projecten.map((t) => (
            <li key={`${t.administratie_id}-${t.project_id}`}>
              {t.project_naam ?? t.project_id}
              {t.administratie_naam ? ` · ${t.administratie_naam}` : ''}{' '}
              <Badge variant="stil">{BRON_LABEL[t.bron] ?? t.bron}</Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function DetacheerderKoppelModal({
  detacheerder,
  zzpers,
  onSluiten,
  onGewijzigd,
}: {
  detacheerder: VeldgebruikerDto
  zzpers: VeldgebruikerDto[]
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const huidige = detacheerder.zzpers.map((z) => z.gebruiker_id)
  const [selectie, setSelectie] = useState<string[]>(huidige)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const erbij = selectie.filter((id) => !huidige.includes(id))
  const eraf = huidige.filter((id) => !selectie.includes(id))

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      for (const zzperId of erbij) await koppelDetacheerder(detacheerder.gebruiker_id, zzperId)
      for (const zzperId of eraf) await ontkoppelDetacheerder(detacheerder.gebruiker_id, zzperId)
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Koppelen mislukt.')
      onGewijzigd()
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>ZZP'ers van {detacheerder.naam}</DialogTitle>
        <DialogDescription>
          De detacheerder vult weekstaten in NAMENS deze ZZP'ers — exact dezelfde schermen en velden; elke invoer
          wordt vastgelegd als "ingevuld door {detacheerder.naam} namens …" (zichtbaar bij de keuring en in het
          audit-log). Projectinhoud (specs, contract, meerwerk) ziet een detacheerder nooit.
        </DialogDescription>
        {zzpers.length === 0 && <p className="hint">Er zijn nog geen ZZP'ers om te koppelen.</p>}
        <MultiSelect
          opties={zzpers.map((z) => ({ waarde: z.gebruiker_id, label: z.naam }))}
          waarden={selectie}
          onChange={setSelectie}
          zoekPlaceholder="Zoek ZZP'er…"
        />
        {(erbij.length > 0 || eraf.length > 0) && (
          <p className="hint">
            {erbij.length > 0 && `${erbij.length} erbij`}
            {erbij.length > 0 && eraf.length > 0 && ' · '}
            {eraf.length > 0 && `${eraf.length} eraf`}
          </p>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void opslaan()} disabled={bezig || (erbij.length === 0 && eraf.length === 0)}>
            {bezig ? 'Bezig…' : 'Koppelingen opslaan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Crediteur-koppeling + los ZZP-uurtarief per administratie (factuurmatch fase 3, besluiten
 * Peter 21-08): welke RLZ-crediteur factureert het werk van deze veldwerker. Eén crediteur
 * per veldwerker per administratie (upsert); het uurtarief hoort alleen bij een ZZP'er —
 * bureau-tarieven staan per detacheerder↔zzp'er-koppeling (BureauTarievenModal). */
function CrediteurModal({
  veldwerker,
  administraties,
  onSluiten,
  onGewijzigd,
}: {
  veldwerker: VeldgebruikerDto
  administraties: AdministratieDto[]
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const [administratieId, setAdministratieId] = useState(
    veldwerker.crediteuren[0]?.administratie_id ?? administraties[0]?.id ?? '',
  )
  const [crediteuren, setCrediteuren] = useState<{ id: string; naam: string | null }[] | null>(null)
  const huidige = veldwerker.crediteuren.find((c) => c.administratie_id === administratieId) ?? null
  const [vendorId, setVendorId] = useState('')
  const [tarief, setTarief] = useState('')
  // Lokale spiegel van de autoboek-opt-in: de prop is een momentopname (de lijst herlaadt op
  // de achtergrond terwijl de modal openstaat) — pas ná een geslaagde server-call bijgewerkt.
  const [autoboeken, setAutoboeken] = useState(huidige?.autoboeken_ingeschakeld ?? false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    if (!administratieId) return
    const koppeling = veldwerker.crediteuren.find((c) => c.administratie_id === administratieId) ?? null
    setVendorId(koppeling?.vendor_id ?? '')
    setTarief(koppeling?.uurtarief ?? '')
    setAutoboeken(koppeling?.autoboeken_ingeschakeld ?? false)
    setCrediteuren(null)
    setFout(null)
    apiJson<VendorLijstDto>(`/administraties/${administratieId}/crediteuren`)
      .then((data) => setCrediteuren(data.crediteuren))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Crediteuren laden mislukt'))
    // veldwerker verandert niet tijdens een open modal
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administratieId])

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      await koppelVeldwerkerCrediteur({
        administratie_id: administratieId,
        gebruiker_id: veldwerker.gebruiker_id,
        vendor_id: vendorId,
        uurtarief: veldwerker.rol === 'zzper' && tarief.trim() !== '' ? tarief.replace(',', '.') : null,
      })
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Koppelen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  async function ontkoppelen() {
    setBezig(true)
    setFout(null)
    try {
      await ontkoppelVeldwerkerCrediteur(administratieId, veldwerker.gebruiker_id)
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Ontkoppelen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  async function wisselAutoboeken(ingeschakeld: boolean) {
    setBezig(true)
    setFout(null)
    try {
      await zetVeldwerkerAutoboeken(administratieId, veldwerker.gebruiker_id, ingeschakeld)
      setAutoboeken(ingeschakeld) // pas ná de geslaagde server-call — nooit optimistisch
      onGewijzigd()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Autoboeken wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>Crediteur van {veldwerker.naam}</DialogTitle>
        <DialogDescription>
          Facturen van deze crediteur worden automatisch gematcht tegen de goedgekeurde urenstaten
          {veldwerker.rol === 'zzper'
            ? ' van deze ZZP’er (uren × uurtarief; zonder tarief alleen op uren — oranje).'
            : ' van de aan dit bureau gekoppelde ZZP’ers (uren × bureau-tarief per ZZP’er — knop "tarieven…").'}{' '}
          Eén veldwerker per crediteur; elke wijziging wordt geauditeerd.
        </DialogDescription>
        <AdministratieCombobox
          label="Administratie"
          administraties={administraties}
          waarde={administratieId}
          onWijzig={setAdministratieId}
        />
        {crediteuren === null && !fout && <p className="hint">Crediteuren laden…</p>}
        {crediteuren !== null && (
          <FormField label="Crediteur (uit Reeleezee)" htmlFor="crediteur-vendor">
            <Select
              id="crediteur-vendor"
              className="w-full"
              value={vendorId}
              onChange={(e) => setVendorId(e.target.value)}
            >
              <option value="">— kies een crediteur —</option>
              {crediteuren.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.naam ?? c.id}
                </option>
              ))}
            </Select>
          </FormField>
        )}
        {veldwerker.rol === 'zzper' && (
          <FormField label="Uurtarief (optioneel — zonder tarief matcht alleen op uren)" htmlFor="crediteur-tarief">
            <input
              id="crediteur-tarief"
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              placeholder="bijv. 42,50"
              value={tarief}
              onChange={(e) => setTarief(e.target.value)}
            />
          </FormField>
        )}
        {/* Factuurmatch fase 4 (besluit 4, 21-08): autoboek-opt-in per koppeling — default
            UIT, direct effect (eigen audit-actie, los van de opslaan-knop). Het slot blijft
            strikt: alleen een GROENE match incl. bedrag + alle bestaande autoboek-poorten. */}
        {huidige !== null && (
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 10,
              padding: '10px 12px',
              border: '1px solid var(--border)',
              borderRadius: 8,
            }}
          >
            <Switch
              id="crediteur-autoboeken"
              aria-label="Automatisch boeken bij een groene urenmatch"
              checked={autoboeken}
              disabled={bezig}
              onChange={(e) => void wisselAutoboeken(e.target.checked)}
            />
            <label htmlFor="crediteur-autoboeken" style={{ fontSize: 12.5, lineHeight: 1.5 }}>
              <b>Automatisch boeken bij een groene urenmatch</b>
              <span style={{ display: 'block', color: 'var(--muted)' }}>
                Boekt uitsluitend als de match GROEN is inclusief bedrag (tarief dus ingevuld) én alle vaste
                autoboek-poorten slagen (harde checks, bevestigd boekingsgeheugen, geen duplicaat/vraag,
                volumerem, accordering). Elke boeking draagt de markering &quot;automatisch&quot;; storno blijft de
                terugweg. Wijziging werkt per direct en wordt geauditeerd.
              </span>
            </label>
          </div>
        )}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          {huidige !== null && (
            <Button variant="secundair" onClick={() => void ontkoppelen()} disabled={bezig}>
              Ontkoppelen
            </Button>
          )}
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void opslaan()} disabled={bezig || vendorId === ''}>
            {bezig ? 'Bezig…' : 'Opslaan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/** Bureau-tarief per detacheerder↔zzp'er-koppeling (besluit 1, 21-08: hét hoofdmechanisme van
 * de bureaufactuurmatch — bureaus factureren per ZZP'er verschillende tarieven). Leeg laten =
 * "geen tarief bekend" (match alleen op uren, oranje — geen blokkade). */
function BureauTarievenModal({
  detacheerder,
  onSluiten,
  onGewijzigd,
}: {
  detacheerder: VeldgebruikerDto
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const [tarieven, setTarieven] = useState<Record<string, string>>(() =>
    Object.fromEntries(detacheerder.zzpers.map((z) => [z.gebruiker_id, z.uurtarief ?? ''])),
  )
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const gewijzigd = detacheerder.zzpers.filter((z) => (z.uurtarief ?? '') !== (tarieven[z.gebruiker_id] ?? ''))

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      for (const z of gewijzigd) {
        const waarde = (tarieven[z.gebruiker_id] ?? '').trim()
        await zetDetacheerderTarief(
          detacheerder.gebruiker_id,
          z.gebruiker_id,
          waarde === '' ? null : waarde.replace(',', '.'),
        )
      }
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Tarieven opslaan mislukt.')
      onGewijzigd()
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>Bureau-tarieven van {detacheerder.naam}</DialogTitle>
        <DialogDescription>
          Het tarief per gekoppelde ZZP'er — de bureaufactuur wordt gematcht op de som van
          (goedgekeurde uren × tarief) per ZZP'er. Leeg = geen tarief bekend: match alleen op uren (oranje).
        </DialogDescription>
        {detacheerder.zzpers.map((z) => (
          <FormField key={z.gebruiker_id} label={z.naam} htmlFor={`tarief-${z.gebruiker_id}`}>
            <input
              id={`tarief-${z.gebruiker_id}`}
              type="number"
              inputMode="decimal"
              min="0"
              step="0.01"
              placeholder="geen tarief bekend"
              value={tarieven[z.gebruiker_id] ?? ''}
              onChange={(e) => setTarieven((t) => ({ ...t, [z.gebruiker_id]: e.target.value }))}
            />
          </FormField>
        ))}
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void opslaan()} disabled={bezig || gewijzigd.length === 0}>
            {bezig ? 'Bezig…' : 'Tarieven opslaan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
