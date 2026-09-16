import { useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieInstellingenDto, GroepDto } from '../api/types'
import { berekenVerschil, namenOpsomming, ScopeLijst, verschilTekst, type ScopeLijstItem } from '../gebruikers/ScopeLijst'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { BevestigDialog } from './BevestigDialog'
import { zetGroepAdministratiesBulk, type GroepBulkUitkomstDto } from './instellingenApi'

/* "Administraties toevoegen…" per groep (bulk-toewijzing 16-09; Peter: "nu moet ik 1 voor 1 doen"). Dezelfde
 * doorzoekbare vinkjeslijst als de scope-dialoog (ScopeLijst, BESLISSINGEN "SCOPE-DIALOOG: LIJST IN PLAATS VAN CHIPS"):
 * alle administraties, al-toegewezen aangevinkt, leden van een ANDERE groep mét die groepsnaam als chip (aanvinken =
 * verhuizen, bevestiging "N administraties verhuizen van groep X"), gearchiveerde onderaan. Opslaan toont "+N −M" en
 * gaat in één transactie via PUT /groepen/{id}/administraties (audit per administratie, server-side). */

export function groepLedenItems(
  groep: GroepDto,
  administraties: AdministratieInstellingenDto[],
): { items: ScopeLijstItem[]; leden: string[]; andereGroep: Map<string, string> } {
  const items: ScopeLijstItem[] = []
  const leden: string[] = []
  const andereGroep = new Map<string, string>()
  for (const a of administraties) {
    const inAndere = a.groep_id && a.groep_id !== groep.id ? a.groep_naam ?? 'andere groep' : null
    if (inAndere) andereGroep.set(a.id, inAndere)
    if (a.groep_id === groep.id) leden.push(a.id)
    items.push({ id: a.id, naam: a.naam, actief: !a.gearchiveerd_op, notitie: inAndere ? `groep: ${inAndere}` : undefined })
  }
  return { items, leden, andereGroep }
}

/** "3 administraties verhuizen van groep Vastgoedgroep; 1 van groep Oud" — gegroepeerd per oude groep. */
export function verhuisTekst(erbij: string[], andereGroep: Map<string, string>): string {
  const perGroep = new Map<string, number>()
  for (const id of erbij) {
    const g = andereGroep.get(id)
    if (g) perGroep.set(g, (perGroep.get(g) ?? 0) + 1)
  }
  return [...perGroep.entries()]
    .map(([g, n]) => `${n} ${n === 1 ? 'administratie verhuist' : 'administraties verhuizen'} van groep ${g}`)
    .join('; ')
}

export function GroepLedenDialoog({
  groep,
  administraties,
  onSluiten,
  onGewijzigd,
}: {
  groep: GroepDto
  administraties: AdministratieInstellingenDto[]
  onSluiten: () => void
  onGewijzigd: (uitkomst: GroepBulkUitkomstDto) => void
}) {
  const { items, leden, andereGroep } = useMemo(() => groepLedenItems(groep, administraties), [groep, administraties])
  const [keuze, setKeuze] = useState<string[]>(leden)
  const [bevestigen, setBevestigen] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const naamVan = useMemo(() => new Map(items.map((it) => [it.id, it.naam])), [items])
  const verschil = berekenVerschil(leden, keuze)
  const tekst = verschilTekst(verschil)
  const geenVerschil = verschil.erbij.length === 0 && verschil.eraf.length === 0
  const verhuizen = verhuisTekst(verschil.erbij, andereGroep)

  async function opslaan() {
    setBezig(true)
    setFout(null)
    try {
      const uitkomst = await zetGroepAdministratiesBulk(groep.id, { toevoegen: verschil.erbij, verwijderen: verschil.eraf })
      onGewijzigd(uitkomst)
      onSluiten()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt — probeer het opnieuw.')
      setBevestigen(false)
    } finally {
      setBezig(false)
    }
  }

  const namen = (ids: string[]) => namenOpsomming(ids.map((id) => naamVan.get(id) ?? 'onbekende administratie'))
  const bevestigTekst =
    (verschil.erbij.length > 0 ? `Erbij (${verschil.erbij.length}): ${namen(verschil.erbij)}. ` : '') +
    (verschil.eraf.length > 0 ? `Eruit (${verschil.eraf.length}): ${namen(verschil.eraf)}. ` : '') +
    (verhuizen ? `LET OP: ${verhuizen} — een administratie zit in hoogstens één groep. ` : '') +
    'Alles in één keer, per administratie geauditeerd.'

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent data-testid="groep-leden-dialoog" className="flex max-h-[calc(100vh-32px)] flex-col">
        <DialogTitle>Administraties in groep {groep.naam}</DialogTitle>
        <DialogDescription className="mb-2">
          Vink aan welke administraties bij deze groep horen. Een administratie zit in hoogstens één groep — een lid van een
          andere groep verhuist bij aanvinken (met bevestiging). Een groep is een filter, nooit een poort.
        </DialogDescription>
        <ScopeLijst
          items={items}
          geselecteerd={keuze}
          onChange={setKeuze}
          oorspronkelijk={leden}
          disabled={bezig}
          zoekPlaceholder="Zoek administratie…"
          geenBevestigingTekst={`Dit haalt alle zichtbare administraties uit groep ${groep.naam}; de wijziging gaat pas door bij opslaan en wordt geauditeerd.`}
          data-testid="groep-leden-lijst"
        />
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button variant="secundair" onClick={onSluiten} disabled={bezig}>
            Annuleren
          </Button>
          <Button onClick={() => setBevestigen(true)} disabled={bezig || geenVerschil} data-testid="groep-leden-opslaan">
            {bezig ? 'Bezig…' : geenVerschil ? 'Opslaan' : `Opslaan (${tekst})`}
          </Button>
        </DialogFooter>
        {bevestigen && (
          <BevestigDialog
            titel={`Groep ${groep.naam} wijzigen (${tekst})`}
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
