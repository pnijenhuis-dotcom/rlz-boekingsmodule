// Klant-accordering (Peter 18-09, live meegekeken bij BLOW): de melding "Geen klant-accordeurs met toegang tot deze
// administratie" was signalering zónder handeling (kernprincipe 7.2). Nu twee acties op de regel:
//   • "Accordeur uitnodigen →"  = Gebruikers & toegang, uitnodigingsformulier voorgevuld (rol Klant-accordeur + deze
//     administratie in scope) via `?groep=accordeurs&uitnodig=accordeur&administratie=<id>`;
//   • "Bestaande accordeur koppelen →" = lijst van álle klant-accordeurs van het kantoor mét vinkje voor deze administratie —
//     aanvinken = de BESTAANDE scope-route (`POST /auth/gebruikers/{id}/scope`, Beheerder-only, audit server-side); geen
//     tweede schrijver. Loskoppelen blijft bewust op Gebruikers & toegang (daar staat de vervallen-rondes-waarschuwing).
// Dezelfde melding + acties staan in de leveranciersroute-editor als de accordeurlijst leeg is.
import { useCallback, useEffect, useState } from 'react'
import { Link, useInRouterContext } from 'react-router-dom'
import { haalAccorderingKandidaten, haalAlleAccordeurKandidaten, type KandidaatDto } from '../accordering/accorderingApi'
import { voegScopeToe } from '../gebruikers/gebruikersApi'
import { Checkbox, Dialog, DialogContent, DialogDescription, DialogTitle } from '../ui/basis'

export function uitnodigAccordeurUrl(administratieId: string): string {
  return `/gebruikers?groep=accordeurs&uitnodig=accordeur&administratie=${encodeURIComponent(administratieId)}`
}

export function GeenAccordeursMelding({
  administratieId,
  naam,
  isBeheerder,
  onGekoppeld,
  compact = false,
}: {
  administratieId: string
  naam: string
  isBeheerder: boolean
  /** Ná een geslaagde koppeling: de aanroeper herlaadt de kandidatenlijst. */
  onGekoppeld: () => void
  /** In de route-editor: kortere tekst. */
  compact?: boolean
}) {
  const inRouter = useInRouterContext()
  const [koppelOpen, setKoppelOpen] = useState(false)
  const url = uitnodigAccordeurUrl(administratieId)
  return (
    <div className="hint" style={{ margin: 0, display: 'flex', flexWrap: 'wrap', gap: '4px 12px', alignItems: 'center' }} data-testid="geen-accordeurs-melding">
      <span>
        {compact
          ? 'Geen klant-accordeurs met toegang tot deze administratie.'
          : 'Geen klant-accordeurs met toegang tot deze administratie — nodig een gebruiker uit met de rol Klant-accordeur of koppel een bestaande accordeur.'}
      </span>
      {inRouter ? (
        <Link className="linkbtn" to={url} data-testid="accordeur-uitnodigen">
          Accordeur uitnodigen →
        </Link>
      ) : (
        <a className="linkbtn" href={url} data-testid="accordeur-uitnodigen">
          Accordeur uitnodigen →
        </a>
      )}
      {isBeheerder && (
        <button type="button" className="linkbtn" onClick={() => setKoppelOpen(true)} data-testid="accordeur-koppelen">
          Bestaande accordeur koppelen →
        </button>
      )}
      {koppelOpen && (
        <KoppelAccordeurDialoog
          administratieId={administratieId}
          naam={naam}
          onSluiten={() => setKoppelOpen(false)}
          onGekoppeld={onGekoppeld}
        />
      )}
    </div>
  )
}

