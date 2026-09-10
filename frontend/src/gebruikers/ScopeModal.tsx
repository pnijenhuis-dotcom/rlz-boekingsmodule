import { useMemo, useState } from 'react'
import type { AdministratieDto } from '../api/types'
import { ApiError } from '../api/client'
import { BevestigDialog } from '../instellingen/BevestigDialog'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { verwijderScope, voegScopeToe, type GebruikerOverzichtDto } from './gebruikersApi'
import { berekenVerschil, namenOpsomming, ScopeLijst, verschilTekst, type ScopeLijstItem } from './ScopeLijst'

/* Scope wijzigen (Gebruikers & toegang › Kantoor › ⋯ › Scope wijzigen…). Sinds blok 2 nachtrun 10/11-09 (kliktest
 * Peter 10-09 avond, 71 administraties) één doorzoekbare lijst over de dialooghoogte (ScopeLijst) i.p.v. MultiSelect
 * + chips-wolk; Opslaan toont het verschil ("+3 −1") en bevestigt eerst mét namen. Opslaan = het verschil doorvoeren
 * via de bestaande per-koppeling-endpoints (elke wijziging server-side gecontroleerd én geaudit; eigen scope
 * wijzigen weigert de backend — zelfbescherming). Geen backend-wijziging. */

/** Alle administraties voor de lijst: de actieve (GET /auth/administraties) + de gearchiveerde die nog in de scope
 * staan (naam + status uit de gebruikers-DTO; een id zonder naam blijft zichtbaar als "onbekende administratie"). */
export function scopeLijstItems(gebruiker: GebruikerOverzichtDto, administraties: AdministratieDto[]): ScopeLijstItem[] {
  const items = new Map<string, ScopeLijstItem>()
  for (const a of administraties) items.set(a.id, { id: a.id, naam: a.naam, actief: true })
  for (const a of gebruiker.administraties ?? []) {
    if (!items.has(a.id)) items.set(a.id, { id: a.id, naam: a.naam, actief: a.actief })
  }
  for (const id of gebruiker.administratie_ids) {
    if (!items.has(id)) items.set(id, { id, naam: 'onbekende administratie', actief: false })
  }
  return [...items.values()]
}

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
  const [bevestigen, setBevestigen] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const items = useMemo(() => scopeLijstItems(gebruiker, administraties), [gebruiker, administraties])
  const naamVan = useMemo(() => new Map(items.map((it) => [it.id, it.naam])), [items])
  const verschil = berekenVerschil(gebruiker.administratie_ids, scope)
  const tekst = verschilTekst(verschil)
  const geenVerschil = verschil.erbij.length === 0 && verschil.eraf.length === 0

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      for (const id of verschil.erbij) await voegScopeToe(gebruiker.id, id)
      for (const id of verschil.eraf) await verwijderScope(gebruiker.id, id)
      onGewijzigd()
      onSluiten()
    } catch (err) {
      setFout(
        err instanceof ApiError
          ? `${err.message} — al doorgevoerde wijzigingen blijven staan; de lijst wordt ververst.`
          : 'Scope wijzigen mislukt.',
      )
      setBevestigen(false)
      onGewijzigd()
    } finally {
      setBezig(false)
    }
  }

  const namen = (ids: string[]) => namenOpsomming(ids.map((id) => naamVan.get(id) ?? 'onbekende administratie'))
  const bevestigTekst =
    (verschil.erbij.length > 0
      ? `Erbij (${verschil.erbij.length}): ${namen(verschil.erbij)}. `
      : '') +
    (verschil.eraf.length > 0 ? `Eraf (${verschil.eraf.length}): ${namen(verschil.eraf)}. ` : '') +
    (scope.length === 0 ? 'LET OP: zonder scope ziet deze medewerker niets meer (RLS op databaseniveau). ' : '') +
    'Elke wijziging wordt geauditeerd.'

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent data-testid="scope-dialoog" className="flex max-h-[calc(100vh-32px)] flex-col">
        <DialogTitle>Scope van {gebruiker.naam}</DialogTitle>
        <DialogDescription className="mb-2">
          Zonder scope ziet een medewerker niets (RLS op databaseniveau). Elke wijziging wordt geauditeerd.
        </DialogDescription>
        <ScopeLijst
          items={items}
          geselecteerd={scope}
          onChange={setScope}
          oorspronkelijk={gebruiker.administratie_ids}
          disabled={bezig}
          zoekPlaceholder="Zoek administratie…"
          geenBevestigingTekst={`${gebruiker.naam} heeft nu toegang tot ${gebruiker.administratie_ids.length} ${
            gebruiker.administratie_ids.length === 1 ? 'administratie' : 'administraties'
          }. Zonder scope ziet ${gebruiker.naam} niets meer — de toegang wordt op databaseniveau afgedwongen (RLS). Dit haalt alle zichtbare administraties uit de selectie; de wijziging gaat pas door bij "Scope opslaan" en wordt geauditeerd.`}
        />
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => setBevestigen(true)} disabled={bezig || geenVerschil} data-testid="scope-opslaan">
            {bezig ? 'Bezig…' : geenVerschil ? 'Scope opslaan' : `Scope opslaan (${tekst})`}
          </Button>
        </DialogFooter>
        {bevestigen && (
          <BevestigDialog
            titel={`Scope van ${gebruiker.naam} wijzigen (${tekst})`}
            bericht={bevestigTekst}
            bezig={bezig}
            fout={fout}
            onBevestigen={() => void opslaan()}
            onAnnuleren={() => !bezig && setBevestigen(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
