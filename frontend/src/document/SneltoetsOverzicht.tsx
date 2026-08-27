import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { SNELTOETS_OMSCHRIJVING, SNELTOETSEN_CONTROLESCHERM, SNELTOETSEN_LIJST } from './sneltoetsen'

/** Sneltoets-overzicht via "?" (punt 5): één tabel, alle toetsen van controlescherm + lijst. */
export function SneltoetsOverzicht({ onSluiten }: { onSluiten: () => void }) {
  return (
    <Dialog open onOpenChange={(open) => !open && onSluiten()}>
      <DialogContent aria-describedby="sneltoets-uitleg">
        <DialogTitle>Sneltoetsen</DialogTitle>
        <DialogDescription id="sneltoets-uitleg">
          Werken zonder muis op het controlescherm. Sneltoetsen doen niets zolang de cursor in een invoerveld staat
          of een dialoog open is.
        </DialogDescription>
        <table className="lines sneltoets-tabel">
          <tbody>
            <tr>
              <th style={{ width: 70 }}>Toets</th>
              <th>Actie</th>
            </tr>
            {[...SNELTOETSEN_CONTROLESCHERM, ...SNELTOETSEN_LIJST].map((b) => (
              <tr key={b.actie}>
                <td>
                  <kbd className="kbd">{b.label}</kbd>
                </td>
                <td>{SNELTOETS_OMSCHRIJVING[b.actie]}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <DialogFooter>
          <Button type="button" onClick={onSluiten}>
            Sluiten
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
