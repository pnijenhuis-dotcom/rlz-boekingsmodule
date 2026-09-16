import { useState } from 'react'
import { ApiError } from '../api/client'
import type { AdministratieInstellingenDto, GroepDto } from '../api/types'
import { Badge, Button, useToastOptioneel } from '../ui/basis'
import { codeGeldig, codeVoorstel } from './groepen'
import { GroepLedenDialoog } from './GroepLedenDialoog'
import { maakGroepAan, wijzigGroep, type GroepBulkUitkomstDto } from './instellingenApi'

/** Klein blok "Groepen" op Instellingen › Administraties (lijstpagina) — blok 8 run 11-09: hernoemen, archiveren
 * (nooit verwijderen), heractiveren en een nieuwe groep aanmaken. Ingeklapt tot een linkbtn "groepen (N)"; leden
 * ken je toe per groep via "Administraties toevoegen…" (bulk-toewijzing 16-09, dialoog mét vinkjeslijst), op de
 * detailpagina (tab Algemeen) of in de wizard. Geen nav-item/tab → geen registry-entry nodig. */
export function GroepenBeheer({
  groepen,
  administraties = [],
  onGewijzigd,
}: {
  groepen: GroepDto[]
  /** Alle administraties (actief + gearchiveerd) voor de leden-dialoog; leeg = knop niet tonen. */
  administraties?: AdministratieInstellingenDto[]
  /** Ná élke mutatie: de lijst (en de administratie-lijst mét chips) herladen. */
  onGewijzigd: () => void
}) {
  const { meld } = useToastOptioneel()
  const [open, setOpen] = useState(false)
  const [ledenVoor, setLedenVoor] = useState<GroepDto | null>(null)
  const bulkGereed = (u: GroepBulkUitkomstDto) => {
    const overgeslagen = u.rijen.filter((r) => r.uitkomst === 'overgeslagen')
    const verhuisd = u.rijen.filter((r) => r.uitkomst === 'verhuisd').length
    const delen = [
      u.toegevoegd > 0 ? `${u.toegevoegd} toegevoegd${verhuisd > 0 ? ` (${verhuisd} verhuisd)` : ''}` : null,
      u.verwijderd > 0 ? `${u.verwijderd} eruit` : null,
      overgeslagen.length > 0 ? `${overgeslagen.length} overgeslagen (${overgeslagen.map((r) => `${r.naam}: ${r.detail}`).join('; ')})` : null,
    ].filter(Boolean)
    meld(`Groep ${u.groep.naam}: ${delen.join(', ') || 'niets gewijzigd'} — geauditeerd.`, overgeslagen.length > 0 ? 'warn' : 'ok')
    onGewijzigd()
  }
  const [hernoem, setHernoem] = useState<{ id: string; naam: string } | null>(null)
  const [nieuwNaam, setNieuwNaam] = useState('')
  const [nieuwCode, setNieuwCode] = useState('')
  const [codeHandmatig, setCodeHandmatig] = useState(false)
  const [bezig, setBezig] = useState(false)
  const [fout, setFout] = useState<string | null>(null)

  const doe = async (actie: () => Promise<unknown>) => {
    setBezig(true)
    setFout(null)
    try {
      await actie()
      onGewijzigd()
    } catch (err) {
      setFout(err instanceof ApiError ? err.message : 'Opslaan mislukt — probeer het opnieuw.')
    } finally {
      setBezig(false)
    }
  }

  const aanmaken = () =>
    doe(async () => {
      await maakGroepAan(nieuwNaam.trim(), nieuwCode)
      setNieuwNaam('')
      setNieuwCode('')
      setCodeHandmatig(false)
    })

  return (
    <div data-testid="groepen-beheer">
      <button type="button" className="linkbtn" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? '▾' : '▸'} groepen ({groepen.length})
      </button>
      {open && (
        <div className="panel" style={{ marginTop: 8, padding: 12 }}>
          <div className="hint" style={{ marginTop: 0 }}>
            Een groep is een kenmerk om administraties samen te filteren (klantenlijst, Inzicht › Reconciliatie, deze lijst).
            Leden kies je per groep via &ldquo;Administraties toevoegen…&rdquo;, per administratie op de detailpagina (Algemeen › Groep)
            of in de wizard. Groepen worden nooit verwijderd — archiveren houdt bestaande leden zichtbaar.
          </div>
          <div className="tabel-scroll">
          <table style={{ width: 'auto', minWidth: 420 }}>
            <thead>
              <tr>
                <th>Groep</th>
                <th>Code</th>
                <th>Leden</th>
                <th className="acties" style={{ textAlign: 'right' }}>
                  Acties
                </th>
              </tr>
            </thead>
            <tbody>
              {groepen.map((g) => (
                <tr key={g.id} style={{ opacity: g.actief ? 1 : 0.7 }}>
                  <td>
                    {hernoem?.id === g.id ? (
                      <input
                        aria-label={`Nieuwe naam voor ${g.naam}`}
                        value={hernoem.naam}
                        autoFocus
                        disabled={bezig}
                        onChange={(e) => setHernoem({ id: g.id, naam: e.target.value })}
                        onKeyDown={(e) => {
                          if (e.key === 'Escape') setHernoem(null)
                          if (e.key === 'Enter' && hernoem.naam.trim()) {
                            e.preventDefault()
                            void doe(() => wijzigGroep(g.id, { naam: hernoem.naam.trim() })).then(() => setHernoem(null))
                          }
                        }}
                      />
                    ) : (
                      <>
                        <b>{g.naam}</b> {!g.actief && <Badge variant="stil">gearchiveerd</Badge>}
                      </>
                    )}
                  </td>
                  <td>
                    <code>{g.code}</code>
                  </td>
                  <td>{g.aantal_administraties}</td>
                  <td className="acties" style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                    {hernoem?.id === g.id ? (
                      <>
                        <Button
                          maat="klein"
                          disabled={bezig || !hernoem.naam.trim()}
                          onClick={() => void doe(() => wijzigGroep(g.id, { naam: hernoem.naam.trim() })).then(() => setHernoem(null))}
                        >
                          Opslaan
                        </Button>{' '}
                        <button type="button" className="linkbtn" onClick={() => setHernoem(null)} disabled={bezig}>
                          annuleren
                        </button>
                      </>
                    ) : (
                      <>
                        {g.actief && administraties.length > 0 && (
                          <Button maat="klein" aria-label={`Administraties toevoegen aan ${g.naam}`} disabled={bezig} onClick={() => setLedenVoor(g)}>
                            Administraties toevoegen…
                          </Button>
                        )}
                        <Button variant="ghost" maat="klein" aria-label={`Hernoem ${g.naam}`} disabled={bezig} onClick={() => setHernoem({ id: g.id, naam: g.naam })}>
                          hernoemen
                        </Button>
                        {g.actief ? (
                          <Button variant="ghost" maat="klein" aria-label={`Archiveer ${g.naam}`} disabled={bezig} onClick={() => void doe(() => wijzigGroep(g.id, { actief: false }))}>
                            archiveren
                          </Button>
                        ) : (
                          <Button variant="ghost" maat="klein" aria-label={`Heractiveer ${g.naam}`} disabled={bezig} onClick={() => void doe(() => wijzigGroep(g.id, { actief: true }))}>
                            heractiveren
                          </Button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {groepen.length === 0 && (
                <tr>
                  <td colSpan={4} className="hint">
                    Nog geen groepen.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
          </div>
          <form
            style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginTop: 10 }}
            onSubmit={(e) => {
              e.preventDefault()
              void aanmaken()
            }}
          >
            <input
              aria-label="Naam nieuwe groep"
              placeholder="Nieuwe groep, bv. Kempen groep"
              value={nieuwNaam}
              disabled={bezig}
              style={{ width: 220 }}
              onChange={(e) => {
                setNieuwNaam(e.target.value)
                if (!codeHandmatig) setNieuwCode(codeVoorstel(e.target.value))
              }}
            />
            <input
              aria-label="Code nieuwe groep"
              placeholder="CODE"
              value={nieuwCode}
              disabled={bezig}
              maxLength={12}
              style={{ width: 120 }}
              onChange={(e) => {
                setCodeHandmatig(true)
                setNieuwCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ''))
              }}
            />
            <Button type="submit" maat="klein" disabled={bezig || !nieuwNaam.trim() || !codeGeldig(nieuwCode)}>
              {bezig ? 'Bezig…' : '+ Groep aanmaken'}
            </Button>
          </form>
          {fout && (
            <div className="fout" role="alert" style={{ marginTop: 6 }}>
              {fout}
            </div>
          )}
        </div>
      )}
      {ledenVoor && (
        <GroepLedenDialoog
          groep={ledenVoor}
          administraties={administraties}
          onSluiten={() => setLedenVoor(null)}
          onGewijzigd={bulkGereed}
        />
      )}
    </div>
  )
}
