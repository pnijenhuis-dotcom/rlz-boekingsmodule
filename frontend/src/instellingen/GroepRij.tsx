import { useState } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieInstellingenDto } from '../api/types'
import { Badge } from '../ui/basis'
import { InstellingRij } from './AdministratieDetailPagina'
import { GroepVeld } from './GroepVeld'
import { useGroepen } from './groepen'
import { zetAdministratieGroep } from './instellingenApi'

/** Instellingenrij "Groep" op Instellingen › Administraties › ‹administratie› › Algemeen (blok 8 run 11-09,
 * migratie 0135): keuzelijst van groepen + inline "Nieuwe groep…"; opslaan = PUT /administraties/{id}/groep
 * (Beheerder-only, audit `administratie_groep_gewijzigd` oud→nieuw). Zelfde zelfstandige patroon als BtwDefaultRij
 * (eigen fetch/PUT, geen PendingToggle-dialoog: een groep is een kenmerk, geen geldpoort). Ná een wijziging herlaadt de
 * lijst (`onGewijzigd`) zodat chip en filter dezelfde stand zien. */
export function GroepRij({
  administratie: a,
  onGewijzigd,
}: {
  administratie: AdministratieInstellingenDto
  onGewijzigd?: () => void
}) {
  const { groepen, fout: laadFout, zet } = useGroepen(true)
  const [huidig, setHuidig] = useState<string | null>(a.groep_id ?? null)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)
  const [opgeslagen, setOpgeslagen] = useState(false)

  const wijzig = async (groepId: string | null) => {
    if (groepId === huidig) return
    setBezig(true)
    setFout(null)
    setOpgeslagen(false)
    try {
      const r = await zetAdministratieGroep(a.id, groepId)
      setHuidig(r.groep_id)
      setOpgeslagen(true)
      onGewijzigd?.()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const huidigeGroep = (groepen ?? []).find((g) => g.id === huidig)

  return (
    <InstellingRij
      titel="Groep"
      uitleg="Kenmerk voor filters op de klantenlijst, Inzicht › Reconciliatie en deze lijst (bv. “Kempen groep”). Hoogstens één groep; leeg = geen groep. Geen poort — niemand ziet hierdoor meer of minder."
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {groepen === null && !laadFout ? (
          <span className="hint" style={{ margin: 0 }}>
            groepen laden…
          </span>
        ) : (
          <GroepVeld
            ariaLabel={`Groep van ${a.naam}`}
            waarde={huidig}
            groepen={groepen ?? []}
            uitgeschakeld={bezig || Boolean(a.gearchiveerd_op)}
            onWijzig={(id) => void wijzig(id)}
            onGroepAangemaakt={zet}
          />
        )}
        {huidigeGroep && !huidigeGroep.actief && (
          <Badge variant="stil" title="De groep is gearchiveerd; deze administratie blijft lid tot je een andere kiest.">
            groep gearchiveerd
          </Badge>
        )}
        {laadFout && (
          <span className="text-[12px] text-orange" role="alert">
            groepen niet te laden — {laadFout}
          </span>
        )}
        {opgeslagen && !fout && <span className="text-[12px] text-ok">opgeslagen</span>}
        {fout && (
          <span className="text-[12px] text-red" role="alert">
            {fout}
          </span>
        )}
      </div>
    </InstellingRij>
  )
}
