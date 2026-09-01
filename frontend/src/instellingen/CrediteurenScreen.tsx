// Inzicht › Crediteuren (Instellingen v3, ontwerpnotitie ⑤ — akkoord Peter 01-09): de
// dubbel-signalering per administratie (btw-/KvK-nummer, IBAN, genormaliseerde naam) is een
// signaleringsscherm, geen instelling — verhuisd uit Instellingen; /instellingen/crediteuren
// redirect hierheen. Rolpoort ongewijzigd: Beheerder (de leeslijst /instellingen/administraties
// én de dubbelen-endpoints weigeren andere rollen; de UI rendert dan een leesbare melding).
import { useEffect, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { SkeletonRegels } from '../ui/basis'
import { CrediteurDubbelen } from './CrediteurDubbelen'
import { haalInstellingenAdministratiesOp } from './instellingenApi'

export function CrediteurenScreen() {
  const { rol, status } = useAuth()
  const [administraties, setAdministraties] = useState<{ id: string; naam: string }[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)

  useEffect(() => {
    if (rol !== 'beheerder') return
    let actief = true
    haalInstellingenAdministratiesOp()
      .then((r) => {
        if (actief) setAdministraties(r.administraties.map((a) => ({ id: a.id, naam: a.naam })))
      })
      .catch((err: unknown) => {
        if (actief) setFout(err instanceof Error ? err.message : 'Onbekende fout')
      })
    return () => {
      actief = false
    }
  }, [rol])

  if (status === 'laden') return <SkeletonRegels />
  return (
    <div>
      <div className="topbar">
        <div>
          <div className="mb-1 text-[12.5px] text-muted">Inzicht</div>
          <h1>Crediteuren</h1>
        </div>
      </div>
      {rol !== 'beheerder' ? (
        <p className="hint">De crediteuren-dubbelsignalering is alleen beschikbaar voor de Beheerder.</p>
      ) : fout ? (
        <div className="fout">Kon de administraties niet laden: {fout}</div>
      ) : administraties === null ? (
        <SkeletonRegels />
      ) : (
        <CrediteurDubbelen administraties={administraties} />
      )}
    </div>
  )
}
