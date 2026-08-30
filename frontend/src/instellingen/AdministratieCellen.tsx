// Eigenaar-select en IBAN-accordeurs-cel (uit InstellingenScreen gelicht bij de v2-herbouw 30-08 — de
// cellen leven nu in de detail-dialoog per administratie, mockup instellingen-administraties-v2).
import { useEffect, useState } from 'react'
import type { AdministratieInstellingenDto } from '../api/types'
import { haalIbanAccordeursOp } from '../document/ibanAccorderingApi'
import { Badge, Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle, Select, SkeletonRegels } from '../ui/basis'
import { useMedewerkers } from '../vragen/useMedewerkers'

interface EigenaarCellProps {
  administratie: AdministratieInstellingenDto
  onKies: (eigenaarId: string | null, eigenaarNaam: string | undefined) => void
}

/** Eigenaar-select per administratie (mockup Instellingen "Eigenaar (krijgt vragen)"): de
 * toewijsbare medewerkers komen per rij uit het scope-gecontroleerde medewerkers-endpoint. */
export function EigenaarCell({ administratie, onKies }: EigenaarCellProps) {
  const { medewerkers, fout } = useMedewerkers(administratie.id)
  if (fout) return <span className="hint" style={{ margin: 0 }}>medewerkers niet te laden</span>
  return (
    <Select
      aria-label={`Eigenaar van ${administratie.naam}`}
      value={administratie.eigenaar_gebruiker_id ?? ''}
      disabled={!medewerkers}
      onChange={(e) => {
        const id = e.target.value || null
        onKies(id, medewerkers?.find((m) => m.id === id)?.naam)
      }}
    >
      <option value="">— geen eigenaar —</option>
      {(medewerkers ?? []).map((m) => (
        <option key={m.id} value={m.id}>
          {m.naam}
        </option>
      ))}
    </Select>
  )
}

interface IbanAccordeursCellProps {
  administratie: AdministratieInstellingenDto
  /** Bump na een geslaagde wijziging: de cel herlaadt dan zijn set van de backend. */
  versie: number
  onWijzig: (nieuweSet: string[], omschrijving: string) => void
}

/** Instelling "IBAN-wissel accorderen door" (vier-ogen-flow, docs/ontwerp/
 * iban-wissel-accordering.md): één of meer medewerkers binnen de scope. Compact in de rij
 * (feedbackronde 25-08 deel 3 punt 4a — de open checkbox-lijst maakte elke rij 4-6 regels hoog):
 * de gekozen namen als chips, of "beheerders (terugval)" zonder set, plus "wijzig" dat de
 * checkbox-lijst in een dialoog opent (patroon ScopeModal). Opslaan in de dialoog = één
 * bevestigde wijziging (PUT met de volledige nieuwe set), zoals voorheen per vinkje. */
export function IbanAccordeursCell({ administratie, versie, onWijzig }: IbanAccordeursCellProps) {
  const { medewerkers, fout: medewerkersFout } = useMedewerkers(administratie.id)
  const [accordeurs, setAccordeurs] = useState<string[] | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [concept, setConcept] = useState<string[]>([])

  useEffect(() => {
    haalIbanAccordeursOp(administratie.id)
      .then((dto) => setAccordeurs(dto.accordeurs))
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Onbekende fout'))
  }, [administratie.id, versie])

  if (fout || medewerkersFout) {
    return (
      <span className="hint" style={{ margin: 0 }}>
        accordeurs niet te laden
      </span>
    )
  }
  if (accordeurs === null || !medewerkers) {
    return (
      <SkeletonRegels regels={2} />
    )
  }
  const naamVan = (id: string) => medewerkers.find((m) => m.id === id)?.naam ?? 'onbekend'
  const gekozen = accordeurs.filter((id) => medewerkers.some((m) => m.id === id))
  const opslaan = () => {
    const erbij = concept.filter((id) => !accordeurs.includes(id)).map(naamVan)
    const eraf = accordeurs.filter((id) => !concept.includes(id)).map(naamVan)
    setOpen(false)
    if (erbij.length === 0 && eraf.length === 0) return
    const delen = [
      erbij.length ? `${erbij.join(', ')} ${erbij.length === 1 ? 'wordt' : 'worden'} IBAN-accordeur` : null,
      eraf.length ? `${eraf.join(', ')} ${eraf.length === 1 ? 'is' : 'zijn'} niet langer IBAN-accordeur` : null,
    ].filter(Boolean)
    onWijzig(concept, delen.join('; '))
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      {gekozen.length === 0 ? (
        <Badge variant="stil" title="Geen accordeurs ingesteld — een IBAN-wissel valt terug op de beheerder(s)">
          beheerders (terugval)
        </Badge>
      ) : (
        gekozen.map((id) => (
          <Badge key={id} variant="info">
            {naamVan(id)}
          </Badge>
        ))
      )}
      <Button
        variant="ghost"
        maat="klein"
        aria-label={`IBAN-accordeurs van ${administratie.naam} wijzigen`}
        onClick={() => {
          setConcept(gekozen)
          setOpen(true)
        }}
      >
        wijzig
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogTitle>IBAN-wissel accorderen door — {administratie.naam}</DialogTitle>
          <DialogDescription>
            Wie mag een IBAN-wissel accorderen (vier ogen — nooit de aanvrager zelf)? Zonder keuze valt de
            accordering terug op de beheerder(s). Opslaan vraagt één bevestiging en wordt geauditeerd.
          </DialogDescription>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, margin: '10px 0' }}>
            {medewerkers.map((m) => (
              <label key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 8, margin: 0, fontSize: 13 }}>
                <Checkbox
                  checked={concept.includes(m.id)}
                  onChange={(e) =>
                    setConcept((huidig) => (e.target.checked ? [...huidig, m.id] : huidig.filter((id) => id !== m.id)))
                  }
                />
                {m.naam}
              </label>
            ))}
            {medewerkers.length === 0 && (
              <span className="hint" style={{ margin: 0 }}>
                Geen medewerkers met scope op deze administratie.
              </span>
            )}
          </div>
          <DialogFooter>
            <Button variant="secundair" onClick={() => setOpen(false)}>
              Annuleren
            </Button>
            <Button onClick={opslaan}>Opslaan</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