/** Alle klant-accordeurs van het kantoor mét vinkje "toegang tot ‹naam›"; aanvinken = bestaande scope-route (audit). */
export function KoppelAccordeurDialoog({
  administratieId,
  naam,
  onSluiten,
  onGekoppeld,
}: {
  administratieId: string
  naam: string
  onSluiten: () => void
  onGekoppeld: () => void
}) {
  const [alle, setAlle] = useState<KandidaatDto[] | null>(null)
  const [gekoppeld, setGekoppeld] = useState<Set<string>>(new Set())
  const [bezig, setBezig] = useState<string | null>(null)
  const [fout, setFout] = useState<string | null>(null)
  const [zoek, setZoek] = useState('')

  const laad = useCallback(() => {
    setFout(null)
    Promise.all([
      haalAlleAccordeurKandidaten(),
      // Wie al toegang heeft (kandidaten van déze administratie) — vinkje aan + vergrendeld.
      haalAccorderingKandidaten(administratieId),
    ])
      .then(([allen, huidige]) => {
        setAlle(allen.kandidaten)
        setGekoppeld(new Set(huidige.kandidaten.map((k) => k.id)))
      })
      .catch((err: unknown) => setFout(err instanceof Error ? err.message : 'Accordeurs laden mislukt'))
  }, [administratieId])

  useEffect(() => {
    laad()
  }, [laad])

  const koppel = async (gebruikerId: string) => {
    setBezig(gebruikerId)
    setFout(null)
    try {
      await voegScopeToe(gebruikerId, administratieId)
      setGekoppeld((h) => new Set([...h, gebruikerId]))
      onGekoppeld()
    } catch (err) {
      setFout(err instanceof Error ? err.message : 'Koppelen mislukt')
    } finally {
      setBezig(null)
    }
  }

  const term = zoek.trim().toLowerCase()
  const zichtbaar = (alle ?? []).filter((k) => !term || k.naam.toLowerCase().includes(term))

  return (
    <Dialog open onOpenChange={(open) => !open && !bezig && onSluiten()}>
      <DialogContent aria-describedby={undefined} data-testid="koppel-accordeur-dialoog" style={{ maxWidth: 520 }}>
        <DialogTitle>Bestaande accordeur koppelen — {naam}</DialogTitle>
        <DialogDescription>
          Vink een klant-accordeur aan om die toegang te geven tot deze administratie (scope-wijziging, vastgelegd in het
          audit log). Toegang intrekken doet u op Gebruikers &amp; toegang — daar ziet u ook welke lopende rondes dat raakt.
        </DialogDescription>
        {fout && <div className="fout">{fout}</div>}
        {alle === null && !fout ? (
          <p className="hint">Laden…</p>
        ) : alle !== null && alle.length === 0 ? (
          <p className="hint" style={{ margin: 0 }}>
            Er zijn nog geen klant-accordeurs in het kantoor —{' '}
            <a className="linkbtn" href={uitnodigAccordeurUrl(administratieId)}>
              nodig er een uit →
            </a>
          </p>
        ) : (
          <>
            {(alle?.length ?? 0) > 8 && (
              <input
                type="search"
                aria-label="Zoek accordeur"
                placeholder="Zoek accordeur…"
                value={zoek}
                onChange={(e) => setZoek(e.target.value)}
                style={{ width: '100%', marginBottom: 8 }}
              />
            )}
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 6, maxHeight: 360, overflowY: 'auto' }}>
              {zichtbaar.map((k) => {
                const al = gekoppeld.has(k.id)
                return (
                  <li key={k.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Checkbox
                      aria-label={`Toegang voor ${k.naam}`}
                      checked={al}
                      disabled={al || bezig !== null}
                      onChange={() => void koppel(k.id)}
                    />
                    <span>{k.naam}</span>
                    {al && <span className="chip geheugen">al gekoppeld</span>}
                    {bezig === k.id && <span className="hint">koppelen…</span>}
                  </li>
                )
              })}
              {zichtbaar.length === 0 && <li className="hint">Geen accordeur past bij &quot;{zoek.trim()}&quot;.</li>}
            </ul>
          </>
        )}
        <div className="actions" style={{ marginTop: 10 }}>
          <button type="button" className="btn secondary" onClick={onSluiten} disabled={bezig !== null}>
            Sluiten
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
