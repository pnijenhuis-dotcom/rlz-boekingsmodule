// Topbar-knop "Wat is nieuw" + dialoog (best-practice-punt D1, 01-09) voor kantoorrollen: leest het
// hand-gecureerde WAT_IS_NIEUW.md (changelog.ts), toont een ongelezen-dot per gebruiker en markeert
// gelezen bij openen. Geen AI, geen server-infra.
import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '../ui/basis'
import { isOngelezen, markeerGelezen, RELEASES } from './changelog'

function datumLang(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('nl-NL', { day: 'numeric', month: 'long', year: 'numeric' })
}

export function WatIsNieuwKnop() {
  const { gebruikerId } = useAuth()
  const [open, setOpen] = useState(false)
  const [ongelezen, setOngelezen] = useState(() => isOngelezen(gebruikerId))

  const openen = () => {
    setOpen(true)
    markeerGelezen(gebruikerId)
    setOngelezen(false)
  }

  return (
    <>
      <button
        type="button"
        className="shell-iconknop wat-is-nieuw-knop"
        title="Wat is nieuw"
        aria-label={ongelezen ? 'Wat is nieuw — er is iets bijgekomen' : 'Wat is nieuw'}
        onClick={openen}
      >
        ✦{ongelezen && <span className="wat-is-nieuw-dot" data-testid="wat-is-nieuw-dot" aria-hidden />}
      </button>
      <Dialog open={open} onOpenChange={(o) => !o && setOpen(false)}>
        <DialogContent data-testid="wat-is-nieuw-dialoog" style={{ maxWidth: 620 }}>
          <DialogTitle>Wat is nieuw</DialogTitle>
          <DialogDescription>De laatste verbeteringen aan de boekingsmodule, in gewone taal.</DialogDescription>
          <div className="wat-is-nieuw-lijst">
            {RELEASES.slice(0, 8).map((r) => (
              <section key={r.id} className="wat-is-nieuw-release">
                <h3>
                  <span className="wat-is-nieuw-datum">{datumLang(r.datum)}</span> — {r.titel}
                </h3>
                <ul>
                  {r.punten.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </section>
            ))}
            {RELEASES.length === 0 && <p className="hint">Nog geen releases beschreven.</p>}
          </div>
          <DialogFooter>
            <Button variant="secundair" onClick={() => setOpen(false)}>
              Sluiten
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
