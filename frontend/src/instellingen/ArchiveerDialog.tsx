// Archiveren-bevestiging (v2 30-08, 🗑 — nooit verwijderen), sinds Instellingen v3 (01-09) gedeeld
// door de administraties-tabel én de administratie-detailpagina: één dialoog, één endpoint.
import { useState } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieInstellingenDto } from '../api/types'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { archiveerAdministratie } from './instellingenApi'

export function ArchiveerDialog({
  administratie,
  onSluiten,
  onGearchiveerd,
}: {
  administratie: AdministratieInstellingenDto | null
  onSluiten: () => void
  /** Leesbare uitkomst (login ingetrokken, open werk) — de aanroeper toont 'm als statusregel. */
  onGearchiveerd: (melding: string) => void
}) {
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const archiveer = async () => {
    if (!administratie) return
    setBezig(true)
    setFout(null)
    try {
      const r = await archiveerAdministratie(administratie.id)
      onGearchiveerd(
        `"${administratie.naam}" gearchiveerd: webservice-login ${r.credential_ingetrokken ? 'ingetrokken' : 'was er niet'}, syncs gestopt, documenten en historie blijven staan${
          r.open_documenten > 0 ? ` — let op: ${r.open_documenten} open document${r.open_documenten === 1 ? '' : 'en'}` : ''
        }.`,
      )
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Archiveren mislukt.')
    } finally {
      setBezig(false)
    }
  }

  return (
    <Dialog open={administratie !== null} onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="archiveer-dialoog">
        <DialogTitle>Archiveren — {administratie?.naam}</DialogTitle>
        <DialogDescription>
          De webservice-login wordt uit de credential-store ingetrokken, syncs en jobs stoppen, de administratie verdwijnt uit alle
          werk-lijsten en uit de registersync voor Vastly. Documenten, boekingen en historie blijven bewaard — er wordt niets verwijderd.
          Terugzetten kan later mét een nieuwe webservice-login.
        </DialogDescription>
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="ghost" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => void archiveer()} disabled={bezig}>
            {bezig ? 'Bezig…' : 'Archiveren'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
