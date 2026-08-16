import { useState } from 'react'
import type { AdministratieDto } from '../api/types'
import { ApiError } from '../api/client'
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
  MultiSelect,
} from '../ui/basis'
import { verwijderScope, voegScopeToe, type GebruikerOverzichtDto } from './gebruikersApi'

/* Scope wijzigen (Gebruikers & toegang): zoekbare MultiSelect (schaal 50+), opslaan = het
 * verschil doorvoeren via de bestaande per-koppeling-endpoints (elke wijziging server-side
 * gecontroleerd én geaudit; eigen scope wijzigen weigert de backend — zelfbescherming). */
export function ScopeModal({
  gebruiker,
  administraties,
  onSluiten,
  onGewijzigd,
}: {
  gebruiker: GebruikerOverzichtDto
  administraties: AdministratieDto[]
  onSluiten: () => void
  onGewijzigd: () => void
}) {
  const [scope, setScope] = useState<string[]>(gebruiker.administratie_ids)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const erbij = scope.filter((id) => !gebruiker.administratie_ids.includes(id))
  const eraf = gebruiker.administratie_ids.filter((id) => !scope.includes(id))

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      for (const id of erbij) await voegScopeToe(gebruiker.id, id)
      for (const id of eraf) await verwijderScope(gebruiker.id, id)
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(
        err instanceof ApiError
          ? `${err.message} — al doorgevoerde wijzigingen blijven staan; de lijst wordt ververst.`
          : 'Scope wijzigen mislukt.',
      )
      onGewijzigd()
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent>
        <DialogTitle>Scope van {gebruiker.naam}</DialogTitle>
        <DialogDescription>
          Zonder scope ziet een medewerker niets (RLS op databaseniveau). Elke wijziging wordt geauditeerd.
        </DialogDescription>
        <MultiSelect
          opties={administraties.map((a) => ({ waarde: a.id, label: a.naam }))}
          waarden={scope}
          onChange={setScope}
          zoekPlaceholder="Zoek administratie… (typ om te filteren)"
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
            {bezig ? 'Bezig…' : 'Scope opslaan'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
