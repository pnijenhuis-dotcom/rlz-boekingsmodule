import { useCallback, useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { ApiError, apiJson } from '../api/client'
import type { AdministratieInstellingenDto, AdministratieInstellingenLijstDto, BoekenIngeschakeldDto } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { BevestigDialog } from './BevestigDialog'

type WijzigingType = 'kill_switch' | 'boeken' | 'project'

interface PendingWijziging {
  type: WijzigingType
  administratieId?: string
  naam: string
  nieuweWaarde: boolean
}

function berichtVoor(pending: PendingWijziging): string {
  switch (pending.type) {
    case 'kill_switch':
      return pending.nieuweWaarde
        ? 'Boeken wordt platformbreed weer mogelijk (nog steeds ook afhankelijk van de boeken-toggle per administratie).'
        : 'Boeken wordt voor ALLE administraties direct stopgezet, ongeacht de toggle per administratie.'
    case 'boeken':
      return pending.nieuweWaarde
        ? `Boeken wordt ingeschakeld voor "${pending.naam}".`
        : `Boeken wordt uitgeschakeld voor "${pending.naam}".`
    case 'project':
      return pending.nieuweWaarde
        ? `Project wordt verplicht bij boeken voor "${pending.naam}" — regels zonder project blokkeren dan het boeken.`
        : `Project is niet langer verplicht bij boeken voor "${pending.naam}".`
  }
}

async function voerWijzigingUit(pending: PendingWijziging): Promise<void> {
  const init = { method: 'PUT', headers: { 'Content-Type': 'application/json' } }
  if (pending.type === 'kill_switch') {
    await apiJson<BoekenIngeschakeldDto>('/instellingen/boeken-kill-switch', {
      ...init,
      body: JSON.stringify({ ingeschakeld: pending.nieuweWaarde }),
    })
    return
  }
  if (pending.type === 'boeken') {
    await apiJson<BoekenIngeschakeldDto>(`/administraties/${pending.administratieId}/boeken-instelling`, {
      ...init,
      body: JSON.stringify({ ingeschakeld: pending.nieuweWaarde }),
    })
    return
  }
  await apiJson(`/administraties/${pending.administratieId}/project-instelling`, {
    ...init,
    body: JSON.stringify({ verplicht: pending.nieuweWaarde }),
  })
}

export function InstellingenScreen() {
  const { rol, status } = useAuth()

  const [administraties, setAdministraties] = useState<AdministratieInstellingenDto[] | null>(null)
  const [killSwitch, setKillSwitch] = useState<boolean | null>(null)
  const [laadFout, setLaadFout] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingWijziging | null>(null)
  const [bezig, setBezig] = useState(false)
  const [wijzigenFout, setWijzigenFout] = useState<string | null>(null)

  const laadAlles = useCallback(() => {
    setLaadFout(null)
    Promise.all([
      apiJson<AdministratieInstellingenLijstDto>('/instellingen/administraties'),
      apiJson<BoekenIngeschakeldDto>('/instellingen/boeken-kill-switch'),
    ])
      .then(([lijst, switchDto]) => {
        setAdministraties(lijst.administraties)
        setKillSwitch(switchDto.ingeschakeld)
      })
      .catch((err: unknown) => setLaadFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [])

  useEffect(() => {
    if (rol === 'beheerder') laadAlles()
  }, [rol, laadAlles])

  // Backend dwingt dit al af op elk endpoint hieronder — dit is de UI-kant: niet-Beheerders zien
  // het scherm niet eens (design-pass taak 3), geen kale 403 of lege tabel. Wacht op `status` (niet
  // alleen `rol`) zodat dit ook correct is als dit scherm ooit los van App.tsx's status==='laden'-
  // gate gemount wordt — anders redirect het al vóórdat de stille sessie-refresh de rol kent.
  if (status === 'laden') {
    return <p className="hint">Laden…</p>
  }
  if (rol !== 'beheerder') {
    return <Navigate to="/" replace />
  }

  const bevestigen = async () => {
    if (!pending) return
    setBezig(true)
    setWijzigenFout(null)
    try {
      await voerWijzigingUit(pending)
      if (pending.type === 'kill_switch') {
        setKillSwitch(pending.nieuweWaarde)
      } else {
        setAdministraties(
          (huidig) =>
            huidig?.map((a) =>
              a.id === pending.administratieId
                ? {
                    ...a,
                    ...(pending.type === 'boeken'
                      ? { boeken_ingeschakeld: pending.nieuweWaarde }
                      : { project_verplicht: pending.nieuweWaarde }),
                  }
                : a,
            ) ?? null,
        )
      }
      setPending(null)
    } catch (err) {
      setWijzigenFout(err instanceof ApiError ? err.message : 'Wijzigen mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <div>
      <div className="topbar">
        <h1>Instellingen</h1>
      </div>

      {laadFout && <div className="fout">Kon instellingen niet laden: {laadFout}</div>}

      <div className="panel">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h2 style={{ margin: 0 }}>Boeken — globale kill switch</h2>
            <p className="hint" style={{ marginTop: 4, marginBottom: 0 }}>
              Platformbrede noodstop: staat deze uit, dan kan er nergens geboekt worden, ongeacht de toggle per
              administratie hieronder.
            </p>
          </div>
          {killSwitch !== null && (
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
              <input
                type="checkbox"
                style={{ width: 'auto' }}
                checked={killSwitch}
                onChange={(e) =>
                  setPending({ type: 'kill_switch', naam: 'kill switch', nieuweWaarde: e.target.checked })
                }
              />
              {killSwitch ? 'aan' : 'uit'}
            </label>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h2 style={{ marginTop: 0 }}>Administraties</h2>
        {administraties === null && !laadFout && <p className="hint">Laden…</p>}
        {administraties !== null && administraties.length === 0 && (
          <p className="hint">Nog geen administraties gekoppeld.</p>
        )}
        {administraties !== null && administraties.length > 0 && (
          <table>
            <tbody>
              <tr>
                <th>Administratie</th>
                <th>Project verplicht bij boeken</th>
                <th>Boeken ingeschakeld</th>
              </tr>
              {administraties.map((a) => (
                <tr key={a.id}>
                  <td>{a.naam}</td>
                  <td>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                      <input
                        type="checkbox"
                        style={{ width: 'auto' }}
                        checked={a.project_verplicht}
                        onChange={(e) =>
                          setPending({
                            type: 'project',
                            administratieId: a.id,
                            naam: a.naam,
                            nieuweWaarde: e.target.checked,
                          })
                        }
                      />
                      {a.project_verplicht ? 'aan' : 'uit'}
                    </label>
                  </td>
                  <td>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                      <input
                        type="checkbox"
                        style={{ width: 'auto' }}
                        checked={a.boeken_ingeschakeld}
                        onChange={(e) =>
                          setPending({
                            type: 'boeken',
                            administratieId: a.id,
                            naam: a.naam,
                            nieuweWaarde: e.target.checked,
                          })
                        }
                      />
                      {a.boeken_ingeschakeld ? 'aan' : 'uit'}
                    </label>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {pending && (
        <BevestigDialog
          titel="Instelling wijzigen?"
          bericht={berichtVoor(pending)}
          bezig={bezig}
          fout={wijzigenFout}
          onBevestigen={() => void bevestigen()}
          onAnnuleren={() => {
            setWijzigenFout(null)
            setPending(null)
          }}
        />
      )}
    </div>
  )
}
