import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { ApiError, apiJson } from '../api/client'
import type { AdministratieDto, ProjectLijstDto } from '../api/types'
import {
  haalVeldgebruikers,
  koppelDetacheerder,
  koppelProject,
  ontkoppelDetacheerder,
  ontkoppelProject,
  type VeldgebruikerDto,
} from '../meerwerk/meerwerkApi'
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
  useToastOptioneel,
} from '../ui/basis'
import { rolLabel, type GebruikerOverzichtDto } from './gebruikersApi'

/* Veldwerkers-paneel (Gebruikers & toegang, fase 3 uren & meerwerk — mockup meerwerk-kantoor
 * "Gebruikers & toegang" + bouwopdracht 21-08): kantoor beheert hier de koppelingen
 * uitvoerder↔project (keurrecht) en detacheerder↔zzp'er — Beheerder-only, elke wijziging in
 * het audit_event. ZZP'ers krijgen hier ook hun project-toewijzing (schrijfrecht weekstaten). */

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
  const [projectModal, setProjectModal] = useState<VeldgebruikerDto | null>(null)
  const [zzperModal, setZzperModal] = useState<VeldgebruikerDto | null>(null)

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
        ZZP'ers schrijven weekstaten op hun gekoppelde projecten; uitvoerders keuren die per week (keurrecht per
        uitvoerder↔project) en melden meerwerk; een detacheerder vult in namens de aan hem gekoppelde ZZP'ers.
        Zelfde mobiele app en passkey-flow als de accordeurs.
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
                <th />
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
                      {g.rol !== 'detacheerder' && (
                        <>
                          {(info?.projecten ?? []).map((t) => (
                            <span key={`${t.administratie_id}-${t.project_id}`}>
                              <Badge variant="info">{t.project_naam ?? t.project_id}</Badge>{' '}
                            </span>
                          ))}
                          {info !== undefined && (
                            <Button variant="ghost" maat="klein" onClick={() => setProjectModal(info)}>
                              {info.projecten.length === 0 ? 'projecten koppelen' : 'wijzig'}
                            </Button>
                          )}
                          {info !== undefined && info.projecten.length === 0 && (
                            <div style={{ fontSize: 11, color: 'var(--warn)', marginTop: 2 }}>
                              zonder projectkoppeling ziet deze {g.rol === 'zzper' ? "ZZP'er" : 'uitvoerder'} niets
                            </div>
                          )}
                        </>
                      )}
                      {g.rol === 'detacheerder' && (
                        <>
                          {(info?.zzpers ?? []).map((z) => (
                            <span key={z.gebruiker_id}>
                              <Badge variant="info">{z.naam}</Badge>{' '}
                            </span>
                          ))}
                          {info !== undefined && (
                            <Button variant="ghost" maat="klein" onClick={() => setZzperModal(info)}>
                              {info.zzpers.length === 0 ? "ZZP'ers koppelen" : 'wijzig'}
                            </Button>
                          )}
                        </>
                      )}
                    </td>
                    <td>
                      {g.status === 'actief' && <Badge variant="ok">actief</Badge>}
                      {g.status === 'geblokkeerd' && <Badge variant="danger">geblokkeerd</Badge>}
                      {g.status === 'uitgenodigd' && <Badge variant="stil">uitgenodigd</Badge>}
                      {g.status === 'wacht_op_passkey' && <Badge variant="warn">activatie onderbroken</Badge>}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>{actieKolom(g)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {projectModal && (
        <ProjectKoppelModal
          veldwerker={projectModal}
          administraties={administraties}
          onSluiten={() => setProjectModal(null)}
          onGewijzigd={() => {
            meld('Projectkoppelingen bijgewerkt — geauditeerd.')
            laad()
          }}
        />
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
    </div>
  )
}

/** Projecten koppelen per administratie: kies de administratie (alleen relevante), laad haar
 * projecten en beheer de set met een zoekbare MultiSelect (patroon ScopeModal). */
function ProjectKoppelModal({
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
  const [administratieId, setAdministratieId] = useState(administraties[0]?.id ?? '')
  const [projecten, setProjecten] = useState<{ id: string; naam: string | null }[] | null>(null)
  const [selectie, setSelectie] = useState<string[]>([])
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const huidige = veldwerker.projecten.filter((t) => t.administratie_id === administratieId).map((t) => t.project_id)

  useEffect(() => {
    if (!administratieId) return
    setProjecten(null)
    setSelectie(veldwerker.projecten.filter((t) => t.administratie_id === administratieId).map((t) => t.project_id))
    apiJson<ProjectLijstDto>(`/administraties/${administratieId}/projecten`)
      .then((data) => setProjecten(data.projecten))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Projecten laden mislukt'))
    // veldwerker verandert niet tijdens een open modal
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [administratieId])

  const erbij = selectie.filter((id) => !huidige.includes(id))
  const eraf = huidige.filter((id) => !selectie.includes(id))

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      for (const projectId of erbij) {
        await koppelProject({ administratie_id: administratieId, gebruiker_id: veldwerker.gebruiker_id, project_id: projectId })
      }
      for (const projectId of eraf) {
        await ontkoppelProject({ administratie_id: administratieId, gebruiker_id: veldwerker.gebruiker_id, project_id: projectId })
      }
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
        <DialogTitle>Projecten van {veldwerker.naam}</DialogTitle>
        <DialogDescription>
          {veldwerker.rol === 'uitvoerder'
            ? 'Een uitvoerder keurt de weekstaten van zijn gekoppelde projecten (keurrecht) en ziet daar de projectinhoud (specs, contract, meerwerk).'
            : "Een ZZP'er schrijft weekstaten op zijn gekoppelde projecten — zonder koppeling ziet hij niets."}{' '}
          Elke wijziging wordt geauditeerd; bestaande weekstaten en meerwerk blijven altijd staan.
        </DialogDescription>
        <FormField label="Administratie" htmlFor="koppel-administratie">
          <Select
            id="koppel-administratie"
            className="w-full"
            value={administratieId}
            onChange={(e) => setAdministratieId(e.target.value)}
          >
            {administraties.map((a) => (
              <option key={a.id} value={a.id}>
                {a.naam}
              </option>
            ))}
          </Select>
        </FormField>
        {projecten === null && !fout && <p className="hint">Projecten laden…</p>}
        {projecten !== null && (
          <MultiSelect
            opties={projecten.map((p) => ({ waarde: p.id, label: p.naam ?? p.id }))}
            waarden={selectie}
            onChange={setSelectie}
            zoekPlaceholder="Zoek project… (typ om te filteren)"
          />
        )}
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
