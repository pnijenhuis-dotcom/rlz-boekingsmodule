import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'

interface Props {
  titel: string
  bericht: string
  bezig: boolean
  fout: string | null
  onBevestigen: () => void
  onAnnuleren: () => void
}

/** Generieke bevestigingsdialoog voor beheerinstellingen (design-pass taak 3: "elke wijziging
 * toont een bevestiging"). Sinds de v2-herbouw van Instellingen › Administraties (30-08) een Radix-
 * dialoog (ui/basis): hij opent bóven de detail-dialoog per administratie — geneste modals stapelen
 * dan correct (focus, aria-hidden), waar de oude eigen modal onder de Radix-laag verborgen raakte.
 * Geen redenveld: dit zijn schakelaars, geen document-actie met audit-reden. */
export function BevestigDialog({ titel, bericht, bezig, fout, onBevestigen, onAnnuleren }: Props) {
  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onAnnuleren()}>
      <DialogContent aria-describedby={undefined} data-testid="bevestig-dialoog">
        <DialogTitle>{titel}</DialogTitle>
        <DialogDescription>{bericht}</DialogDescription>
        {fout && <div className="fout">{fout}</div>}
        <DialogFooter>
          <Button type="button" variant="secundair" onClick={onAnnuleren} disabled={bezig}>
            Annuleren
          </Button>
          <Button type="button" onClick={onBevestigen} disabled={bezig}>
            {bezig ? 'Bezig…' : 'Bevestigen'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
